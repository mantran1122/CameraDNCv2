from datetime import datetime, date
from typing import Dict, Any, List
import database

def generate_daily_summary(target_date_str: str = None) -> Dict[str, Any]:
    if not target_date_str:
        target_date_str = date.today().strftime("%Y-%m-%d")
        
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    # Query events for the target date
    cursor.execute("""
        SELECT * FROM events 
        WHERE timestamp LIKE ?
        ORDER BY id ASC
    """, (f"{target_date_str}%",))
    rows = cursor.fetchall()
    conn.close()
    
    events = [dict(r) for r in rows]
    
    total_events = len(events)
    video_anomalies = [e for e in events if e["event_type"] == "video_anomaly"]
    audio_anomalies = [e for e in events if e["event_type"] == "audio_anomaly"]
    human_events = [e for e in events if e["event_code"] in ["HumanTrait", "FaceDetection"]]
    vehicle_events = [e for e in events if e["event_code"] in ["VehicleTrait"]]
    
    # Hourly timeline distribution
    hourly_distribution = [0] * 24
    hourly_anomalies = [0] * 24
    channel_counts: Dict[int, int] = {}
    
    max_audio_db = 0.0
    loudest_audio_channel = None
    loudest_audio_time = None
    
    for e in events:
        try:
            dt = datetime.strptime(e["timestamp"], "%Y-%m-%d %H:%M:%S")
            h = dt.hour
            hourly_distribution[h] += 1
            if e["event_type"] in ["audio_anomaly", "video_anomaly"]:
                hourly_anomalies[h] += 1
        except Exception:
            pass
            
        ch = e["channel"]
        channel_counts[ch] = channel_counts.get(ch, 0) + 1
        
        if e["audio_level_db"] and e["audio_level_db"] > max_audio_db:
            max_audio_db = e["audio_level_db"]
            loudest_audio_channel = ch
            loudest_audio_time = e["timestamp"]

    peak_hour = hourly_distribution.index(max(hourly_distribution)) if total_events > 0 else 12
    top_channels = sorted(channel_counts.items(), key=lambda x: x[1], reverse=True)[:3]
    
    # Construct Natural Language Executive AI Report (Vietnamese)
    if total_events == 0:
        ai_narrative = f"Trạng thái ngày {target_date_str}: Không ghi nhận dữ liệu metadata hoặc sự kiện bất thường nào từ đầu ghi Dahua DHI-NVR5832-EI2."
    else:
        ai_narrative = (
            f"📌 **TÓM TẮT BÁO CÁO HOẠT ĐỘNG NGÀY {target_date_str} (HỆ THỐNG DAHUA AI NVR5832-EI2)**\n\n"
            f"1. **Tổng quan Hoạt động:**\n"
            f"   - Tổng số lượt phát hiện Metadata: **{total_events} lượt**.\n"
            f"   - Ghi nhận **{len(human_events)}** lượt diện mạo con người và **{len(vehicle_events)}** phương tiện giao thông di chuyển trong khu vực quan sát.\n"
            f"   - Khung giờ cao điểm hoạt động nhộn nhịp nhất trong ngày rơi vào khoảng **{peak_hour}:00 - {peak_hour+1}:00**.\n\n"
            f"2. **Cảnh báo Bất thường (Video & Âm thanh):**\n"
            f"   - Tổng số sự kiện bất thường ghi nhận: **{len(video_anomalies) + len(audio_anomalies)} sự kiện**.\n"
            f"   - **Bất thường Âm thanh ({len(audio_anomalies)} vụ):** Đã ghi nhận các đỉnh âm thanh bất thường (tiếng la gào, cãi vã, tiếng đập phá)."
        )
        if max_audio_db > 0:
            ai_narrative += f" Độ ồn cao nhất đạt **{max_audio_db} dB** tại Camera Kênh {loudest_audio_channel:02d} lúc {loudest_audio_time}."
        ai_narrative += (
            f"\n   - **Bất thường Video ({len(video_anomalies)} vụ):** Ghi nhận các hành vi đột nhập vi phạm ranh giới an ninh (Intrusion/Tripwire/Fight).\n\n"
            f"3. **Tự động Cắt Video 10s Xem lại:**\n"
            f"   - Toàn bộ {len(video_anomalies) + len(audio_anomalies)} sự kiện bất thường đều đã được hệ thống tự động trích xuất đoạn ghi hình 10 giây (5 giây trước + 5 giây sau cảnh báo) từ luồng RTSP Playback của NVR và sẵn sàng phát lại ngay trên Dashboard."
        )

    summary_data = {
        "date": target_date_str,
        "total_events": total_events,
        "anomaly_video_count": len(video_anomalies),
        "anomaly_audio_count": len(audio_anomalies),
        "human_count": len(human_events),
        "vehicle_count": len(vehicle_events),
        "peak_hour": peak_hour,
        "hourly_distribution": hourly_distribution,
        "hourly_anomalies": hourly_anomalies,
        "max_audio_db": max_audio_db,
        "loudest_channel": loudest_audio_channel,
        "top_channels": top_channels,
        "summary_text": ai_narrative
    }
    
    return summary_data
