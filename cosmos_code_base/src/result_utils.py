import json
import re
from typing import Any, Dict, List, Optional


ALLOWED_ABNORMAL_TYPES = {
    "none",
    "phone_usage",
    "crowding",
    "phone_usage_and_crowding",
    "fall",
    "fight",
    "intrusion",
    "fire_smoke",
    "theft",
    "abandoned_object",
    "vandalism",
    "suspicious_behavior",
    "other",
}

ALLOWED_RISK_LEVELS = {"none", "low", "medium", "high"}
CJK_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")


def clean_text(text: Any) -> str:
    cleaned = str(text or "")
    cleaned = re.sub(r"```json|```", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(assistant|thought|user|system)[:\s]*", "", cleaned, flags=re.IGNORECASE)
    return re.sub(r"\s+", " ", cleaned).strip()


def contains_cjk(value: Any) -> bool:
    if isinstance(value, dict):
        return any(contains_cjk(item) for item in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(contains_cjk(item) for item in value)
    return bool(CJK_RE.search(str(value or "")))


def replace_cjk_content(data: Dict[str, Any], start: str, end: str) -> Dict[str, Any]:
    """Preserve structured detections but never expose Chinese prose in the UI."""
    cleaned = dict(data)
    people_count = cleaned.get("people_count", "unknown")
    phone_detected = bool(cleaned.get("phone_detected", False))
    crowd_detected = bool(cleaned.get("crowd_detected", False))
    abnormal = bool(cleaned.get("abnormal", False))

    count_text = (
        f"Phát hiện khoảng {people_count} người trong khung hình. "
        if _coerce_people_count(people_count) is not None
        else "Không xác định chắc chắn số người trong khung hình. "
    )
    observations = []
    if phone_detected:
        observations.append("Có dấu hiệu sử dụng điện thoại")
    if crowd_detected:
        observations.append("Có nhiều người xuất hiện trong khu vực")
    if abnormal and not observations:
        observations.append("Có dấu hiệu cần nhân viên giám sát kiểm tra lại")
    if not observations:
        observations.append("Không ghi nhận bất thường rõ ràng từ các khung hình mẫu")

    cleaned["start"] = start
    cleaned["end"] = end
    cleaned["description"] = count_text + ". ".join(observations) + "."
    cleaned["objects"] = [item for item in _ensure_list(cleaned.get("objects", [])) if not contains_cjk(item)]
    cleaned["actions"] = [item for item in _ensure_list(cleaned.get("actions", [])) if not contains_cjk(item)]
    cleaned["scene_changes"] = "Không xác định được thay đổi cảnh do kết quả ngôn ngữ không hợp lệ."
    important_event = cleaned.get("important_event")
    if not isinstance(important_event, dict):
        important_event = {}
    important_event = dict(important_event)
    if contains_cjk(important_event.get("event")):
        important_event["event"] = "Đoạn video cần được kiểm tra lại."
    cleaned["important_event"] = important_event
    return cleaned


def safe_json_loads(text: str) -> Optional[Dict[str, Any]]:
    cleaned = clean_text(text)
    if not cleaned:
        return None

    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else None
    except Exception:
        pass

    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if match:
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except Exception:
            return None

    return None


def salvage_segment_from_text(text: str, start: str, end: str) -> Dict[str, Any]:
    cleaned = clean_text(text)
    description = _extract_json_string_field(cleaned, "description") or cleaned
    people_count = _extract_json_number_field(cleaned, "people_count") or "unknown"
    phone_detected = _extract_json_bool_field(cleaned, "phone_detected")
    crowd_detected = _extract_json_bool_field(cleaned, "crowd_detected")

    lowered = description.lower()
    if phone_detected is None:
        phone_detected = any(term in lowered for term in ["điện thoại", "phone", "mobile"])
    if crowd_detected is None:
        count = _coerce_people_count(people_count)
        crowd_detected = bool(count and count > 2)

    return {
        "start": start,
        "end": end,
        "description": description,
        "people_count": people_count,
        "phone_detected": bool(phone_detected),
        "crowd_detected": bool(crowd_detected),
        "objects": _extract_json_string_list_field(cleaned, "objects"),
        "actions": _extract_json_string_list_field(cleaned, "actions"),
        "scene_changes": _extract_json_string_field(cleaned, "scene_changes") or "unknown",
        "abnormal": bool(phone_detected or crowd_detected),
        "abnormal_type": "phone_usage_and_crowding" if phone_detected and crowd_detected else (
            "phone_usage" if phone_detected else ("crowding" if crowd_detected else "none")
        ),
        "risk_level": "medium" if phone_detected and crowd_detected else ("low" if phone_detected or crowd_detected else "none"),
        "important_event": {
            "has_event": bool(phone_detected or crowd_detected),
            "event": _salvaged_event_text(phone_detected=bool(phone_detected), crowd_detected=bool(crowd_detected), people_count=people_count),
            "timestamp": start if phone_detected or crowd_detected else "none",
        },
        "confidence": 0.2,
        "raw_model_output": cleaned,
    }


def normalize_segment(data: Dict[str, Any], start: str, end: str) -> Dict[str, Any]:
    important_event = data.get("important_event") or {}
    if not isinstance(important_event, dict):
        important_event = {
            "has_event": False,
            "event": clean_text(important_event),
            "timestamp": "none",
        }

    segment = {
        "start": clean_text(data.get("start") or start),
        "end": clean_text(data.get("end") or end),
        "description": clean_text(data.get("description", "")),
        "people_count": data.get("people_count", "unknown"),
        "phone_detected": bool(data.get("phone_detected", False)),
        "crowd_detected": bool(data.get("crowd_detected", False)),
        "objects": _ensure_list(data.get("objects", [])),
        "actions": _ensure_list(data.get("actions", [])),
        "scene_changes": clean_text(data.get("scene_changes", "unknown")),
        "abnormal": bool(data.get("abnormal", False)),
        "abnormal_type": clean_text(data.get("abnormal_type", "none")),
        "risk_level": clean_text(data.get("risk_level", "none")),
        "important_event": {
            "has_event": bool(important_event.get("has_event", False)),
            "event": clean_text(important_event.get("event", "none")),
            "timestamp": clean_text(important_event.get("timestamp", "none")),
        },
        "confidence": _coerce_float(data.get("confidence", 0.0)),
    }

    if segment["abnormal_type"] not in ALLOWED_ABNORMAL_TYPES:
        segment["abnormal_type"] = "other" if segment["abnormal"] else "none"
    if segment["risk_level"] not in ALLOWED_RISK_LEVELS:
        segment["risk_level"] = "none"

    _apply_rule_based_flags(segment)

    segment["confidence"] = max(0.0, min(1.0, segment["confidence"]))
    return segment


def segment_search_text(segment: Dict[str, Any]) -> str:
    important_event = segment.get("important_event") or {}
    parts: List[str] = [
        f"Thời gian: {segment.get('start', '')} đến {segment.get('end', '')}",
        f"Mô tả: {segment.get('description', '')}",
        f"Số người: {segment.get('people_count', 'unknown')}",
        f"Đối tượng: {_join_values(segment.get('objects', []))}",
        f"Hành động: {_join_values(segment.get('actions', []))}",
        f"Thay đổi cảnh: {segment.get('scene_changes', '')}",
        f"Sự kiện quan trọng: {important_event.get('event', '')}",
        f"Loại bất thường: {segment.get('abnormal_type', 'none')}",
        f"Mức rủi ro: {segment.get('risk_level', 'none')}",
    ]
    if segment.get("phone_detected"):
        parts.append("Có phát hiện điện thoại hoặc hành vi dùng điện thoại.")
    if segment.get("crowd_detected"):
        parts.append("Có phát hiện tụ tập trên hai người.")
    if segment.get("abnormal"):
        parts.append("Đây là đoạn được đánh dấu bất thường.")
    return clean_text(" ".join(part for part in parts if part))


def _ensure_list(value: Any) -> List[str]:
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    if value in (None, ""):
        return []
    return [clean_text(value)]


def _join_values(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(clean_text(item) for item in value if clean_text(item))
    return clean_text(value)


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _apply_rule_based_flags(segment: Dict[str, Any]) -> None:
    people_count = _coerce_people_count(segment.get("people_count"))
    if people_count is not None and people_count > 2:
        segment["crowd_detected"] = True
        segment["abnormal"] = True
        if segment["phone_detected"]:
            segment["abnormal_type"] = "phone_usage_and_crowding"
        elif segment["abnormal_type"] in ("none", ""):
            segment["abnormal_type"] = "crowding"
        if segment["risk_level"] == "none":
            segment["risk_level"] = "low"

        important_event = segment.get("important_event") or {}
        if not important_event.get("has_event"):
            segment["important_event"] = {
                "has_event": True,
                "event": f"Phát hiện {people_count} người trong khung hình.",
                "timestamp": segment.get("start", "none"),
            }


def _coerce_people_count(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _extract_json_string_field(text: str, field: str) -> Optional[str]:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*"((?:\\.|[^"\\])*)"', text, flags=re.DOTALL)
    if not match:
        return None
    try:
        return clean_text(json.loads(f'"{match.group(1)}"'))
    except Exception:
        return clean_text(match.group(1))


def _extract_json_number_field(text: str, field: str) -> Optional[int]:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*(\d+)', text)
    if not match:
        return None
    try:
        return int(match.group(1))
    except Exception:
        return None


def _extract_json_bool_field(text: str, field: str) -> Optional[bool]:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*(true|false)', text, flags=re.IGNORECASE)
    if not match:
        return None
    return match.group(1).lower() == "true"


def _extract_json_string_list_field(text: str, field: str, limit: int = 12) -> List[str]:
    match = re.search(rf'"{re.escape(field)}"\s*:\s*\[(.*?)\]', text, flags=re.DOTALL)
    if not match:
        return []
    values = re.findall(r'"((?:\\.|[^"\\])*)"', match.group(1))
    cleaned_values = []
    for value in values[:limit]:
        try:
            cleaned_values.append(clean_text(json.loads(f'"{value}"')))
        except Exception:
            cleaned_values.append(clean_text(value))
    return [value for value in cleaned_values if value]


def _salvaged_event_text(phone_detected: bool, crowd_detected: bool, people_count: Any) -> str:
    if phone_detected and crowd_detected:
        return f"Phát hiện dùng điện thoại và {people_count} người trong khung hình."
    if phone_detected:
        return "Phát hiện dấu hiệu liên quan đến điện thoại."
    if crowd_detected:
        return f"Phát hiện {people_count} người trong khung hình."
    return "none"
