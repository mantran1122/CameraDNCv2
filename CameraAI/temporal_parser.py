"""
Temporal and Semantic Query Parser for VSS Blueprint.
Extracts dates, explicit time ranges (e.g. 'từ 7h đến 8h', '07:00 - 08:00'),
channel numbers, and intent filters from natural Vietnamese queries.
"""

import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional


def parse_query_temporal(text: str, default_date: Optional[str] = None) -> Dict[str, Any]:
    """
    Parses a natural language query for:
    - target_date: YYYY-MM-DD
    - start_time: YYYY-MM-DD HH:MM:SS
    - end_time: YYYY-MM-DD HH:MM:SS
    - is_time_filtered: bool
    - is_date_filtered: bool
    - channel: int | None
    - only_anomalies: bool
    - search_kw: str | None
    - target_event_id: int | None
    """
    lowered = (text or "").lower()
    now = datetime.now()
    today_str = default_date or now.strftime("%Y-%m-%d")

    # 1. Date Detection
    target_date = today_str
    is_date_filtered = False

    if any(k in lowered for k in ["hôm qua", "hom qua", "yesterday"]):
        target_date = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        is_date_filtered = True
    elif any(k in lowered for k in ["hôm nay", "hom nay", "today", "ngày nay"]):
        target_date = today_str
        is_date_filtered = True
    else:
        date_iso_m = re.search(r'\b(202\d-\d{2}-\d{2})\b', text)
        if date_iso_m:
            target_date = date_iso_m.group(1)
            is_date_filtered = True
        else:
            date_vn_m = re.search(r'\b(\d{1,2})[/.-](\d{1,2})[/.-](202\d)\b', text)
            if date_vn_m:
                d, m, y = date_vn_m.groups()
                target_date = f"{y}-{int(m):02d}-{int(d):02d}"
                is_date_filtered = True

    # 2. Time Range Detection
    start_time = None
    end_time = None
    is_time_filtered = False

    # Patterns like: "từ 7h đến 8h", "từ 7h30 đến 8h45", "7h - 8h", "07:00 đến 08:00", "7:00 - 8:00", "từ 7 giờ đến 8 giờ"
    range_regex = (
        r'(?:từ|tu|khoảng|khoang|khung|tầm|tam)?\s*'
        r'(\d{1,2})(?:h|:| giờ|h00)?\s*(\d{2})?\s*'
        r'(?:đến|den|tới|toi|-|->)\s*'
        r'(\d{1,2})(?:h|:| giờ|h00)?\s*(\d{2})?'
    )
    range_m = re.search(range_regex, lowered)
    if range_m:
        h1_s, m1_s, h2_s, m2_s = range_m.groups()
        try:
            h1 = int(h1_s)
            m1 = int(m1_s) if m1_s else 0
            h2 = int(h2_s)
            m2 = int(m2_s) if m2_s else 0
            if 0 <= h1 <= 24 and 0 <= h2 <= 24:
                start_time = f"{target_date} {h1:02d}:{m1:02d}:00"
                end_time = f"{target_date} {h2:02d}:{m2:02d}:59" if m2_s else f"{target_date} {h2:02d}:00:59"
                is_time_filtered = True
        except Exception:
            pass

    # Single hour like "lúc 10h", "vào 10h45", "lúc 10:45"
    if not is_time_filtered:
        single_m = re.search(r'(?:lúc|luc|vào|vao|khoảng|khoang)\s*(\d{1,2})(?:h|:)(\d{2})?', lowered)
        if single_m:
            try:
                sh = int(single_m.group(1))
                sm = int(single_m.group(2)) if single_m.group(2) else None
                if 0 <= sh <= 24:
                    if sm is not None and 0 <= sm <= 59:
                        dt_start = datetime.strptime(f"{target_date} {sh:02d}:{sm:02d}:00", "%Y-%m-%d %H:%M:%S") - timedelta(minutes=2)
                        dt_end = datetime.strptime(f"{target_date} {sh:02d}:{sm:02d}:00", "%Y-%m-%d %H:%M:%S") + timedelta(minutes=2)
                        start_time = dt_start.strftime("%Y-%m-%d %H:%M:%S")
                        end_time = dt_end.strftime("%Y-%m-%d %H:%M:%S")
                    else:
                        start_time = f"{target_date} {sh:02d}:00:00"
                        end_time = f"{target_date} {sh:02d}:59:59"
                    is_time_filtered = True
            except Exception:
                pass

    # Broad daylight periods
    if not is_time_filtered:
        if any(k in lowered for k in ["sáng nay", "sang nay", "buổi sáng", "buoi sang"]):
            start_time = f"{target_date} 06:00:00"
            end_time = f"{target_date} 11:59:59"
            is_time_filtered = True
        elif any(k in lowered for k in ["chiều nay", "chieu nay", "buổi chiều", "buoi chieu"]):
            start_time = f"{target_date} 12:00:00"
            end_time = f"{target_date} 17:59:59"
            is_time_filtered = True
        elif any(k in lowered for k in ["tối nay", "toi nay", "buổi tối", "buoi toi"]):
            start_time = f"{target_date} 18:00:00"
            end_time = f"{target_date} 23:59:59"
            is_time_filtered = True
        elif any(k in lowered for k in ["đêm qua", "dem qua"]):
            yesterday_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
            start_time = f"{yesterday_str} 22:00:00"
            end_time = f"{target_date} 05:59:59"
            is_time_filtered = True

    # 3. Channel Detection
    channel = None
    ch_m = re.search(r'(?:kênh|kenh|cam|channel)\s*(\d+)', lowered)
    if ch_m:
        try:
            detected_ch = int(ch_m.group(1))
            if 1 <= detected_ch <= 32:
                channel = detected_ch
        except Exception:
            pass

    # 4. Target Event ID detection
    target_event_id = None
    ev_m = re.search(r'(?:sự kiện|event|id)\s*#?\s*(\d+)', lowered)
    if not ev_m:
        ev_m = re.search(r'#(\d{4,6})', text)
    if ev_m:
        try:
            target_event_id = int(ev_m.group(1))
        except Exception:
            pass

    # 5. Anomaly Intent Detection (including common typos like 'trúc thường' for 'bất thường')
    anomaly_keywords = [
        "bất thường", "bat thuong", "nguy hiểm", "nguy hiem",
        "cảnh báo", "canh bao", "alarm", "anomaly", "sự cố", "su co",
        "trúc thường", "truc thuong", "thường xuyên"
    ]
    only_anomalies = any(k in lowered for k in anomaly_keywords)

    # 6. Specific Object/Action Keyword Detection
    search_kw = None
    keyword_map = [
        (["đánh nhau", "xô xát", "ẩu đả", "fight"], "Fight"),
        (["vượt rào", "rào", "crossline", "tripwire"], "CrossLine"),
        (["đột nhập", "xâm nhập", "intrusion"], "Intrusion"),
        (["xe nâng", "xe", "phương tiện", "ô tô", "xe máy", "vehicle"], "Vehicle"),
        (["la hét", "tiếng ồn", "âm thanh", "sound", "audio"], "Audio"),
        (["chuyển động", "motion"], "Motion"),
        (["người", "nhân viên", "khách", "human"], "Human"),
    ]
    for terms, kw in keyword_map:
        if any(term in lowered for term in terms):
            search_kw = kw
            break

    return {
        "date": target_date,
        "start_time": start_time,
        "end_time": end_time,
        "is_time_filtered": is_time_filtered,
        "is_date_filtered": is_date_filtered,
        "channel": channel,
        "only_anomalies": only_anomalies,
        "search_kw": search_kw,
        "target_event_id": target_event_id
    }

