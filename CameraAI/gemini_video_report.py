"""Gemini final-report layer for CameraAI evidence.

Cosmos provides per-window visual observations and PhoWhisper provides the
optional transcript.  Gemini receives only that structured text evidence, not
the original surveillance video or frames.
"""

import base64
import json
import os
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


_RISK_LEVELS = {"none", "low", "medium", "high"}
_RISK_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}
_VIETNAMESE_MARKS = set("ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ")
_VIETNAMESE_WORDS = {
    "không", "có", "người", "video", "đoạn", "hình", "ảnh", "mức", "rủi",
    "ro", "cần", "kiểm", "tra", "phát", "hiện", "khuyến", "nghị", "thời", "gian",
}
_DEFAULT_MODEL = "gemini-2.5-flash"
_LOCAL_CONFIG_FILE = Path(
    os.getenv(
        "CAMERAAI_GEMINI_CONFIG_FILE",
        str(Path(__file__).resolve().parent / "storage" / "gemini_config.json"),
    )
)


def get_gemini_settings() -> tuple[str, str, str]:
    """Return (api_key, model, source), preferring environment variables."""
    env_key = os.getenv("GEMINI_API_KEY", "").strip()
    env_model = os.getenv("CAMERAAI_GEMINI_MODEL", "").strip()
    if env_key:
        return env_key, env_model or _DEFAULT_MODEL, "environment"
    try:
        saved = json.loads(_LOCAL_CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        saved = {}
    key = str(saved.get("api_key", "")).strip() if isinstance(saved, dict) else ""
    model = str(saved.get("model", "")).strip() if isinstance(saved, dict) else ""
    return key, model or env_model or _DEFAULT_MODEL, "local" if key else "none"


def get_gemini_public_config() -> dict[str, Any]:
    key, model, source = get_gemini_settings()
    return {"configured": bool(key), "model": model, "source": source}


def save_gemini_local_config(api_key: str, model: str = _DEFAULT_MODEL) -> dict[str, Any]:
    """Persist an admin-supplied key locally; the storage directory is Git-ignored."""
    clean_key = api_key.strip()
    clean_model = model.strip() or _DEFAULT_MODEL
    if len(clean_key) < 20:
        raise ValueError("API key Gemini không hợp lệ.")
    _LOCAL_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    temporary = _LOCAL_CONFIG_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({"api_key": clean_key, "model": clean_model}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temporary.replace(_LOCAL_CONFIG_FILE)
    try:
        os.chmod(_LOCAL_CONFIG_FILE, 0o600)
    except OSError:
        pass
    return get_gemini_public_config()


def _extract_json(text: str) -> dict[str, Any] | None:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start:end + 1])
        return value if isinstance(value, dict) else None
    except json.JSONDecodeError:
        return None


def _normalize_report(value: dict[str, Any]) -> dict[str, Any] | None:
    summary = " ".join(str(value.get("summary", "")).split())
    if not summary:
        return None
    risk_level = str(value.get("risk_level", "none")).lower()
    evidence = value.get("evidence")
    if not isinstance(evidence, list):
        evidence = []
    report = {
        "summary": summary[:4000],
        "risk_level": risk_level if risk_level in _RISK_LEVELS else "none",
        "recommended_action": " ".join(str(value.get("recommended_action", "")).split())[:1000],
        "evidence": [
            {"source": str(item.get("source", "Gemini"))[:80], "detail": str(item.get("detail", ""))[:500]}
            for item in evidence if isinstance(item, dict) and item.get("detail")
        ][:12],
    }
    language_sample = report["summary"] + " " + report["recommended_action"]
    if not _looks_vietnamese(language_sample):
        return None
    return report


def _looks_vietnamese(text: str) -> bool:
    lowered = text.casefold()
    words = {word.strip(".,:;!?()[]{}\"'") for word in lowered.split()}
    return bool(_VIETNAMESE_MARKS.intersection(lowered)) and len(words.intersection(_VIETNAMESE_WORDS)) >= 2


def build_vietnamese_fallback(windows: list[dict[str, Any]]) -> dict[str, Any]:
    """Create a Vietnamese-only safe result when the final LLM is unavailable."""
    highest_risk = "none"
    ranges = []
    for window in windows:
        result = window.get("result") if isinstance(window, dict) else {}
        risk = str(result.get("risk_level", "none")).lower() if isinstance(result, dict) else "none"
        if _RISK_ORDER.get(risk, 0) > _RISK_ORDER[highest_risk]:
            highest_risk = risk
        start, end = window.get("window_start_seconds"), window.get("window_end_seconds")
        if isinstance(start, (int, float)) and isinstance(end, (int, float)):
            ranges.append(f"{start:.1f}–{end:.1f} giây")
    risk_text = {
        "none": "chưa ghi nhận dấu hiệu rủi ro rõ ràng",
        "low": "ghi nhận dấu hiệu mức thấp cần theo dõi",
        "medium": "ghi nhận dấu hiệu mức trung bình cần kiểm tra",
        "high": "ghi nhận dấu hiệu mức cao cần kiểm tra ngay",
    }[highest_risk]
    range_text = ", ".join(ranges[:6]) if ranges else "không xác định"
    return {
        "summary": (
            f"Đã phân tích {len(windows)} đoạn hình ảnh; hệ thống {risk_text}. "
            f"Các khoảng thời gian đã xử lý: {range_text}. "
            "Mô tả chi tiết từ mô hình chưa đáp ứng yêu cầu tiếng Việt, cần kiểm tra clip gốc."
        ),
        "risk_level": highest_risk,
        "recommended_action": "Đối chiếu clip gốc và chỉ xử lý cảnh báo khi bằng chứng hình ảnh hoặc âm thanh đủ rõ.",
        "evidence": [],
    }


def generate_final_video_report(event: dict[str, Any], windows: list[dict[str, Any]], audio_analysis: dict[str, Any] | None) -> tuple[dict[str, Any] | None, str | None]:
    """Return (report, model_id); return (None, None) when Gemini is disabled.

    Any Gemini failure is intentionally non-fatal: the Cosmos result remains
    available for the operator instead of turning a completed video analysis
    into a failed one.
    """
    api_key, model, _ = get_gemini_settings()
    if not api_key:
        return None, None
    if not model:
        return None, None

    visual_evidence = []
    for window in windows:
        result = window.get("result") if isinstance(window, dict) else {}
        if not isinstance(result, dict):
            continue
        visual_evidence.append({
            "time_range_seconds": [window.get("window_start_seconds"), window.get("window_end_seconds")],
            "cosmos_summary": result.get("summary", ""),
            "cosmos_risk_level": result.get("risk_level", "none"),
            "cosmos_events": result.get("events", []),
        })
    transcript = ""
    audio_rms = None
    if audio_analysis:
        transcript = str(audio_analysis.get("transcript") or "")[:6000]
        audio_rms = audio_analysis.get("audio_rms")

    evidence = {
        "event": {
            "id": event.get("id"),
            "code": event.get("event_code"),
            "channel": event.get("channel"),
            "timestamp": event.get("timestamp"),
            "description": event.get("description"),
            "severity": event.get("severity"),
        },
        "visual_windows_from_cosmos": visual_evidence,
        "audio_from_phowhisper": {
            "transcript": transcript or None,
            "audio_level_dbfs": audio_rms,
            "has_audio_track": bool(audio_analysis.get("status") != "no_audio_track") if audio_analysis else None,
        } if audio_analysis else None,
    }
    instruction = """Bạn là chuyên gia thẩm định an ninh thị giác & âm thanh đa phương thức cho hệ thống camera giám sát. Hãy viết hoàn toàn bằng tiếng Việt có dấu.

QUY TẮC ĐỐI CHIẾU MÔI TRƯỜNG & CHỐNG ẢO GIÁC BẮT BUỘC:
1. Mô hình Cosmos (thị giác) và PhoWhisper (âm thanh) là mô hình chạy cục bộ, ĐỘ TIN CẬY KHÔNG TUYỆT ĐỐI và thường xuyên hiểu sai bối cảnh (false positive):
   - Người đi lại nhanh hoặc cử chỉ tay bình thường có thể bị Cosmos phán đoán nhầm là đánh nhau/đuổi bắt.
   - Tiếng ồn nền, tiếng xe cộ hoặc quạt gió có thể bị PhoWhisper dịch nhầm thành tiếng la hét/cãi vã.
2. PHẢI ĐỐI CHIẾU CHÉO (CROSS-CHECK):
   - Nếu Cosmos nghi ngờ 'đánh nhau/xô xát' nhưng âm thanh bình thường (dBFS thấp < -40dBFS, không có tiếng thét/la) -> KHÔNG KẾT LUẬN ĐÁNH NHAU, chỉ ghi nhận là 'có chuyển động nhanh/tương tác gần, âm thanh bình thường, nghi vấn cử chỉ thông thường, cần người kiểm tra clip gốc'.
   - Nếu PhoWhisper sinh từ ngữ tiêu cực nhưng mức dBFS rất thấp hoặc không có người trong video -> coi đó là nhiễu âm thanh nền.
   - Chỉ xác nhận rủi ro 'high' hoặc 'medium' khi cả hình ảnh lẫn âm thanh đều đồng nhất bằng chứng rõ ràng.
3. Tuyệt đối không bịa đặt, không suy đoán danh tính, động cơ, thương tích không có trong dữ liệu.

Trả về đúng định dạng JSON (không dùng markdown):
{
  "summary": "Đoạn kết luận ngắn gọn, chuẩn xác, nêu rõ tình hình thực tế và mốc thời gian nếu có",
  "risk_level": "none|low|medium|high",
  "recommended_action": "Hành động thực tế cho người vận hành (ví dụ: Tiếp tục giám sát / Kiểm tra trực tiếp tại hiện trường / Xem lại clip gốc)",
  "evidence": [{"source": "Cosmos Video / PhoWhisper Audio / Metadata NVR", "detail": "Chi tiết bằng chứng thực tế"}]
}

Dữ liệu bằng chứng:
""" + json.dumps(evidence, ensure_ascii=False)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": instruction}]}],
        "generationConfig": {
            "temperature": 0.1,
            "maxOutputTokens": 4096,
            "thinkingConfig": {"thinkingBudget": 0},
            "responseMimeType": "application/json",
        },
    }
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent".format(quote(model, safe=""))
    response = None
    for attempt in range(3):
        try:
            response = requests.post(endpoint, headers={"x-goog-api-key": api_key}, json=payload, timeout=75)
            if response.status_code == 400 and "thinkingConfig" in response.text:
                payload["generationConfig"].pop("thinkingConfig", None)
                response = requests.post(endpoint, headers={"x-goog-api-key": api_key}, json=payload, timeout=75)
            if response.status_code == 429:
                time.sleep(2.0 * (attempt + 1))
                continue
            response.raise_for_status()
            break
        except requests.RequestException as exc:
            if attempt == 2:
                print(f"[GEMINI] Final video report failed: {exc}")
                return None, None
            time.sleep(1.5)

    if not response or not response.ok:
        return None, None

    try:
        payload = response.json()
        parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
        report = _normalize_report(_extract_json(text) or {})
        if not report:
            print("[GEMINI] No usable JSON report returned")
            return None, None
        return report, model
    except (ValueError, IndexError, KeyError) as exc:
        print(f"[GEMINI] Final video report parsing failed: {exc}")
        return None, None


def transcribe_and_analyze_audio_with_gemini(wav_path: str) -> dict[str, Any] | None:
    """Listen to extracted audio using Gemini multimodal to accurately transcribe and classify sounds."""
    api_key, model, _ = get_gemini_settings()
    if not api_key:
        return None

    path_obj = Path(wav_path)
    if not path_obj.is_file() or path_obj.stat().st_size == 0:
        return None

    try:
        audio_bytes = path_obj.read_bytes()
        b64_audio = base64.b64encode(audio_bytes).decode("utf-8")
        prompt = (
            "Bạn là chuyên gia an ninh thẩm định âm thanh camera giám sát. Hãy lắng nghe đoạn âm thanh trích xuất từ camera:\n"
            "1. Lắng nghe và bóc tách CHÍNH XÁC lời nói (tiếng Việt) nếu có người nói chuyện.\n"
            "2. Nhận diện các loại âm thanh môi trường xung quanh (tiếng bước chân, tiếng gõ, tiếng cười, nói chuyện, cãi vã, la hét, im lặng, tiếng quạt/xe cộ...).\n"
            "3. Đánh giá mức độ rủi ro an ninh (none/low/medium/high).\n"
            "Trả về đúng định dạng JSON (không dùng markdown):\n"
            "{\n"
            '  "transcript": "nội dung bóc băng chính xác hoặc chuỗi rỗng nếu không có ai nói",\n'
            '  "detected_sounds": ["danh sách các âm thanh nghe được"],\n'
            '  "summary": "Tóm tắt ngắn gọn và trung thực những gì nghe thấy được bằng tiếng Việt",\n'
            '  "speech_detected": true/false,\n'
            '  "risk_level": "none/low/medium/high"\n'
            "}"
        )
        payload = {
            "contents": [{
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": "audio/wav", "data": b64_audio}}
                ]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 2048,
                "thinkingConfig": {"thinkingBudget": 0},
                "responseMimeType": "application/json",
            }
        }
        endpoint = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent".format(quote(model, safe=""))
        response = None
        for attempt in range(3):
            try:
                response = requests.post(endpoint, headers={"x-goog-api-key": api_key}, json=payload, timeout=45)
                if response.status_code == 400 and "thinkingConfig" in response.text:
                    payload["generationConfig"].pop("thinkingConfig", None)
                    response = requests.post(endpoint, headers={"x-goog-api-key": api_key}, json=payload, timeout=45)
                if response.status_code == 429:
                    time.sleep(2.0 * (attempt + 1))
                    continue
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt == 2:
                    print(f"[GEMINI AUDIO] Network error: {exc}")
                    return None
                time.sleep(1.5)

        if not response or not response.ok:
            return None
        parts = response.json().get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
        extracted = _extract_json(text)
        if not extracted or not isinstance(extracted, dict):
            return None
        transcript = str(extracted.get("transcript") or "").strip()
        speech_detected = bool(extracted.get("speech_detected") or transcript)
        detected_sounds = extracted.get("detected_sounds", [])
        if not isinstance(detected_sounds, list):
            detected_sounds = []
        return {
            "transcript": transcript,
            "speech_detected": int(speech_detected),
            "detected_sounds": [str(s) for s in detected_sounds],
            "summary": str(extracted.get("summary") or "").strip(),
            "risk_level": str(extracted.get("risk_level", "none")).lower(),
            "audio_model": f"Gemini ({model})",
        }
    except Exception as exc:
        print(f"[GEMINI AUDIO] Audio transcription error: {exc}")
        return None

