"""
Qwen Vision & LLM Client for Internal Server (2x NVIDIA H200)
Replaces both Cosmos local video model and Gemini 2.5 cloud model.
Provides dense frame extraction, multimodal vision reasoning, and agent conversations.
"""

import base64
import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import requests
from dotenv import load_dotenv

import config

logger = logging.getLogger(__name__)


def extract_dense_frames(
    clip_path: Path | str,
    num_frames: int = 4,
    max_dim: int = 400,
    jpeg_quality: int = 40,
) -> List[Tuple[float, str]]:
    """
    Extract evenly distributed dense frames across a video clip.
    Returns a list of (timestamp_seconds, base64_data_url).
    """
    clip_path = Path(clip_path)
    if not clip_path.is_file():
        raise FileNotFoundError(f"Video clip not found: {clip_path}")

    cap = cv2.VideoCapture(str(clip_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video file via OpenCV: {clip_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps if fps > 0 else 0.0

    if total_frames <= 0:
        cap.release()
        raise RuntimeError(f"Video has zero frames: {clip_path}")

    # Determine frame indices to extract
    target_count = min(num_frames, total_frames)
    if target_count <= 1:
        indices = [0]
    else:
        step = (total_frames - 1) / (target_count - 1)
        indices = [int(round(i * step)) for i in range(target_count)]

    extracted = []
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), jpeg_quality]

    for frame_idx in indices:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret or frame is None:
            continue

        ts_sec = round(frame_idx / fps, 2)

        # Scale down while maintaining aspect ratio
        h, w = frame.shape[:2]
        if max(h, w) > max_dim:
            scale = max_dim / float(max(h, w))
            new_w = int(round(w * scale))
            new_h = int(round(h * scale))
            frame = cv2.resize(frame, (new_w, new_h), interpolation=cv2.INTER_AREA)

        # Encode to JPEG in memory
        success, buffer = cv2.imencode(".jpg", frame, encode_params)
        if not success:
            continue

        b64_str = base64.b64encode(buffer).decode("utf-8")
        data_url = f"data:image/jpeg;base64,{b64_str}"
        extracted.append((ts_sec, data_url))

    cap.release()
    logger.info(f"[DenseFrameExtractor] Extracted {len(extracted)} frames from {clip_path.name} (duration: {duration_sec:.1f}s)")
    return extracted


def clean_repetitive_text(text: str) -> str:
    """
    Loại bỏ hiện tượng thoái hóa lặp từ vô tận của LLM (token repetition degeneration).
    Ví dụ: 'tuy tuy tuy tuy...', 'cụ thể cụ thể cụ thể...', hoặc lặp cụm từ/âm tiết liên tiếp.
    """
    if not text:
        return text

    # 1. Lặp âm tiết dính liền nhau trong từ: 'chuchuchu' -> 'chu', 'aaaaa' -> 'a'
    text = re.sub(r'([a-zA-Z\u00C0-\u1EF9]{2,6})\1{2,}', r'\1', text, flags=re.IGNORECASE)
    text = re.sub(r'([a-zA-Z\u00C0-\u1EF9])\1{3,}', r'\1', text, flags=re.IGNORECASE)

    # 2. Lặp 1 từ >= 2 lần liên tiếp: 'chu chu chu...' -> 'chu'
    text = re.sub(r'(\b\S+\b)(?:\s+\1){2,}', r'\1', text, flags=re.IGNORECASE)

    # 3. Lặp cụm 2 từ >= 2 lần liên tiếp
    text = re.sub(r'(\b\S+\s+\S+\b)(?:\s+\1){2,}', r'\1', text, flags=re.IGNORECASE)

    # 4. Lặp cụm 3 từ >= 2 lần liên tiếp
    text = re.sub(r'(\b\S+\s+\S+\s+\S+\b)(?:\s+\1){2,}', r'\1', text, flags=re.IGNORECASE)

    # 5. Dọn dẹp các cụm từ lặp lại ở cuối dòng / cuối đoạn (ví dụ: 'khuyen nghj khuyến nghj khuyen', 'chu chu...')
    text = re.sub(r'(\b[a-zA-Z\u00C0-\u1EF9]{2,}\b)(?:\s+\1){1,}', r'\1', text, flags=re.IGNORECASE)

    # 6. Loại bỏ phần đuôi thoái hóa vô nghĩa (ví dụ: 'chu Chú Cúc Cuc uc u', 'aa aa A', lặp từ lẻ)
    lines = []
    for line in text.splitlines():
        # Nếu dòng kết thúc bằng chuỗi 2+ từ ngắn lặp hoặc đuôi vô nghĩa
        line = re.sub(r'(?:\s+[a-zA-Z\u00C0-\u1EF9]{1,4}){3,}\s*$', '.', line)
        lines.append(line)
    text = "\n".join(lines)

    return text.strip()


def sanitize_cctv_english(text: str) -> str:
    """
    Tự động dịch/thay thế các cụm từ tiếng Anh rập khuôn thường gặp của mô hình Qwen Vision
    và sửa các từ bị méo chính tả sang tiếng Việt chuẩn.
    """
    if not text:
        return text
    replacements = [
        (r'\bin in a work\s*place\b', 'trong môi trường làm việc'),
        (r'\bin a work\s*place\b', 'trong môi trường làm việc'),
        (r'\bwith one person sitting quietly doing (?:his|her|their) job', 'với một người đang ngồi làm việc bình thường'),
        (r'\bno suspicious behavior or unusual activity detected\b', 'không phát hiện hành vi khả nghi hay hoạt động bất thường nào'),
        (r'\bneither from visual nor audio channel\b', 'cả về mặt hình ảnh lẫn âm thanh'),
        (r'\bsingle person scene without interaction noise disturbance or anomaly event\b', 'khung cảnh một người, không có tiếng ồn gây rối hay sự kiện bất thường'),
        (r'\bboth vision and audio channels confirm consistent benign status\b', 'cả kênh hình ảnh và âm thanh đều xác nhận trạng thái an toàn'),
        (r'\bso no immediate action required beyond routine monitoring log record for audit purpose only\b', 'do đó không cần can thiệp, tiếp tục theo dõi định kỳ'),
        (r'\bno suspicious behavior\b', 'không có hành vi đáng ngờ'),
        (r'\bunusual activity\b', 'hoạt động bất thường'),
        (r'\bvisual nor audio channel\b', 'kênh hình ảnh lẫn âm thanh'),
        (r'\broutine monitoring\b', 'giám sát định kỳ'),
        (r'\bmú do\b', 'mức độ'),
        (r'\bmúc độ\b', 'mức độ'),
        (r'\bbooi canh giac\b', 'bối cảnh'),
        (r'\bbooi canh\b', 'bối cảnh'),
        (r'\ban nine\b', 'an ninh'),
        (r'\bchimb xếp tài computer li computer\b', 'bàn làm việc và các thiết bị máy tính'),
        (r'\bchimb xếp tài computer\b', 'bàn làm việc và máy tính'),
        (r'\btài computer\b', 'bàn máy tính'),
        (r'Kết luôn va khuyến ngh', 'Kết luận và khuyến nghị'),
        (r'\bvia âm thanh\b', 'và âm thanh'),
        (r'\band am thanh\b', 'và âm thanh'),
        (r'\bđồng thụj\b', 'đồng thời'),
        (r'\bngưong\b', 'ngưỡng'),
        (r'\bcử động\b', 'cử động'),
        (r'\btổng hợp\b', 'Tổng hợp'),
        (r'\bpha bên phải\b', 'phía bên phải'),
        (r'\bpha trái\b', 'phía trái'),
        (r'\bliên computer\b', 'liên tục'),
        (r'\bkhuy[eê]n ngh[ij]\b', 'khuyến nghị'),
        (r'\bgió\b', 'giờ'),
        (r'\bá\s+o\b', 'áo'),
        (r'\btiếp tuç\b', 'tiếp tục'),
        (r'\bro re\b', 'rõ ràng'),
        (r'\bmúc rủi ro\b', 'mức độ rủi ro'),
        (r'\btrang tr\b', 'trang trí'),
        (r'\bkhông biểu hung hang.*$', 'không có biểu hiện hung hãn hay hành vi bất thường.'),
        (r'\bhung hang\b', 'hung hãn'),
    ]
    for pattern, repl in replacements:
        text = re.sub(pattern, repl, text, flags=re.IGNORECASE)
    return text


def call_qwen_chat(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    max_tokens: int = 2048,
    temperature: float = 0.6,
    frequency_penalty: float = 0.15,
    presence_penalty: float = 0.1,
    repetition_penalty: float = 1.1,
    timeout: int = 150,
) -> Dict[str, Any]:
    """
    Call the OpenAI-compatible SGLang endpoint on Server AI.
    Returns dict with 'content', 'reasoning', and 'model'.
    Configured with frequency/presence/repetition penalties to prevent token degeneration loops.
    """
    try:
        load_dotenv(config.BASE_DIR / ".env", override=True)
    except Exception:
        pass
    active_key = os.getenv("QWEN_API_KEY", config.QWEN_API_KEY).strip()
    active_server = (os.getenv("QWEN_SERVER_URL") or config.QWEN_SERVER_URL).rstrip("/")

    url = f"{active_server}/chat/completions"
    headers = {
        "Authorization": f"Bearer {active_key}",
        "User-Agent": config.QWEN_USER_AGENT,
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or config.QWEN_MODEL_NAME,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "frequency_penalty": frequency_penalty,
        "presence_penalty": presence_penalty,
        "repetition_penalty": repetition_penalty,
        "chat_template_kwargs": {"enable_thinking": False},
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        try:
            data = resp.json()
        except Exception:
            raw_text = resp.content.decode("utf-8", errors="replace").strip()
            if "data: [DONE]" in raw_text:
                raw_text = raw_text.split("data: [DONE]")[0].strip()
            if raw_text.startswith("data:"):
                raw_text = raw_text[len("data:"):].strip()
            data = json.loads(raw_text)
        choice = data["choices"][0]
        message = choice.get("message", {})

        content = message.get("content") or ""
        reasoning = message.get("reasoning_content") or ""

        # Extract and strip <think>...</think> if present in content
        if "<think>" in content:
            think_match = re.search(r"<think>(.*?)(?:</think>|$)", content, re.DOTALL)
            if think_match:
                extracted_thinking = think_match.group(1).strip()
                if not reasoning:
                    reasoning = extracted_thinking
                else:
                    reasoning = f"{reasoning}\n\n{extracted_thinking}".strip()
            content = re.sub(r"<think>.*?(?:</think>|$)", "", content, flags=re.DOTALL).strip()

        # Clean any stray unclosed or orphan closing tags
        if "</think>" in content:
            parts = content.split("</think>")
            if not reasoning and parts[0].strip():
                reasoning = parts[0].strip()
            content = parts[-1].strip()

        if not content.strip() and reasoning.strip():
            final_match = re.search(r"(?:Potential final|Final answer|Kết luận|Trả lời|Tóm tắt|Kết quả)[^\n]*\n(.*)", reasoning, re.DOTALL | re.IGNORECASE)
            if final_match and final_match.group(1).strip():
                content = final_match.group(1).strip()
            else:
                content = reasoning.strip()

        content = clean_repetitive_text(content.strip())
        content = sanitize_cctv_english(content)
        reasoning = clean_repetitive_text(reasoning.strip())

        return {
            "content": content,
            "reasoning": reasoning,
            "model": data.get("model", config.QWEN_MODEL_NAME),
            "usage": data.get("usage", {}),
        }
    except requests.RequestException as exc:
        err_detail = ""
        if getattr(exc, "response", None) is not None:
            try:
                err_json = exc.response.json()
                msg = err_json.get("error", {}).get("message") or err_json.get("message") or str(err_json)
                err_detail = f" (Chi tiết máy chủ: {msg})"
            except Exception:
                err_detail = f" (Chi tiết máy chủ: {exc.response.text[:200]})"
        logger.error(f"[Qwen Server Error]: {exc}{err_detail}")
        raise RuntimeError(f"Lỗi kết nối Server AI ({config.QWEN_SERVER_URL}): {exc}{err_detail}")


def analyze_video_dense(
    clip_path: Path | str,
    prompt: str,
    history: Optional[List[Dict[str, str]]] = None,
    num_frames: Optional[int] = None,
    audio_analysis: Optional[Dict[str, Any]] = None,
    event: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Dense Video Multimodal Analysis kết hợp âm thanh thực tế:
    1. Trích xuất tối đa num_frames từ video.
    2. Đưa chuỗi frame, bối cảnh sự kiện và âm thanh thực tế vào prompt.
    3. Gọi Server AI để phân tích toàn diện.
    """
    max_frames = getattr(config, "MAX_VLM_FRAMES", 8)
    target_frames = num_frames or config.DENSE_FRAMES_COUNT
    effective_frames = min(target_frames, max_frames)

    frames = extract_dense_frames(clip_path, num_frames=effective_frames)
    if not frames:
        raise ValueError(f"Không trích xuất được frame nào từ video {clip_path}")

    system_prompt = (
        "Bạn là 'Vision & Audio Agent' - trợ lý AI chuyên gia phân tích an ninh giám sát đa phương thức (Thị giác video + Âm thanh thực tế) "
        "thuộc hệ thống VSS Blueprint.\n\n"
        "QUY TẮC BẮT BUỘC:\n"
        "1. 100% TIẾNG VIỆT THUẦN TÚY: Bắt buộc trả lời hoàn toàn bằng TIẾNG VIỆT chuẩn mực, tự nhiên, có dấu đầy đủ. TUYỆT ĐỐI KHÔNG CHÈN TIẾNG ANH. Dịch toàn bộ thuật ngữ sang tiếng Việt chuẩn.\n"
        "2. CHÍNH TẢ CHUẨN XÁC: Viết đúng chính tả tiếng Việt ('Mức độ an toàn', 'Bối cảnh', 'An ninh', 'Bình thường', 'Khuyến nghị'). Tuyệt đối không viết sai dấu hay từ ngữ biến dạng.\n"
        "3. PHÂN TÍCH DIỄN BIẾN THEO MỐC GIÂY: Trình bày chi tiết những gì diễn ra theo từng mốc thời gian (người, chuyển động, vị trí, hành động).\n"
        "4. TỔNG HỢP HÌNH ẢNH VÀ ÂM THANH: Kết hợp đối chiếu hình ảnh với dữ liệu âm thanh thực tế (mức dBFS, lời thoại nếu có).\n"
        "5. ĐÁNH GIÁ MỨC ĐỘ RỦI RO: Phân định rõ: Bình thường, Nghi vấn, hay Nguy hiểm/Bất thường.\n"
        "6. KẾT LUẬN: Đưa ra nhận định súc tích (1-2 câu ngắn gọn) xác nhận tình trạng an ninh và kết thúc phản hồi.\n"
        "7. ĐỊNH DẠNG: Tuyệt đối KHÔNG dùng ký tự markdown như dấu thăng (#, ##) làm tiêu đề, không dùng dấu sao (**in đậm**). Trình bày từng ý bằng gạch đầu dòng ngắn gọn."
    )

    # Build event context
    event_context_text = ""
    if event:
        ch = event.get("channel")
        cam_name = config.CAMERA_NAMES.get(str(ch)) or f"Kênh {ch}"
        code = event.get("event_code", "Giám sát")
        desc = event.get("description", "")
        ts = event.get("timestamp", "")
        event_context_text = (
            f"\n--- THÔNG TIN SỰ KIỆN CAMERA AN NINH ---\n"
            f"- Camera: {cam_name} (Kênh {ch})\n"
            f"- Cảnh báo kích hoạt: {code} ({desc})\n"
            f"- Thời điểm ghi nhận: {ts}\n"
            f"-----------------------------------------\n"
        )

    # Ghép thông tin âm thanh thực tế nếu có
    audio_context_text = ""
    if audio_analysis and audio_analysis.get("has_audio"):
        transcript = audio_analysis.get("transcript", "").strip()
        sounds = audio_analysis.get("detected_sounds", [])
        sounds_str = ", ".join(sounds) if sounds else "Không có âm thanh bất thường"
        summary = audio_analysis.get("summary", "")
        rms = audio_analysis.get("audio_rms")

        quoted_transcript = f'"{transcript}"' if transcript else '(Không có tiếng nói người rõ ràng)'
        audio_context_text = (
            f"\n--- BẰNG CHỨNG ÂM THANH THỰC TẾ TRÍCH XUẤT TỪ CLIP (ĐÃ LỌC NHIỄU DEEPFILTERNET) ---\n"
            f"- Mức âm lượng: {rms} dBFS\n"
            f"- Lời thoại bóc băng (Transcript): {quoted_transcript}\n"
            f"- Âm thanh môi trường: {sounds_str}\n"
            f"- Tóm tắt âm thanh: {summary}\n"
            f"------------------------------------------------------------------------------------\n"
        )

    timestamps_str = ", ".join([f"{ts}s" for ts, _ in frames])
    user_prompt_text = (
        f"[YÊU CẦU BẮT BUỘC: TRẢ LỜI HOÀN TOÀN BẰNG TIẾNG VIỆT CHUẨN MỰC, KHÔNG DÙNG TIẾNG ANH]\n\n"
        f"Clip camera an ninh có thời lượng thực tế với các mốc khung hình chính tại: {timestamps_str}."
        f"{event_context_text}"
        f"{audio_context_text}\n"
        f"YÊU CẦU CỦA NGƯỜI VẬN HÀNH:\n{prompt}\n\n"
        "Hãy phân tích chi tiết diễn biến, kết hợp đầy đủ bối cảnh camera, diễn biến sự kiện và âm thanh thực tế để trả lời yêu cầu trên hoàn toàn bằng tiếng Việt."
    )

    user_content: List[Dict[str, Any]] = [
        {
            "type": "text",
            "text": user_prompt_text,
        }
    ]

    # Only attach raw image_url if model is not GLM text model (which rejects base64 image_url)
    model_name = (config.QWEN_MODEL_NAME or "").lower()
    is_glm_text = "glm" in model_name
    if not is_glm_text:
        for ts_sec, data_url in frames:
            user_content.append({
                "type": "image_url",
                "image_url": {
                    "url": data_url
                }
            })

    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt}
    ]

    # Append previous chat turns if provided
    if history:
        for turn in history[-6:]:  # Keep recent history
            role = turn.get("role", "user")
            content = turn.get("content", "")
            if role in ("user", "assistant") and content:
                messages.append({"role": role, "content": content})

    messages.append({"role": "user", "content": user_content})

    res = call_qwen_chat(messages, timeout=150)

    return {
        "reply": res["content"],
        "reasoning": res["reasoning"],
        "frame_count": len(frames),
        "model": res["model"],
        "server": "Server AI (SGLang)",
        "audio_analysis": audio_analysis,
    }


def query_vision_agent_text(
    query_text: str,
    context_lines: List[str],
    channel: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Conversational Agent Query replacement for Gemini:
    Uses Qwen3.8-27B to reason about recent events, search results, and camera status.
    """
    system_prompt = (
        "Bạn là 'Vision Agent' - trợ lý AI chuyên gia phân tích an ninh giám sát video thông minh của hệ thống VSS Blueprint.\n\n"
        "QUY TẮC BẮT BUỘC:\n"
        "1. SUY NGHĨ & PHẢN HỒI: Hãy suy luận nội bộ cực kỳ ngắn gọn (chỉ 1-3 câu). Đóng ngay thẻ </think> và dành toàn bộ dung lượng trả lời 100% bằng TIẾNG VIỆT tự nhiên, trang trọng, chính xác.\n"
        "2. NGUỒN DỮ LIỆU: Phân tích dựa trên ĐÚNG các số liệu thực tế được trích xuất từ CSDL Camera bên dưới (bao gồm tổng số sự kiện, chi tiết từng loại và các bản ghi tiêu biểu). Tuyệt đối không giả định thông tin không có trong CSDL.\n"
        "3. PHÂN ĐỊNH RÕ BẤT THƯỜNG: Phân biệt rõ giữa các cảnh báo an ninh thực sự (VideoMotion - chuyển động hình ảnh, AudioMutation - đột biến âm thanh/tiếng ồn, Intrusion, Fight) với các sự kiện nhận diện người/xe định kỳ (HumanTrait, VehicleTrait).\n"
        "4. DẪN CHỨNG SỰ KIỆN: Nêu rõ mã sự kiện dạng #ID (ví dụ #23916, #24231) kèm mốc thời gian và Kênh camera (nếu có) để người vận hành bấm xem trực tiếp video clip.\n"
        "5. TRÌNH BÀY: Súc tích, mạch lạc (3-5 ý chính), kèm nhận định an ninh và khuyến nghị hành động. Tuyệt đối không sinh bảng Markdown rườm rà dài dòng làm chậm tốc độ phản hồi.\n"
        "6. ĐỊNH DẠNG VĂN BẢN: Trình bày văn bản tiếng Việt tự nhiên, sạch sẽ, súc tích. Tuyệt đối KHÔNG dùng các ký tự markdown thô như dấu thăng (#, ##, ###) làm tiêu đề, không dùng dấu sao kép (**in đậm**) hay dấu sao (*in nghiêng*). Giữ nguyên mã sự kiện camera dạng #ID (ví dụ #23916) để giao diện hiển thị nút xem clip.\n"
        "7. CHÍNH TẢ & CHỐNG LẶP TỪ: Luôn luôn trả lời bằng TIẾNG VIỆT CHUẨN CÓ DẤU ĐẦY ĐỦ ngay cả khi người dùng đặt câu hỏi không dấu. Tuyệt đối KHÔNG viết tiếng Việt không dấu. Tuyệt đối KHÔNG lặp lại một từ hoặc cụm từ nhiều lần. Nếu đã trình bày xong một ý thì chuyển sang ý tiếp theo hoặc kết thúc ngắn gọn."
    )

    cam_str = f"Kênh {channel:02d}" if channel is not None else "Đa kênh (Toàn bộ các Camera: Kênh 11, 18, 19, 20)"
    user_text = (
        f"Phạm vi camera giám sát: {cam_str}.\n"
        f"DỮ LIỆU THỰC TẾ TRUY VẤN TỪ CSDL CAMERA:\n"
        + "\n".join(context_lines)
        + f"\n\nCÂU HỎI CỦA NGƯỜI VẬN HÀNH:\n{query_text}"
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]

    res = call_qwen_chat(messages, max_tokens=4096, timeout=75)
    return {
        "reply": res["content"],
        "reasoning": res["reasoning"],
        "source": f"Vision Agent (Server AI: {res['model']})",
        "channel": channel,
    }

