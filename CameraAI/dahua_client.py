import time
import json
import re
import threading
from datetime import datetime
import requests
from requests.auth import HTTPDigestAuth

import config
import database

class DahuaNVRListener(threading.Thread):
    def __init__(self, broadcast_callback=None, audio_job_callback=None):
        super().__init__(daemon=True, name="dahua-nvr-listener")
        self.broadcast_callback = broadcast_callback
        self.audio_job_callback = audio_job_callback
        self.is_running = False
        self.is_connected = False
        self.last_packet_time = 0.0
        self.last_event_time = 0.0
        self.total_events_received = 0
        self.current_response = None
        self._watchdog_thread = None

    def stop(self):
        self.is_running = False
        self.is_connected = False
        if self.current_response:
            try:
                self.current_response.close()
            except Exception:
                pass

    def get_status(self) -> dict:
        now = time.time()
        idle_sec = int(now - self.last_packet_time) if self.last_packet_time > 0 else -1
        event_idle_sec = int(now - self.last_event_time) if self.last_event_time > 0 else -1
        return {
            "is_running": self.is_running,
            "is_connected": self.is_connected,
            "idle_seconds": idle_sec,
            "event_idle_seconds": event_idle_sec,
            "total_events_received": self.total_events_received,
            "nvr_target": f"{config.NVR_HOST}:{config.NVR_PORT}",
        }

    def _start_watchdog(self):
        def _watchdog():
            while self.is_running:
                time.sleep(15)
                if self.is_connected and self.current_response:
                    idle = time.time() - self.last_packet_time
                    # If connected but no packets or heartbeats for > 90 seconds, the TCP connection is dead
                    if self.last_packet_time > 0 and idle > 90:
                        print(f"[DahuaClient Watchdog] Stream connection stalled (no data for {int(idle)}s). Forcing reconnect...")
                        try:
                            self.current_response.close()
                        except Exception:
                            pass

        self._watchdog_thread = threading.Thread(target=_watchdog, daemon=True, name="dahua-watchdog")
        self._watchdog_thread.start()

    def run(self):
        if config.DEMO_MODE:
            print("[DahuaClient] DEMO_MODE enabled. Listener standing by.")
            return

        self.is_running = True
        self._start_watchdog()

        while self.is_running:
            # Auto-detect HTTPS: Port 4443, 443, 8443 or config.USE_HTTPS
            use_https = bool(config.USE_HTTPS or config.NVR_PORT in (443, 4443, 8443))
            protocol = "https" if use_https else "http"
            url = (
                f"{protocol}://{config.NVR_HOST}:{config.NVR_PORT}/cgi-bin/eventManager.cgi"
                "?action=attach&codes=[All]"
            )
            print(f"[DahuaClient] Connecting to Dahua NVR event stream ({protocol.upper()}): {url}")

            auth = HTTPDigestAuth(config.NVR_USER, config.NVR_PASSWORD)

            try:
                # Use a session with stream=True and connect timeout 15s, read timeout 60s
                with requests.Session() as session:
                    response = session.get(url, auth=auth, stream=True, timeout=(15, 60), verify=False)
                    if response.status_code == 200:
                        print(f"[DahuaClient] Connected successfully to Dahua NVR ({config.NVR_HOST}:{config.NVR_PORT}).")
                        self.is_connected = True
                        self.last_packet_time = time.time()
                        self.current_response = response
                        self.parse_multipart_stream(response)
                    else:
                        self.is_connected = False
                        print(f"[DahuaClient] HTTP Error {response.status_code} from NVR ({config.NVR_HOST}). Retrying in 10s...")
                        time.sleep(10)
            except Exception as e:
                self.is_connected = False
                # If HTTP failed on initial connection, try HTTPS fallback
                if protocol == "http" and "SSLError" not in str(e):
                    try:
                        fallback_url = f"https://{config.NVR_HOST}:{config.NVR_PORT}/cgi-bin/eventManager.cgi?action=attach&codes=[All]"
                        print(f"[DahuaClient] Trying HTTPS fallback to {fallback_url}...")
                        fb_resp = requests.get(fallback_url, auth=auth, stream=True, timeout=(15, 60), verify=False)
                        if fb_resp.status_code == 200:
                            print(f"[DahuaClient] Connected successfully via HTTPS fallback ({config.NVR_HOST}).")
                            self.is_connected = True
                            self.last_packet_time = time.time()
                            self.current_response = fb_resp
                            self.parse_multipart_stream(fb_resp)
                            continue
                    except Exception as fb_err:
                        print(f"[DahuaClient] HTTPS fallback failed: {fb_err}")
                print(f"[DahuaClient] Connection error to {config.NVR_HOST}: {e}. Retrying in 5s...")
                time.sleep(5)
            finally:
                self.is_connected = False
                self.current_response = None

    def parse_multipart_stream(self, response):
        buffer = ""
        try:
            for chunk in response.iter_content(chunk_size=1024):
                if not self.is_running:
                    break
                if chunk:
                    self.last_packet_time = time.time()
                    buffer += chunk.decode('utf-8', errors='ignore')
                    while "\r\n\r\n" in buffer or "\n\n" in buffer:
                        parts = re.split(r'\r\n\r\n|\n\n', buffer, 1)
                        header_block = parts[0]
                        buffer = parts[1] if len(parts) > 1 else ""

                        try:
                            self.process_event_block(header_block)
                        except Exception as block_err:
                            print(f"[DahuaClient Error] Failed to process event block: {block_err}")
        except Exception as stream_err:
            print(f"[DahuaClient] Stream read ended: {stream_err}")
        finally:
            self.is_connected = False
            self.current_response = None

    def process_event_block(self, block_str: str):
        event_data = {}

        for line in block_str.strip().splitlines():
            for field in line.split(";"):
                if "=" not in field:
                    continue
                key, val = field.split("=", 1)
                key = key.strip()
                if key:
                    canonical_key = {"code": "Code", "action": "action", "index": "index"}.get(key.lower(), key)
                    event_data[canonical_key] = val.strip()

        code = event_data.get("Code")
        action = event_data.get("action")
        index = event_data.get("index", "0")

        if not code or str(action).lower() != "start":
            return

        channel = int(index) + 1 if index.isdigit() else 1

        # Check active channels filter
        if config.ACTIVE_CHANNELS and channel not in config.ACTIVE_CHANNELS:
            return

        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")

        event_type = "normal_metadata"
        severity = "info"
        description = f"Phát hiện sự kiện {code} tại Camera Ch {channel:02d}"
        audio_db = None

        is_selected_abnormal = (
            code in config.ABNORMAL_EVENT_CODES
            or (code == "SmartMotionHuman" and "HumanTrait" in config.ABNORMAL_EVENT_CODES)
        )
        if is_selected_abnormal and code in config.AUDIO_EVENT_CODES:
            event_type = "audio_anomaly"
            severity = "high"
            audio_db = float(event_data.get("AudioValue", 85.0))
            description = f"Cảnh Báo Âm Thanh: {code} ({audio_db} dB) tại Cam {channel:02d}"
        elif is_selected_abnormal:
            event_type = "video_anomaly"
            severity = "medium" if code in ["HumanTrait", "SmartMotionHuman", "FaceDetection"] else "high"
            code_vn_map = {
                "Intrusion": "Xâm nhập trái phép",
                "CrossLine": "Vượt vạch cấm",
                "Fight": "Ẩu đả / Xô xát",
                "VideoMotion": "Chuyển động bất thường",
                "SoundDetection": "Âm thanh bất thường",
                "AudioAnomaly": "Âm thanh đột biến",
                "HumanTrait": "Người di chuyển (Human Trait)",
                "SmartMotionHuman": "Người di chuyển (Smart Motion)",
                "FaceDetection": "Nhận diện khuôn mặt",
                "VehicleTrait": "Phương tiện di chuyển",
            }
            vn_code = code_vn_map.get(code, code)
            description = f"Cảnh Báo ({vn_code}) tại Cam {channel:02d}"
        elif code in ["FaceDetection", "HumanTrait"]:
            description = f"Phát hiện người (Human Trait) tại Cam {channel:02d}"
        elif code in ["VehicleTrait"]:
            description = f"Phát hiện phương tiện (Vehicle Trait) tại Cam {channel:02d}"
        else:
            description = f"Sự kiện {code} tại Cam {channel:02d}"

        try:
            event_id = database.save_event(
                event_code=code,
                event_type=event_type,
                channel=channel,
                timestamp=timestamp_str,
                description=description,
                severity=severity,
                audio_level_db=audio_db,
                metadata_dict=event_data,
            )
            self.last_event_time = time.time()
            self.total_events_received += 1

            if event_type in {"audio_anomaly", "video_anomaly"}:
                database.create_audio_analysis(event_id, status="not_analyzed")
                if self.audio_job_callback:
                    self.audio_job_callback(event_id)

            event_obj = database.get_event_by_id(event_id)
            print(f"[DahuaClient] Stored event id={event_id} code={code} channel={channel}")
            if event_obj and self.broadcast_callback:
                self.broadcast_callback(event_obj)
        except Exception as save_err:
            print(f"[DahuaClient Error] Failed to persist event {code} (Ch {channel}): {save_err}")
