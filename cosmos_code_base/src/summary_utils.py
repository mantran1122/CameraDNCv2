import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from src.result_utils import clean_text, segment_search_text


def build_video_summary(result: Dict[str, Any], max_moments: int = 8) -> Dict[str, Any]:
    segments = [segment for segment in result.get("segments", []) if isinstance(segment, dict)]
    duration = clean_text(result.get("duration", "unknown"))
    video_id = clean_text(result.get("video_id", ""))
    video_file = clean_text(result.get("video_file", ""))

    people_counts = [_coerce_people_count(segment.get("people_count")) for segment in segments]
    known_people_counts = [count for count in people_counts if count is not None]
    max_people = max(known_people_counts) if known_people_counts else None

    object_counts = Counter()
    action_counts = Counter()
    risk_counts = Counter(clean_text(segment.get("risk_level", "none")) for segment in segments)
    abnormal_counts = Counter(clean_text(segment.get("abnormal_type", "none")) for segment in segments)

    for segment in segments:
        object_counts.update(_clean_items(segment.get("objects", [])))
        action_counts.update(_clean_items(segment.get("actions", [])))

    key_moments = _select_key_moments(segments, max_moments=max_moments)
    overview = _build_overview(
        duration=duration,
        segment_count=len(segments),
        max_people=max_people,
        object_counts=object_counts,
        action_counts=action_counts,
        abnormal_counts=abnormal_counts,
    )
    meaning = _build_meaning(max_people=max_people, abnormal_counts=abnormal_counts, segments=segments)

    summary = {
        "video_id": video_id,
        "video_file": video_file,
        "duration": duration,
        "duration_seconds": result.get("duration_seconds", 0.0),
        "segment_count": len(segments),
        "overview": overview,
        "meaning": meaning,
        "main_subjects": _top_items(object_counts, fallback=["người"]),
        "main_actions": _top_items(action_counts, fallback=["tụ tập", "trao đổi", "ngồi", "đứng"]),
        "risk_summary": {
            "risk_counts": dict(risk_counts),
            "abnormal_type_counts": dict(abnormal_counts),
            "final_assessment": result.get("final_assessment", {}),
        },
        "key_moments": key_moments,
        "searchable_text": _build_searchable_text(overview, meaning, key_moments, segments),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    return summary


def save_video_summary(summary: Dict[str, Any], summaries_dir: Path) -> Path:
    summaries_dir.mkdir(parents=True, exist_ok=True)
    video_id = clean_text(summary.get("video_id", "")) or "video"
    summary_path = summaries_dir / f"{video_id}.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary_path


def _build_overview(
    duration: str,
    segment_count: int,
    max_people: int | None,
    object_counts: Counter,
    action_counts: Counter,
    abnormal_counts: Counter,
) -> str:
    subjects = ", ".join(_top_items(object_counts, fallback=["người"], limit=4))
    actions = ", ".join(_top_items(action_counts, fallback=["tụ tập", "trao đổi"], limit=4))
    crowd_text = f" Số người cao nhất được ghi nhận là khoảng {max_people} người." if max_people else ""
    abnormal_text = ""
    if abnormal_counts.get("crowding", 0) or abnormal_counts.get("phone_usage_and_crowding", 0):
        abnormal_text = " Hệ thống đánh dấu các đoạn có hơn hai người là tình huống cần chú ý."

    return clean_text(
        f"Video dài {duration}, được chia thành {segment_count} đoạn phân tích. "
        f"Nội dung chính xoay quanh {subjects}; các hành động nổi bật gồm {actions}."
        f"{crowd_text}{abnormal_text}"
    )


def _build_meaning(max_people: int | None, abnormal_counts: Counter, segments: List[Dict[str, Any]]) -> str:
    has_phone = any(segment.get("phone_detected") for segment in segments)
    has_crowd = bool(max_people and max_people > 2) or abnormal_counts.get("crowding", 0) > 0

    if has_phone and has_crowd:
        return (
            "Ý nghĩa tổng quát: video ghi lại một nhóm người xuất hiện cùng lúc trong không gian trong nhà, "
            "có dấu hiệu tụ tập và có yếu tố liên quan đến điện thoại, nên cần người vận hành xem lại các mốc được đánh dấu."
        )
    if has_crowd:
        return (
            "Ý nghĩa tổng quát: video ghi lại một nhóm khoảng ba người tụ tập, ngồi/đứng và trao đổi trong một phòng làm việc "
            "hoặc không gian kỹ thuật. Nội dung không cho thấy nguy hiểm rõ ràng, nhưng tình huống nhiều hơn hai người được đánh dấu để kiểm tra."
        )
    if has_phone:
        return (
            "Ý nghĩa tổng quát: video có xuất hiện hành vi hoặc vật thể liên quan đến điện thoại, nên các mốc tương ứng cần được kiểm tra."
        )
    return "Ý nghĩa tổng quát: video ghi lại hoạt động bình thường trong khung hình, chưa có bất thường rõ ràng theo các segment đã phân tích."


def _select_key_moments(segments: List[Dict[str, Any]], max_moments: int) -> List[Dict[str, Any]]:
    ranked = sorted(
        segments,
        key=lambda segment: (
            bool(segment.get("abnormal")),
            _risk_rank(segment.get("risk_level")),
            _coerce_float(segment.get("confidence")),
        ),
        reverse=True,
    )
    selected = ranked[:max_moments] if ranked else []
    return [
        {
            "start": clean_text(segment.get("start", "")),
            "end": clean_text(segment.get("end", "")),
            "start_seconds": _coerce_float(segment.get("start_seconds")),
            "end_seconds": _coerce_float(segment.get("end_seconds")),
            "chunk_path": clean_text(segment.get("chunk_path", "")),
            "description": clean_text(segment.get("description", "")),
            "risk_level": clean_text(segment.get("risk_level", "none")),
            "abnormal_type": clean_text(segment.get("abnormal_type", "none")),
        }
        for segment in selected
    ]


def _build_searchable_text(
    overview: str,
    meaning: str,
    key_moments: List[Dict[str, Any]],
    segments: List[Dict[str, Any]],
) -> str:
    moment_text = " ".join(
        f"{moment.get('start')} đến {moment.get('end')}: {moment.get('description')}"
        for moment in key_moments
    )
    segment_text = " ".join(segment_search_text(segment) for segment in segments)
    return clean_text(f"{overview} {meaning} Các mốc chính: {moment_text}. Toàn bộ timeline: {segment_text}")


def _top_items(counter: Counter, fallback: List[str], limit: int = 6) -> List[str]:
    items = [item for item, _ in counter.most_common(limit) if item]
    return items or fallback[:limit]


def _clean_items(value: Any) -> List[str]:
    if isinstance(value, list):
        return [clean_text(item) for item in value if clean_text(item)]
    cleaned = clean_text(value)
    return [cleaned] if cleaned else []


def _risk_rank(value: Any) -> int:
    return {"none": 0, "low": 1, "medium": 2, "high": 3}.get(clean_text(value), 0)


def _coerce_people_count(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0
