"""
AI Search Planner for VSS Blueprint.
Intelligently analyzes user query intent, resolves camera scope (single camera vs all cameras),
determines temporal filters, event codes, and search criteria.
"""

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from temporal_parser import parse_query_temporal

ANOMALY_CODES = [
    "VideoMotion",
    "AudioMutation",
    "SoundDetection",
    "Intrusion",
    "CrossLine",
    "Fight",
    "RtspSessionDisconnect"
]

HUMAN_CODES = ["HumanTrait", "Intrusion", "CrossLine"]
VEHICLE_CODES = ["Vehicle", "Intrusion"]


def plan_search_intent(
    query_text: str,
    selected_channel: Optional[int] = None
) -> Dict[str, Any]:
    """
    Decomposes and plans the search intent:
    - Resolves whether user is querying ALL cameras or a specific channel.
    - Resolves temporal window (date, start_time, end_time).
    - Resolves target event codes (anomalies vs routine vs specific).
    - Detects if video clips are specifically demanded.
    """
    query_text = (query_text or "").strip()
    lowered = query_text.lower()

    # 1. Base temporal & entity parsing
    temporal = parse_query_temporal(query_text)

    # 2. Camera Scope Resolution
    explicit_channel = temporal.get("channel")

    # Check if query asks for ALL cameras / global scope:
    is_all_phrase = any(
        k in lowered for k in [
            "tất cả", "tat ca", "toàn bộ", "toan bo", "mọi camera", "moi camera",
            "các camera", "cac camera", "các cam", "cac cam", "toàn hệ thống", "hệ thống", "all"
        ]
    )

    this_cam_phrase = any(
        k in lowered for k in [
            "cam này", "kênh này", "kenh nay", "camera này", "ở đây", "o day", "chỗ này", "cho nay"
        ]
    )

    if is_all_phrase:
        # User explicitly requested all cameras / global scope
        resolved_channel = None
        is_all_channels = True
    elif explicit_channel is not None:
        # Query specifies a concrete camera channel (e.g. "kênh 18", "cam 11")
        resolved_channel = explicit_channel
        is_all_channels = False
    elif this_cam_phrase:
        # User asks about current camera ("cam này", "kênh này")
        resolved_channel = selected_channel or 11
        is_all_channels = False
    else:
        # Fall back to selected_channel (if caller specified a channel, use it; otherwise all cameras)
        resolved_channel = selected_channel
        is_all_channels = bool(selected_channel is None)

    # 3. Anomaly & Event Code Resolution
    only_anomalies = temporal.get("only_anomalies", False)
    if not only_anomalies:
        only_anomalies = any(
            k in lowered for k in [
                "bất thường", "bat thuong", "nguy hiểm", "nguy hiem",
                "cảnh báo", "canh bao", "alarm", "anomaly", "sự cố", "su co",
                "đột nhập", "dot nhap", "vượt rào", "vuot rao", "đánh nhau", "danh nhau"
            ]
        )

    event_codes: List[str] = []
    if only_anomalies:
        event_codes = list(ANOMALY_CODES)
    elif any(k in lowered for k in ["người", "nhân viên", "khách", "human", "person"]):
        event_codes = list(HUMAN_CODES)
    elif any(k in lowered for k in ["xe", "phương tiện", "ô tô", "xe máy", "vehicle"]):
        event_codes = list(VEHICLE_CODES)
    elif any(k in lowered for k in ["âm thanh", "tiếng ồn", "la hét", "audio", "sound"]):
        event_codes = ["AudioMutation", "SoundDetection"]

    # 4. Require Clips Resolution
    require_clips = any(
        k in lowered for k in [
            "video", "clip", "mp4", "xem", "phát", "phat", "hiển thị", "hien thi",
            "mở", "mo", "băng ghi hình", "footage"
        ]
    )

    return {
        "channel": resolved_channel,
        "is_all_channels": is_all_channels,
        "target_date": temporal.get("date"),
        "is_date_filtered": temporal.get("is_date_filtered", False),
        "start_time": temporal.get("start_time"),
        "end_time": temporal.get("end_time"),
        "is_time_filtered": temporal.get("is_time_filtered", False),
        "only_anomalies": only_anomalies,
        "event_codes": event_codes,
        "search_kw": temporal.get("search_kw"),
        "target_event_id": temporal.get("target_event_id"),
        "require_clips": require_clips,
    }
