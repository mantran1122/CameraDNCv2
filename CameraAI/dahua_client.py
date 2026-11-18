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
        self._last_clip_queued = {}  # channel -> timestamp float
        self._last_event_per_channel = {}  # channel -> timestamp float

    def _is_rtsp_alive(self, channel: int) -> bool:
        """Kiểm tra phản hồi nhanh (2s) của luồng RTSP camera."""
        import subprocess
        from urllib.parse import quote
        rtsp_user = quote(str(config.NVR_USER), safe="")
        rtsp_password = quote(str(config.NVR_PASSWORD), safe="")
        url = f"rtsp://{rtsp_user}:{rtsp_password}@{config.NVR_HOST}:{config.RTSP_PORT}/cam/realmonitor?channel={channel}&subtype=1"
        cmd = [
            config.FFMPEG_PATH, "-v", "error", "-rtsp_transport", "tcp",
            "-t", "1", "-i", url, "-f", "null", "-"
        ]
        try:
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=4)
            return res.returncode == 0
        except Exception:
            return False

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
        auth_failure_count = 0

        while self.is_running:
            # Prevent accidental spamming if password is empty or blank
            if not (config.NVR_PASSWORD and str(config.NVR_PASSWORD).strip()):
                print("[DahuaClient] Mật khẩu NVR chưa được cấu hình. Tạm dừng kết nối để tránh khóa tài khoản...")
                time.sleep(15)
                continue

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
                        auth_failure_count = 0
                        print(f"[DahuaClient] Connected successfully to Dahua NVR ({config.NVR_HOST}:{config.NVR_PORT}).")
                        self.is_connected = True
                        self.last_packet_time = time.time()
                        self.current_response = response
                        self.parse_multipart_stream(response)
                    elif response.status_code in (401, 403):
                        self.is_connected = False
                        auth_failure_count += 1
                        backoff = min(120, 30 * auth_failure_count)
                        print(f"[DahuaClient] LỖI XÁC THỰC HTTP {response.status_code} từ NVR ({config.NVR_HOST})! Sai user/password hoặc tài khoản tạm bị khóa. Tạm dừng {backoff}s để tránh khóa tài khoản...")
                        time.sleep(backoff)
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
                            auth_failure_count = 0
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
        self._last_event_per_channel[channel] = time.time()

        # Check active channels filter
        if config.ACTIVE_CHANNELS and channel not in config.ACTIVE_CHANNELS:
            return

        now = datetime.now()
        timestamp_str = now.strftime("%Y-%m-%d %H:%M:%S")

        # Xử lý riêng sự kiện ngắt phiên RTSP theo chỉ đạo của sếp: Chỉ báo động khi mất kết nối thực tế >= 1 phút (60s)
        if code == "RtspSessionDisconnect":
            event_id = database.save_event(
                event_code=code,
                event_type="network_anomaly",
                channel=channel,
                timestamp=timestamp_str,
                description=f"Mất kết nối luồng RTSP tại Cam {channel:02d}",
                severity="medium",
                metadata_dict=event_data,
            )
            self.last_event_time = time.time()
            self.total_events_received += 1

            def _verify_outage(ch: int, ev_id: int):
                time.sleep(60)
                now_check = time.time()
                last_active = self._last_event_per_channel.get(ch, 0.0)
                # 1. Nếu trong 60s qua camera vẫn gửi metadata (chuyển động, người...) -> Đang hoạt động bình thường!
                if now_check - last_active < 55.0:
                    print(f"[RtspWatchdog] Cam {ch} có sự kiện hoạt động gần đây ({now_check - last_active:.1f}s trước). Bỏ qua cảnh báo mất kết nối tạm thời.")
                    return
                # 2. Kiểm tra trực tiếp luồng RTSP của camera
                if self._is_rtsp_alive(ch):
                    print(f"[RtspWatchdog] Luồng RTSP Cam {ch} vẫn phản hồi tốt sau 60s. Bỏ qua cảnh báo ngắt phiên tạm thời.")
                    return
                # 3. Mất kết nối thực tế kéo dài trên 1 phút!
                print(f"[RtspWatchdog] XÁC NHẬN MẤT KẾT NỐI Cam {ch} >= 1 phút! Bắt đầu phát cảnh báo đỏ.")
                ev_obj = database.get_event_by_id(ev_id)
                if ev_obj:
                    ev_obj["description"] = f"Mất kết nối Camera tại Cam {ch:02d} (Tín hiệu gián đoạn trên 1 phút)"
                    ev_obj["severity"] = "high"
                    if self.broadcast_callback:
                        self.broadcast_callback(ev_obj)

            t = threading.Thread(target=_verify_outage, args=(channel, event_id), daemon=True, name=f"rtsp-watchdog-{channel}")
            t.start()
            return

        event_type = "normal_metadata"
        severity = "info"
        description = f"Phát hiện sự kiện {code} tại Camera Ch {channel:02d}"
        audio_db = None

        is_selected_abnormal = config.is_channel_anomaly(channel, code)
        is_zalo_alert = False
        try:
            from alert_dispatcher import get_zalo_alert_config
            z_cfg = get_zalo_alert_config()
            z_events = set(z_cfg.get("zalo_alert_events") or [])
            z_channels = set(z_cfg.get("zalo_alert_channels") or [])
            if not z_channels or channel in z_channels:
                if code in z_events:
                    is_zalo_alert = True
                elif code in ("SoundDetection", "AudioAnomaly") and "AudioMutation" in z_events:
                    is_zalo_alert = True
                elif code == "SmartMotionHuman" and "HumanTrait" in z_events:
                    is_zalo_alert = True
        except Exception:
            pass

        is_alert_event = is_selected_abnormal or is_zalo_alert

        code_vn_map = {
            "Intrusion": "Xâm nhập trái phép",
            "CrossLine": "Vượt vạch cấm",
            "Fight": "Ẩu đả / Xô xát",
            "VideoMotion": "Chuyển động bất thường",
            "SoundDetection": "Âm thanh bất thường",
            "AudioAnomaly": "Âm thanh đột biến",
            "AudioMutation": "Âm thanh đột biến",
            "HumanTrait": "Người di chuyển (Human Trait)",
            "SmartMotionHuman": "Người di chuyển (Smart Motion)",
            "FaceDetection": "Nhận diện khuôn mặt",
            "VehicleTrait": "Phương tiện di chuyển",
        }
        vn_code = code_vn_map.get(code, code)

        if is_alert_event and code in config.AUDIO_EVENT_CODES:
            event_type = "audio_anomaly"
            severity = "high"
            audio_db = float(event_data.get("AudioValue", 85.0))
            description = f"Cảnh Báo Âm Thanh: {vn_code} ({audio_db} dB) tại Cam {channel:02d}"
        elif is_alert_event:
            event_type = "video_anomaly"
            severity = "high" if (code in config.CRITICAL_ANOMALY_CODES or is_zalo_alert) else "medium"
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

            if event_type in {"audio_anomaly", "video_anomaly"} or is_alert_event:
                now_ts = time.time()
                # Phân loại độ ưu tiên: Cảnh báo âm thanh hoặc hành vi khẩn cấp KHÔNG bị chặn bởi sự kiện chuyển động thông thường
                is_audio_group = (
                    event_type == "audio_anomaly"
                    or code in getattr(config, "AUDIO_EVENT_CODES", [])
                )
                is_high_priority = (
                    is_audio_group
                    or code in getattr(config, "CRITICAL_ANOMALY_CODES", [])
                    or severity == "high"
                )
                if is_audio_group:
                    debounce_key = f"{channel}_AudioMutation"
                elif is_high_priority:
                    debounce_key = f"{channel}_{code}"
                else:
                    debounce_key = f"{channel}_routine"
                last_queued_ts = self._last_clip_queued.get(debounce_key, 0.0)
                cooldown_limit = 8.0 if is_high_priority else 15.0

                if now_ts - last_queued_ts >= cooldown_limit:
                    self._last_clip_queued[debounce_key] = now_ts
                    database.create_audio_analysis(event_id, status="not_analyzed")
                    if self.audio_job_callback:
                        self.audio_job_callback(event_id)
                else:
                    # Nếu sự kiện cùng camera rơi vào giãn cách, tự động tái sử dụng clip vừa quay gần nhất (trong 45s)
                    recent_clip = database.get_recent_clip_for_channel(channel, max_age_seconds=45)
                    if recent_clip:
                        database.update_event_clip(event_id, recent_clip)
                    database.create_audio_analysis(
                        event_id,
                        status="video_cooldown",
                    )

            event_obj = database.get_event_by_id(event_id)
            print(f"[DahuaClient] Stored event id={event_id} code={code} channel={channel}")
            if event_obj and self.broadcast_callback:
                self.broadcast_callback(event_obj)
        except Exception as save_err:
            print(f"[DahuaClient Error] Failed to persist event {code} (Ch {channel}): {save_err}")
