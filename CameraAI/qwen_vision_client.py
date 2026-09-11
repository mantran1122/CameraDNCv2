"""
Qwen Vision & LLM Client for Internal Server (4x NVIDIA H200)
Replaces both Cosmos local video model and Gemini 2.5 cloud model.
Provides dense frame extraction, multimodal vision reasoning, and agent conversations.
"""

import base64
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import requests

import config

logger = logging.getLogger(__name__)


def extract_dense_frames(
    clip_path: Path | str,
    num_frames: int = 32,
    max_dim: int = 768,
    jpeg_quality: int = 80,
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


def call_qwen_chat(
    messages: List[Dict[str, Any]],
    model: Optional[str] = None,
    max_tokens: int = 4096,
    temperature: float = 0.2,
    timeout: int = 90,
) -> Dict[str, Any]:
    """
    Call the OpenAI-compatible SGLang endpoint on Server 4x H200.
    Returns dict with 'content', 'reasoning', and 'model'.
    """
    url = f"{config.QWEN_SERVER_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.QWEN_API_KEY}",
        "User-Agent": config.QWEN_USER_AGENT,
        "Content-Type": "application/json",
    }
    payload = {
        "model": model or config.QWEN_MODEL_NAME,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }

    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        data = resp.json()
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

        return {
            "content": content.strip(),
            "reasoning": reasoning.strip(),
            "model": data.get("model", config.QWEN_MODEL_NAME),
            "usage": data.get("usage", {}),
        }
    except requests.RequestException as exc:
        logger.error(f"[Qwen Server Error]: {exc}")
        raise RuntimeError(f"Lỗi kết nối Server AI 4x H200 ({config.QWEN_SERVER_URL}): {exc}")


def analyze_video_dense(
    clip_path: Path | str,
    prompt: str,
    history: Optional[List[Dict[str, str]]] = None,
    num_frames: Optional[int] = None,
    audio_analysis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Dense Video Multimodal Analysis:
    1. Extracts 32 (or num_frames) dense frames from the video.
    2. Builds an OpenAI multimodal payload with frame sequence and timestamps.
    3. Calls Qwen3.8-27B on 4x H200 to generate detailed action analysis and reasoning.
    Dense Video Multimodal Analysis kết hợp âm thanh thực tế:
    1. Trích xuất 32 (hoặc num_frames) dense frames từ video.
    2. Đưa chuỗi frame và dữ liệu âm thanh thực tế (đã qua lọc DeepFilterNet) vào prompt.
    3. Gọi Qwen3.8-27B trên Server 4x H200 để phân tích toàn diện đa phương thức.
    """
    num_frames = num_frames or config.DENSE_FRAMES_COUNT
    frames = extract_dense_frames(clip_path, num_frames=num_frames)
    if not frames:
        raise ValueError(f"Không trích xuất được frame nào từ video {clip_path}")

    system_prompt = (
        "Bạn là 'Vision Agent' - trợ lý AI chuyên gia thị giác máy tính và phân tích an ninh giám sát video thông minh "
        "thuộc hệ thống VSS Blueprint (chạy trên Server 4x NVIDIA H200 siêu tốc).\n\n"
        "Bạn là 'Vision & Audio Agent' - trợ lý AI chuyên gia phân tích đa phương thức (Thị giác 32 frames + Âm thanh thực tế) "
        "thuộc hệ thống VSS Blueprint (Server 4x NVIDIA H200 siêu tốc).\n\n"
        "NHIỆM VỤ:\n"
        "1. Phân tích chuỗi các frame liên tiếp được trích xuất từ clip video camera giám sát theo trình tự thời gian.\n"
        "1. Phân tích chuỗi 32 frame liên tiếp theo trình tự thời gian kết hợp ĐỐI CHIẾU CHÉO với âm thanh thực tế được cung cấp.\n"
        "2. Xác định chi tiết: Các đối tượng (người, phương tiện, vật thể), đặc điểm trang phục/bảo hộ, hành động cụ thể.\n"
        "3. Nêu rõ diễn biến theo từng mốc thời gian (giây) nếu có hành vi đáng chú ý.\n"
        "4. Đánh giá mức độ an toàn/rủi ro: Bình thường, Nghi vấn, hay Nguy hiểm/Bất thường.\n"
        "5. Đưa ra kết luận và khuyến nghị rõ ràng, trực diện bằng tiếng Việt chuyên nghiệp."
        "4. TỔNG HỢP CẢ HÌNH ẢNH VÀ ÂM THANH THỰC TẾ: Trình bày rõ ràng những gì quan sát được từ hình ảnh và những gì nghe thấy từ âm thanh (lời thoại, tiếng động).\n"
        "5. Đánh giá mức độ an toàn/rủi ro: Bình thường, Nghi vấn, hay Nguy hiểm/Bất thường.\n"
        "6. Đưa ra kết luận và khuyến nghị rõ ràng, trực diện bằng tiếng Việt chuyên nghiệp."
    )

    # Build user content array containing text prompt and all extracted image frames
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

    # Build user content array containing text prompt, audio context and all extracted image frames
    user_prompt_text = (
        f"Dưới đây là chuỗi {len(frames)} frame hình ảnh liên tiếp được cắt đều từ clip camera an ninh từ giây 0 đến kết thúc."
        f"{audio_context_text}\n"
        f"YÊU CẦU CỦA NGƯỜI VẬN HÀNH:\n{prompt}\n\n"
        "Hãy phân tích chi tiết diễn biến, kết hợp đầy đủ cả hình ảnh lẫn âm thanh thực tế và trả lời yêu cầu trên."
    )

    user_content: List[Dict[str, Any]] = [
        {
            "type": "text",
            "text": (
                f"Dưới đây là chuỗi {len(frames)} frame hình ảnh liên tiếp được cắt đều từ clip camera an ninh "
                f"từ giây 0 đến kết thúc.\n\n"
                f"YÊU CẦU CỦA NGƯỜI VẬN HÀNH:\n{prompt}\n\n"
                "Hãy phân tích chi tiết diễn biến và trả lời đầy đủ yêu cầu trên."
            ),
            "text": user_prompt_text,
        }
    ]

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

    res = call_qwen_chat(messages, timeout=90)

    return {
        "reply": res["content"],
        "reasoning": res["reasoning"],
        "frame_count": len(frames),
        "model": res["model"],
        "server": "4x NVIDIA H200 (SGLang)",
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
        "5. TRÌNH BÀY: Súc tích, mạch lạc (3-5 ý chính), kèm nhận định an ninh và khuyến nghị hành động. Tuyệt đối không sinh bảng Markdown rườm rà dài dòng làm chậm tốc độ phản hồi."
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
        "source": f"Vision Agent (Server H200: {res['model']})",
        "channel": channel,
    }

