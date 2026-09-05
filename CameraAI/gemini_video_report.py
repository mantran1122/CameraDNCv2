"""Gemini final-report layer for CameraAI evidence.

Cosmos provides per-window visual observations and PhoWhisper provides the
optional transcript.  Gemini receives only that structured text evidence, not
the original surveillance video or frames.
"""

import json
import os
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
_DEFAULT_MODEL = "gemini-2.0-flash"
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
    # A valid transcript remains usable when a previous LLM attempt left the
    # audio row in ``transcribed`` instead of ``completed``.
    if audio_analysis:
        transcript = str(audio_analysis.get("transcript") or "")[:6000]

    evidence = {
        "event": {"code": event.get("event_code"), "channel": event.get("channel"), "timestamp": event.get("timestamp")},
        "visual_windows_from_cosmos": visual_evidence,
        "audio_transcript_from_phowhisper": transcript or None,
    }
    instruction = """Bạn là lớp tổng hợp cuối cho hệ thống camera an ninh. Hãy viết hoàn toàn bằng tiếng Việt có dấu.
Cosmos và PhoWhisper chỉ là bằng chứng không hoàn hảo, có thể sai. Không được bịa, không suy luận danh tính, ý định, nguyên nhân, thương tích hay hành vi không có trong bằng chứng. Chỉ tăng mức rủi ro khi nhiều bằng chứng hỗ trợ rõ ràng. Nếu video không đủ rõ để kết luận đánh nhau/ngã/xâm nhập, ghi rõ 'cần kiểm tra clip gốc'.
Trả về đúng JSON, không markdown:
{
  "summary": "kết luận nghiệp vụ ngắn có mốc thời gian nếu có",
  "risk_level": "none|low|medium|high",
  "recommended_action": "hành động thực tế",
  "evidence": [{"source":"Cosmos hoặc PhoWhisper","detail":"bằng chứng có mốc thời gian"}]
}

Dữ liệu bằng chứng:
""" + json.dumps(evidence, ensure_ascii=False)
    payload = {
        "contents": [{"role": "user", "parts": [{"text": instruction}]}],
        "generationConfig": {"temperature": 0.1, "maxOutputTokens": 900, "responseMimeType": "application/json"},
    }
    endpoint = "https://generativelanguage.googleapis.com/v1beta/models/{}:generateContent".format(quote(model, safe=""))
    try:
        response = requests.post(endpoint, headers={"x-goog-api-key": api_key}, json=payload, timeout=75)
        response.raise_for_status()
        payload = response.json()
        parts = payload.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
        report = _normalize_report(_extract_json(text) or {})
        if not report:
            print("[GEMINI] No usable JSON report returned")
            return None, None
        return report, model
    except (requests.RequestException, ValueError, IndexError, KeyError) as exc:
        print(f"[GEMINI] Final video report failed: {exc}")
        return None, None
