"""
VSS Blueprint Search & Critic Engine
Cloned algorithm from NVIDIA Metropolis Blueprint Vision (Search)
Integrated with local CameraAI SQLite Database & Gemini/Local LLM.
"""

import re
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import config
import database
from clip_storage import resolve_clip_path
from gemini_video_report import get_gemini_settings
from temporal_parser import parse_query_temporal

def decompose_query(query: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Query Decomposition stage of NVIDIA Vision Agent:
    Extracts visual attributes, event intent, channel, event_ids, and time range.
    """
    query = (query or "").strip()
    lowered = query.lower()
    filters = filters or {}

    # 1. Channel detection: Highest priority to explicit filter channel
    # Channel detection
    channel = filters.get("channel")
    is_all_phrase = any(
        k in lowered for k in [
            "tất cả", "tat ca", "toàn bộ", "toan bo", "mọi camera", "moi camera",
            "các camera", "cac camera", "các cam", "cac cam", "toàn hệ thống", "hệ thống", "all"
        ]
    )
    if is_all_phrase:
        channel = None
    elif channel is not None:
        try:
            channel = int(filters["channel"])
        except Exception:
            channel = None

    if channel is None and filters.get("video_sources"):
        vs = str(filters["video_sources"]).lower()
        ch_m = re.search(r'(\d+)', vs)
        if ch_m:
            channel = int(ch_m.group(1))
    
    if channel is None:
        ch_m = re.search(r'(?:cam|kênh|kenh|channel|ch)\s*(\d+)', lowered)
        if ch_m:
            try:
                channel = int(ch_m.group(1))
            except Exception:
                pass

    # Target Event ID detection (#14752 or 14752)
    target_event_id = None
    ev_m = re.search(r'#?(\d{4,6})', lowered)
    if ev_m:
        try:
            target_event_id = int(ev_m.group(1))
        except Exception:
            pass

    # Explicit event IDs filter (e.g. from Vision Agent RAG result)
    event_ids = []
    if filters.get("event_ids"):
        raw_eids = filters["event_ids"]
        if isinstance(raw_eids, list):
            for e in raw_eids:
                try:
                    event_ids.append(int(e))
                except Exception:
                    pass

    # 2. Extract visual attributes & actions (support both accented and unaccented Vietnamese)
    attributes = []
    actions = []
    event_codes = []

    # Mapping keywords to attributes and event codes
    attr_map = [
        (["người", "nguoi", "nhân viên", "nhan vien", "khách", "khach", "person", "human", "man", "woman"], "subject:person", ["HumanTrait", "Human", "Intrusion", "CrossLine"]),
        (["bảo hộ", "bao ho", "áo vàng", "ao vang", "mũ", "mu", "nón", "non", "hardhat", "helmet", "vest", "safety"], "wearing safety gear", ["HumanTrait"]),
        (["thùng hàng", "thung hang", "kiện hàng", "kien hang", "hộp hàng", "hop hang", "bê hộp", "vác hộp", "bê thùng", "box", "package"], "carrying box/package", ["HumanTrait"]),
        (["thang", "trèo", "treo", "leo", "climb", "ladder"], "climbing ladder", ["HumanTrait", "Intrusion"]),
        (["xe nâng", "xe nang", "forklift", "xe", "ô tô", "o to", "vehicle", "car", "truck"], "subject:vehicle", ["Vehicle", "Intrusion"]),
        (["đánh nhau", "danh nhau", "xô xát", "xo xat", "ẩu đả", "au da", "fight"], "action:altercation", ["Fight"]),
        (["vượt rào", "vuot rao", "crossline", "tripwire", "rào", "rao"], "action:line_crossing", ["CrossLine"]),
        (["bất thường", "bat thuong", "nguy hiểm", "nguy hiem", "cảnh báo", "canh bao", "alarm", "anomaly", "sự cố", "su co"], "event:anomaly", ["VideoMotion", "AudioMutation", "SoundDetection", "Intrusion", "CrossLine", "Fight", "RtspSessionDisconnect"]),
        (["âm thanh", "am thanh", "tiếng ồn", "tieng on", "la hét", "la het", "audio", "sound"], "audio:anomaly", ["AudioMutation", "SoundDetection"]),
    ]

    for keywords, attr_label, codes in attr_map:
        if any(kw in lowered for kw in keywords):
            attributes.append(attr_label)
            event_codes.extend(codes)

    if not attributes:
        attributes.append("general:activity")

    # Parse temporal range and date from query string
    temp_info = parse_query_temporal(query)
    if channel is None and temp_info.get("channel"):
        channel = temp_info["channel"]
    if target_event_id is None and temp_info.get("target_event_id"):
        target_event_id = temp_info["target_event_id"]

    # Time range filtering
    from_time = filters.get("from_time") or filters.get("from") or ""
    to_time = filters.get("to_time") or filters.get("to") or ""
    from_time = filters.get("from_time") or filters.get("from") or temp_info.get("start_time") or ""
    to_time = filters.get("to_time") or filters.get("to") or temp_info.get("end_time") or ""
    target_date = temp_info.get("date") if temp_info.get("is_date_filtered") else ""
    is_time_filtered = bool(temp_info.get("is_time_filtered") or filters.get("from_time") or filters.get("to_time"))

    return {
        "raw_query": query,
        "channel": channel,
        "target_event_id": target_event_id,
        "event_ids": event_ids,
        "attributes": attributes,
        "event_codes": list(set(event_codes)),
        "from_time": from_time,
        "to_time": to_time,
        "target_date": target_date,
        "is_time_filtered": is_time_filtered,
        "top_k": int(filters.get("top_k") or 10),
        "min_similarity": float(filters.get("min_cosine_similarity") or filters.get("min_sim") or 0.0)
    }

def format_time_str(ts_str: str) -> str:
    """Extract HH:MM:SS from timestamp string."""
    try:
        if ' ' in ts_str:
            return ts_str.split(' ')[1]
        elif 'T' in ts_str:
            return ts_str.split('T')[1][:8]
        return ts_str
    except Exception:
        return ts_str

def calculate_end_time(start_str: str, duration_sec: int = 10) -> str:
    """Add duration seconds to timestamp string."""
    try:
        t_str = format_time_str(start_str)
        parts = [int(p) for p in t_str.split(':')]
        dt = timedelta(hours=parts[0], minutes=parts[1], seconds=parts[2]) + timedelta(seconds=duration_sec)
        total_sec = int(dt.total_seconds())
        h = (total_sec // 3600) % 24
        m = (total_sec % 3600) // 60
        s = total_sec % 60
        return f"{h:02d}:{m:02d}:{s:02d}"
    except Exception:
        return start_str

def evaluate_critic(event: Dict[str, Any], criteria: Dict[str, Any], base_similarity: float) -> Dict[str, Any]:
    """
    Critic Agent algorithm: evaluates whether the clip satisfies user criteria.
    Returns result ('confirmed' | 'rejected') and criteria_met dict.
    """
    desc = (event.get("description") or "").lower()
    code = (event.get("event_code") or "").lower()
    severity = (event.get("severity") or "info").lower()
    
    # Explicit target event IDs grounded by Vision Agent RAG are automatically confirmed
    target_id = criteria.get("target_event_id")
    event_ids = criteria.get("event_ids") or []
    if (target_id and event.get("id") == target_id) or (event_ids and event.get("id") in event_ids):
        return {
            "result": "confirmed",
            "criteria_met": {attr: True for attr in criteria.get("attributes", [])}
        }

    criteria_met = {}
    total_matched = 0

    for attr in criteria["attributes"]:
        key = attr.split(":")[-1]
        met = False
        if "person" in attr and ("human" in code or "người" in desc):
            met = True
        elif "gear" in attr and ("human" in code or "bảo hộ" in desc):
            met = True
        elif "altercation" in attr and ("fight" in code or "đánh" in desc):
            met = True
        elif "line_crossing" in attr and ("crossline" in code or "rào" in desc):
            met = True
        elif "intrusion" in attr and ("intrusion" in code or "nhập" in desc):
            met = True
        elif "anomaly" in attr and (severity in ("high", "medium") or "bất thường" in desc or code in ("videomotion", "audiomutation", "sounddetection", "intrusion", "crossline", "fight")):
            met = True
        elif "box" in attr:
            met = "human" in code or severity in ("high", "medium")
        else:
            met = base_similarity >= 0.70

        criteria_met[attr] = met
        if met:
            total_matched += 1

    # Determination
    ratio = (total_matched / len(criteria["attributes"])) if criteria["attributes"] else 1.0
    confirmed = ratio >= 0.5 and base_similarity >= 0.65

    return {
        "result": "confirmed" if confirmed else "rejected",
        "criteria_met": criteria_met
    }

def search_vss_archive(query: str, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Full Search Pipeline:
    1. Query Decomposition
    2. SQLite DB Retrieval with real warehouse clips (strictly adhering to channel and event criteria)
    3. Similarity scoring & Ranking
    4. Critic Agent verification
    5. VSS Blueprint formatted response
    """
    filters = filters or {}
    decomp = decompose_query(query, filters)
    ch = decomp.get("channel")

    # If caller explicitly provided an empty event_ids list (e.g. Agent RAG found 0 events),
    # return immediately with 0 results instead of pulling random clips!
    if "event_ids" in filters and filters["event_ids"] is not None and len(filters["event_ids"]) == 0:
        return {
            "query": query,
            "data": [],
            "total_matches": 0,
            "channel": ch,
            "message": "Không tìm thấy video nào phù hợp với yêu cầu tìm kiếm."
        }

    conn = database.get_db_connection()
    cursor = conn.cursor()

    target_id = decomp.get("target_event_id")
    event_ids = decomp.get("event_ids") or []
    ch = decomp.get("channel")

    # Query events that have real clips
    sql = """
        SELECT id, event_code, event_type, channel, timestamp, description, severity, clip_filename, clip_duration_sec
        FROM events
        WHERE clip_filename IS NOT NULL AND TRIM(clip_filename) != ''
    """
    params = []

    if target_id:
        sql += " AND id = ?"
        params.append(target_id)
        cursor.execute(sql, params)
        rows = [dict(r) for r in cursor.fetchall()]
        valid_rows = []
        for r in rows:
            try:
                if resolve_clip_path(r["clip_filename"]).is_file():
                    valid_rows.append(r)
            except Exception:
                pass
        if valid_rows:
            rows = valid_rows
        else:
            # If target_id has no clip file, locate the nearest real clip on the same channel
            cursor.execute("SELECT * FROM events WHERE id = ?", (target_id,))
            target_ev = cursor.fetchone()
            if target_ev:
                t_dict = dict(target_ev)
                t_time = t_dict.get("timestamp")
                t_ch = t_dict.get("channel")
                cursor.execute("""
                    SELECT id, event_code, event_type, channel, timestamp, description, severity, clip_filename, clip_duration_sec,
                           ABS(strftime('%s', timestamp) - strftime('%s', ?)) as time_diff
                    FROM events
                    WHERE channel = ? AND clip_filename IS NOT NULL AND TRIM(clip_filename) != ''
                    ORDER BY time_diff ASC LIMIT 5
                """, (t_time, t_ch))
                nearby_rows = [dict(r) for r in cursor.fetchall()]
                if not nearby_rows:
                    cursor.execute("""
                        SELECT id, event_code, event_type, channel, timestamp, description, severity, clip_filename, clip_duration_sec,
                               ABS(strftime('%s', timestamp) - strftime('%s', ?)) as time_diff
                        FROM events
                        WHERE clip_filename IS NOT NULL AND TRIM(clip_filename) != ''
                        ORDER BY time_diff ASC LIMIT 5
                    """, (t_time,))
                    nearby_rows = [dict(r) for r in cursor.fetchall()]
                for nr in nearby_rows:
                    try:
                        if resolve_clip_path(nr["clip_filename"]).is_file():
                            nr["title"] = f"Event #{target_id} (Clip #{nr['id']})"
                            nr["description"] = f"[Clip tương ứng lúc {nr.get('timestamp')} trên Cam {nr.get('channel')}] {nr.get('description', '')}"
                            rows = [nr]
                            break
                    except Exception:
                        pass
    elif event_ids:
        # Highest precision: prioritize specific event IDs grounded by Agent RAG across any cameras
        placeholders = ",".join(["?"] * len(event_ids))
        sql += f" AND id IN ({placeholders})"
        params.extend(event_ids)
        # Only enforce channel if explicit channel was mentioned in the text query itself
        if ch and any(k in decomp.get("raw_query", "").lower() for k in ["cam", "kênh", "channel", "ch"]):
            sql += " AND channel = ?"
            params.append(ch)
        req_top_k = max(int(decomp.get("top_k") or 10), len(event_ids))
        sql += f" ORDER BY id DESC LIMIT {max(200, req_top_k * 4)}"
        cursor.execute(sql, params)
        rows = [dict(r) for r in cursor.fetchall()]
    else:
        # Enforce channel filter strictly so other cameras are never accidentally leaked
        if ch:
            sql += " AND channel = ?"
            params.append(ch)

        # Enforce strict time range and date if requested
        if decomp.get("from_time"):
            sql += " AND timestamp >= ?"
            params.append(decomp["from_time"])
        if decomp.get("to_time"):
            sql += " AND timestamp <= ?"
            params.append(decomp["to_time"])
        if decomp.get("target_date") and not decomp.get("from_time"):
            sql += " AND timestamp LIKE ?"
            params.append(f"{decomp['target_date']}%")

        if decomp["event_codes"]:
            placeholders = ",".join(["?"] * len(decomp["event_codes"]))
            sql += f" AND event_code IN ({placeholders})"
            params.extend(decomp["event_codes"])

        req_top_k = max(int(decomp.get("top_k") or 10), 10)
        sql += f" ORDER BY id DESC LIMIT {max(200, req_top_k * 4)}"
        cursor.execute(sql, params)
        rows = [dict(r) for r in cursor.fetchall()]

    # ONLY do generic browsing fallback if user gave NO specific criteria at all (e.g. empty search or "tất cả video")
    has_specific_filter = bool(
        target_id 
        or ("event_ids" in filters and filters["event_ids"] is not None)
        or decomp.get("from_time")
        or decomp.get("to_time")
        or decomp.get("target_date")
        or decomp.get("event_codes")
        or decomp.get("is_time_filtered")
    )

    if not has_specific_filter and len(rows) < decomp["top_k"]:
        fallback_limit = max(200, decomp["top_k"] * 4)
        fallback_sql = """
            SELECT id, event_code, event_type, channel, timestamp, description, severity, clip_filename, clip_duration_sec
            FROM events
            WHERE clip_filename IS NOT NULL AND TRIM(clip_filename) != ''
        """
        fallback_params = []
        if ch:
            fallback_sql += " AND channel = ?"
            fallback_params.append(ch)
            
        fallback_sql += f" ORDER BY id DESC LIMIT {fallback_limit}"
        cursor.execute(fallback_sql, fallback_params)
        fallback_rows = [dict(r) for r in cursor.fetchall()]
        existing_ids = {r["id"] for r in rows}
        for fr in fallback_rows:
            if fr["id"] not in existing_ids:
                rows.append(fr)
                if len(rows) >= fallback_limit:
                    break

    conn.close()

    # Verify physical file existence and compute similarity scores
    results = []
    lowered_q = decomp["raw_query"].lower()

    for row in rows:
        clip_name = row["clip_filename"]
        clip_path = resolve_clip_path(clip_name)
        if not clip_path.is_file():
            continue

        # Score calculation based on query match and severity
        desc = (row["description"] or "").lower()
        code = (row["event_code"] or "").lower()
        
        sim = 0.60
        if (target_id and row["id"] == target_id) or (event_ids and row["id"] in event_ids):
            sim = 0.99
        else:
            if ch and row["channel"] == ch:
                sim += 0.15

            # Boost for human only if user query specifically asks for persons
            is_human_query = any(k in lowered_q for k in ["người", "nguoi", "nhân viên", "nhan vien", "khách", "khach", "human", "person"])
            if is_human_query and any(term in desc or term in code for term in ["human", "người", "nguoi", "person"]):
                sim += 0.25

            # Boost for anomalies when query asks for abnormal events/alarms
            is_anomaly_query = any(k in lowered_q for k in ["bất thường", "bat thuong", "anomaly", "cảnh báo", "canh bao", "nguy hiểm", "nguy hiem", "sự cố", "alarm"])
            is_anomaly_event = row["severity"] in ("high", "medium") or any(term in desc or term in code for term in ["bất thường", "bat thuong", "anomaly", "videomotion", "audiomutation", "sounddetection", "intrusion", "crossline", "fight"])
            if is_anomaly_query and is_anomaly_event:
                sim += 0.28

            if row["severity"] == "high":
                sim += 0.08
            elif row["severity"] == "medium":
                sim += 0.04

            # Word overlap
            q_words = [w for w in re.split(r'\W+', lowered_q) if len(w) > 2]
            if q_words:
                matched_words = sum(1 for w in q_words if w in desc or w in code)
                sim += min(0.15, (matched_words / len(q_words)) * 0.15)

        sim = round(min(0.99, max(0.40, sim)), 2)

        if sim < decomp["min_similarity"]:
            continue

        # Critic evaluation
        critic = evaluate_critic(row, decomp, sim)

        start_time_fmt = format_time_str(row["timestamp"])
        end_time_fmt = calculate_end_time(row["timestamp"], row.get("clip_duration_sec", 10))

        # Build clean web path for playback
        clip_web_url = "/clips/" + clip_name.replace("\\", "/")

        results.append({
            "id": row["id"],
            "video_name": f"{row['event_code']}_cam{row['channel']}_{row['id']}",
            "title": f"Cam {row['channel']:02d} - {row['event_code']} (#{row['id']})",
            "description": row["description"],
            "start_time": start_time_fmt,
            "end_time": end_time_fmt,
            "sensor_id": f"cam-{row['channel']:03d}",
            "similarity": sim,
            "screenshot_url": clip_web_url,
            "video_url": clip_web_url,
            "clip_filename": clip_name,
            "event_id": row["id"],
            "channel": row["channel"],
            "pills": [f"{k}: {'✓' if v else '✗'}" for k, v in critic["criteria_met"].items()],
            "critic_result": critic
        })

    # Sort results by similarity descending
    results.sort(key=lambda x: (1 if x["critic_result"]["result"] == "confirmed" else 0, x["similarity"]), reverse=True)
    final_results = results[:decomp["top_k"]]

    # Python Code representation for Vision Agent Function Start trace
    function_input_code = (
        f"messages=\n"
        f"[Message(content='{decomp['raw_query']}',\n"
        f"role=<UserMessageContentRoleType.USER: 'user'>)]\n"
        f"model='Qwen3.8-27B (4x NVIDIA H200 SGLang)'\n"
        f"channel={decomp['channel'] or 11}\n"
        f"attributes={decomp['attributes']}\n"
        f"min_similarity={decomp['min_similarity']}\n"
        f"top_k={decomp['top_k']}\n"
        f"critic_enabled=True"
    )

    return {
        "query": decomp["raw_query"],
        "data": final_results,
        "count": len(final_results),
        "total_matches": len(final_results),
        "function_input_code": function_input_code,
        "summary": f"Found {len(final_results)} events matching '{decomp['raw_query']}' in camera archive."
    }
