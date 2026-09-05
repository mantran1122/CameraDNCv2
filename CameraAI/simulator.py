import time
import random
import threading
from datetime import datetime, timedelta

import config
import database

class NVRDataSimulator(threading.Thread):
    def __init__(self, broadcast_callback=None, audio_job_callback=None):
        super().__init__(daemon=True)
        self.broadcast_callback = broadcast_callback
        self.audio_job_callback = audio_job_callback
        self.is_running = False

    def seed_historical_today_data(self):
        """
        Seeds realistic historical metadata and anomaly events for the current day
        so the dashboard charts and AI summaries show rich data right away.
        """
        conn = database.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM events")
        count = cursor.fetchone()[0]
        conn.close()
        
        if count > 10:
            print("[Simulator] Historical events already populated.")
            return

        print("[Simulator] Seeding realistic historical events for Today...")
        now = datetime.now()
        start_of_day = datetime(now.year, now.month, now.day, 6, 0, 0)
        
        sample_scenarios = [
            # Morning peak
            (7, 15, 1, "FaceDetection", "normal_metadata", "Phát hiện nhân viên vào cổng chính", "info", None, {"gender": "Male", "age": 32, "mask": False}),
            (8, 30, 2, "VehicleTrait", "normal_metadata", "Phát hiện Xe ô tô BKS 30H-882.19 vào bãi", "info", None, {"plate": "30H-882.19", "color": "White", "type": "Sedan"}),
            (9, 45, 3, "AudioAnomaly", "audio_anomaly", "BẤT THƯỜNG ÂM THANH: Tiếng la gào / cãi vã (92 dB)", "high", 92.5, {"audio_type": "Screaming", "peak_frequency_hz": 2400}),
            (10, 10, 1, "HumanTrait", "normal_metadata", "Phát hiện nhóm 3 người di chuyển tại hành lang A", "info", None, {"count": 3, "clothing": "Dark shirt"}),
            (11, 20, 4, "Intrusion", "video_anomaly", "BẤT THƯỜNG VIDEO: Đột nhập khu vực cấm Kho Hàng", "high", None, {"zone": "Restricted_Warehouse_4"}),
            
            # Afternoon peak
            (13, 5, 2, "CrossLine", "video_anomaly", "BẤT THƯỜNG VIDEO: Vượt hàng rào bảo vệ Cổng Sau", "high", None, {"line_id": "Gate_Rear_Line_02"}),
            (14, 30, 5, "SoundDetection", "audio_anomaly", "BẤT THƯỜNG ÂM THANH: Tiếng kim loại va đập mạnh / đập phá (88 dB)", "high", 88.0, {"audio_type": "GlassBreak_Impact"}),
            (15, 40, 1, "FaceDetection", "normal_metadata", "Phát hiện đối tượng nghi vấn xuất hiện tại sảnh", "medium", None, {"gender": "Male", "age": 45, "blacklist": False}),
            (16, 15, 3, "VehicleTrait", "normal_metadata", "Phát hiện xe tải giao hàng BKS 29C-512.44", "info", None, {"plate": "29C-512.44", "type": "Truck"}),
            (17, 50, 4, "AudioAnomaly", "audio_anomaly", "BẤT THƯỜNG ÂM THANH: Tiếng còi báo động khẩn cấp (95 dB)", "high", 95.2, {"audio_type": "Siren_Alarm"}),
        ]
        
        for hour, minute, ch, code, ev_type, desc, sev, db_val, meta in sample_scenarios:
            dt = start_of_day.replace(hour=hour, minute=minute)
            if dt > now:
                dt = now - timedelta(minutes=random.randint(5, 60))
            ts_str = dt.strftime("%Y-%m-%d %H:%M:%S")
            
            event_id = database.save_event(
                event_code=code,
                event_type=ev_type,
                channel=ch,
                timestamp=ts_str,
                description=desc,
                severity=sev,
                audio_level_db=db_val,
                metadata_dict=meta
            )
            if ev_type in {"audio_anomaly", "video_anomaly"}:
                database.create_audio_analysis(event_id, status="not_analyzed")
                if self.audio_job_callback:
                    self.audio_job_callback(event_id)

    def run(self):
        self.is_running = True
        self.seed_historical_today_data()
        
        print("[Simulator] Live NVR Event Simulator started.")
        while self.is_running:
            time.sleep(random.randint(15, 30))
            if not self.is_running:
                break
            
            # Generate a new random live event
            channel = random.randint(1, 8)
            now = datetime.now()
            ts_str = now.strftime("%Y-%m-%d %H:%M:%S")
            
            event_choice = random.choices(
                population=["audio_anomaly", "video_anomaly", "normal_human", "normal_vehicle"],
                weights=[0.25, 0.25, 0.3, 0.2]
            )[0]
            
            if event_choice == "audio_anomaly":
                code = random.choice(["AudioAnomaly", "SoundDetection", "FightSound"])
                db_val = round(random.uniform(82.0, 98.5), 1)
                desc = f"BẤT THƯỜNG ÂM THANH: Phát hiện âm thanh vượt ngưỡng ({db_val} dB) tại Cam {channel:02d}"
                sev = "high"
                ev_type = "audio_anomaly"
                meta = {"audio_type": "HighDecibelSound", "peak_frequency_hz": random.randint(1200, 3500)}
            elif event_choice == "video_anomaly":
                code = random.choice(["Intrusion", "CrossLine", "Fight"])
                desc = f"BẤT THƯỜNG VIDEO: Phát hiện vi phạm ranh giới {code} tại Cam {channel:02d}"
                sev = "high"
                ev_type = "video_anomaly"
                db_val = None
                meta = {"zone_id": f"Zone_{channel}", "target": "Human"}
            elif event_choice == "normal_human":
                code = "HumanTrait"
                desc = f"Phát hiện Metadata Người di chuyển tại Cam {channel:02d}"
                sev = "info"
                ev_type = "normal_metadata"
                db_val = None
                meta = {"gender": random.choice(["Male", "Female"]), "age": random.randint(20, 55)}
            else:
                code = "VehicleTrait"
                desc = f"Phát hiện Metadata Phương tiện tại Cam {channel:02d}"
                sev = "info"
                ev_type = "normal_metadata"
                db_val = None
                meta = {"type": random.choice(["Car", "Motorbike", "SUV"]), "color": random.choice(["Black", "White", "Silver"])}

            ev_id = database.save_event(
                event_code=code,
                event_type=ev_type,
                channel=channel,
                timestamp=ts_str,
                description=desc,
                severity=sev,
                audio_level_db=db_val,
                metadata_dict=meta
            )
            if ev_type in {"audio_anomaly", "video_anomaly"}:
                database.create_audio_analysis(ev_id, status="not_analyzed")
                if self.audio_job_callback:
                    self.audio_job_callback(ev_id)
            
            ev_obj = database.get_event_by_id(ev_id)
            if ev_obj and self.broadcast_callback:
                self.broadcast_callback(ev_obj)

    def stop(self):
        self.is_running = False
