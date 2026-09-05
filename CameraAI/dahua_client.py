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
        super().__init__(daemon=True)
        self.broadcast_callback = broadcast_callback
        self.audio_job_callback = audio_job_callback
        self.is_running = False
        
    def stop(self):
        self.is_running = False

    def run(self):
        if config.DEMO_MODE:
            print("[DahuaClient] DEMO_MODE enabled. Listener standing by.")
            return

        self.is_running = True
        protocol = "https" if config.USE_HTTPS else "http"
        url = (
            f"{protocol}://{config.NVR_HOST}:{config.NVR_PORT}/cgi-bin/eventManager.cgi"
            # Dahua firmwares differ in which individual event codes they
            # accept.  Subscribe to All and classify/filter locally so one
            # unsupported code cannot silently suppress the whole stream.
            "?action=attach&codes=[All]"
        )
        print(f"[DahuaClient] Connecting to Dahua NVR event stream over Internet/WAN: {url}")
        
        auth = HTTPDigestAuth(config.NVR_USER, config.NVR_PASSWORD)
        
        while self.is_running:
            try:
                response = requests.get(url, auth=auth, stream=True, timeout=60, verify=False)
                if response.status_code == 200:
                    print(f"[DahuaClient] Connected successfully to Dahua NVR ({config.NVR_HOST}).")
                    self.parse_multipart_stream(response)
                else:
                    print(f"[DahuaClient] HTTP Error {response.status_code} from NVR ({config.NVR_HOST}). Retrying in 10s...")
                    time.sleep(10)
            except Exception as e:
                print(f"[DahuaClient] Connection error to {config.NVR_HOST}: {e}. Retrying in 10s...")
                time.sleep(10)

    def parse_multipart_stream(self, response):
        buffer = ""
        for chunk in response.iter_content(chunk_size=1024):
            if not self.is_running:
                break
            if chunk:
                buffer += chunk.decode('utf-8', errors='ignore')
                while "\r\n\r\n" in buffer or "\n\n" in buffer:
                    parts = re.split(r'\r\n\r\n|\n\n', buffer, 1)
                    header_block = parts[0]
                    buffer = parts[1] if len(parts) > 1 else ""
                    
                    self.process_event_block(header_block)

    def process_event_block(self, block_str: str):
        event_data = {}

        # Dahua eventManager commonly sends a single record such as
        # ``Code=VideoMotion;action=Start;index=0``.  Some firmware versions
        # send one key per line instead.  Accept both forms.
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
        
        is_selected_abnormal = code in config.ABNORMAL_EVENT_CODES
        if is_selected_abnormal and code in config.AUDIO_EVENT_CODES:
            event_type = "audio_anomaly"
            severity = "high"
            audio_db = float(event_data.get("AudioValue", 85.0))
            description = f"BẤT THƯỜNG ĐÃ CHỌN: {code} ({audio_db} dB) tại Cam {channel:02d}"
        elif is_selected_abnormal:
            event_type = "video_anomaly"
            severity = "high"
            description = f"BẤT THƯỜNG ĐÃ CHỌN TỪ METADATA: {code} tại Cam {channel:02d}"
        elif code in ["FaceDetection", "HumanTrait"]:
            description = f"Metadata Người: Phát hiện đối tượng tại Cam {channel:02d}"
        elif code in ["VehicleTrait"]:
            description = f"Metadata Phương tiện: Phát hiện xe tại Cam {channel:02d}"

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
        if event_type in {"audio_anomaly", "video_anomaly"}:
            # The worker waits until the NVR has committed the post-event
            # buffer, then captures the full 10 seconds and reports the audio
            # result (including a missing audio track) to the dashboard.
            database.create_audio_analysis(event_id, status="not_analyzed")
            if self.audio_job_callback:
                self.audio_job_callback(event_id)
        
        event_obj = database.get_event_by_id(event_id)
        print(f"[DahuaClient] Stored event id={event_id} code={code} channel={channel}")
        if event_obj and self.broadcast_callback:
            self.broadcast_callback(event_obj)
