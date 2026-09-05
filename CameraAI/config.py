import os
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
# Keep database/config local; video evidence can be redirected to a mounted
# NAS share without changing code.  The value must be writable by the account
# that runs CameraAI (for example: \\nas01\\camera-ai\\clips).
CLIPS_DIR = Path(os.getenv("CAMERAAI_CLIPS_DIR", str(STORAGE_DIR / "clips"))).expanduser()
CONFIG_FILE = STORAGE_DIR / "nvr_config.json"

# Ensure directories exist
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
CLIPS_DIR.mkdir(parents=True, exist_ok=True)

# Default NVR Configuration
DEFAULT_CONFIG = {
    "nvr_host": os.getenv("NVR_HOST", ""),
    "use_https": False,
    "nvr_port": 80,
    "rtsp_port": 554,
    "nvr_user": os.getenv("NVR_USER", ""),
    "nvr_password": os.getenv("NVR_PASSWORD", ""),
    "active_channels": list(range(1, 33)),  # 1 to 32
    "demo_mode": False,
    "pre_buffer_sec": 5,
    "post_buffer_sec": 5,
    # Give the NVR index a moment to publish the final post-event recording
    # segment before requesting playback.
    "clip_ready_delay_sec": 2,
    "metadata_retention_days": 3,
    # Metadata codes selected here are treated as abnormal behaviour. A 10s
    # replay clip is saved for each selected event.
    "abnormal_event_codes": ["Intrusion", "CrossLine", "Fight", "AudioAnomaly", "SoundDetection"]
}

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                merged.update(data)
                return merged
        except Exception as e:
            print(f"[Config] Error loading nvr_config.json: {e}")
    return DEFAULT_CONFIG.copy()

def save_config(cfg_dict: dict):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg_dict, f, indent=4, ensure_ascii=False)

# Load global variables
_current_cfg = load_config()

NVR_HOST = _current_cfg.get("nvr_host", os.getenv("NVR_HOST", ""))
USE_HTTPS = _current_cfg.get("use_https", False)
NVR_PORT = _current_cfg.get("nvr_port", 80)
RTSP_PORT = _current_cfg.get("rtsp_port", 554)
NVR_USER = _current_cfg.get("nvr_user", os.getenv("NVR_USER", ""))
NVR_PASSWORD = _current_cfg.get("nvr_password", os.getenv("NVR_PASSWORD", ""))
ACTIVE_CHANNELS = _current_cfg.get("active_channels", list(range(1, 33)))
DEMO_MODE = _current_cfg.get("demo_mode", False)
ABNORMAL_EVENT_CODES = _current_cfg.get("abnormal_event_codes", DEFAULT_CONFIG["abnormal_event_codes"])
PRE_BUFFER_SEC = _current_cfg.get("pre_buffer_sec", 5)
POST_BUFFER_SEC = _current_cfg.get("post_buffer_sec", 5)
CLIP_DURATION_SEC = PRE_BUFFER_SEC + POST_BUFFER_SEC
CLIP_READY_DELAY_SEC = _current_cfg.get("clip_ready_delay_sec", 2)
METADATA_RETENTION_DAYS = max(1, int(_current_cfg.get("metadata_retention_days", 3)))
COSMOS_AUDIO_URL = os.getenv("COSMOS_AUDIO_URL", "http://127.0.0.1:8765/transcribe")
COSMOS_VIDEO_URL = os.getenv("COSMOS_VIDEO_URL", "http://127.0.0.1:8765/analyze")
COSMOS_PROMPT_PROFILE = _current_cfg.get("cosmos_prompt_profile", "comprehensive")
# Video analysis is performed as ordered short sequences, rather than three
# unrelated still frames.  Keeping each sequence bounded protects the 2B VLM
# context while allowing longer playback clips to be processed window by window.
VIDEO_ANALYSIS_WINDOW_SECONDS = max(5.0, float(os.getenv("VIDEO_ANALYSIS_WINDOW_SECONDS", "10")))
VIDEO_ANALYSIS_MAX_FRAMES_PER_WINDOW = min(12, max(4, int(os.getenv("VIDEO_ANALYSIS_MAX_FRAMES_PER_WINDOW", "8"))))
AUDIO_ANALYSIS_BACKFILL_LIMIT = max(0, int(os.getenv("AUDIO_ANALYSIS_BACKFILL_LIMIT", "50")))
# Optional OpenAI-compatible endpoint used only to turn completed audio evidence
# into an operator-facing suggestion.  Audio transcription does not depend on it.
AUDIO_SUGGESTION_API_URL = os.getenv("AUDIO_SUGGESTION_API_URL", "").strip()
AUDIO_SUGGESTION_API_KEY = os.getenv("AUDIO_SUGGESTION_API_KEY", "").strip()
AUDIO_SUGGESTION_MODEL = os.getenv("AUDIO_SUGGESTION_MODEL", "").strip()

def get_ffmpeg_executable():
    import shutil
    env_path = os.getenv("FFMPEG_PATH")
    if env_path and os.path.exists(env_path):
        return env_path
    which_path = shutil.which("ffmpeg")
    if which_path:
        return which_path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"

FFMPEG_PATH = get_ffmpeg_executable()

def get_ffprobe_executable():
    import shutil
    return os.getenv("FFPROBE_PATH") or shutil.which("ffprobe") or "ffprobe"

FFPROBE_PATH = get_ffprobe_executable()

EVENT_CODES = [
    "All",
    "VideoMotion",
    "Intrusion",
    "CrossLine",
    "AudioAnomaly",
    "SoundDetection",
    "FaceDetection",
    "HumanTrait",
    "VehicleTrait",
    "Fight"
]

# Labels are kept next to the Dahua event-code contract so the dashboard and
# API use the same metadata behaviours.
ABNORMAL_BEHAVIOR_OPTIONS = [
    {"code": "Intrusion", "label": "Đột nhập vùng cấm"},
    {"code": "CrossLine", "label": "Vượt hàng rào / đường cảnh báo"},
    {"code": "Fight", "label": "Đánh nhau"},
    {"code": "VideoMotion", "label": "Chuyển động"},
    {"code": "AudioAnomaly", "label": "Âm thanh bất thường"},
    {"code": "SoundDetection", "label": "Phát hiện tiếng động"},
    {"code": "FaceDetection", "label": "Phát hiện khuôn mặt"},
    {"code": "HumanTrait", "label": "Phát hiện người"},
    {"code": "VehicleTrait", "label": "Phát hiện phương tiện"},
]
AUDIO_EVENT_CODES = {"AudioAnomaly", "SoundDetection", "FightSound"}

def update_global_config(new_cfg: dict):
    global NVR_HOST, USE_HTTPS, NVR_PORT, RTSP_PORT, NVR_USER, NVR_PASSWORD, ACTIVE_CHANNELS, DEMO_MODE, ABNORMAL_EVENT_CODES
    save_config(new_cfg)
    NVR_HOST = new_cfg.get("nvr_host", NVR_HOST)
    USE_HTTPS = new_cfg.get("use_https", USE_HTTPS)
    NVR_PORT = new_cfg.get("nvr_port", NVR_PORT)
    RTSP_PORT = new_cfg.get("rtsp_port", RTSP_PORT)
    NVR_USER = new_cfg.get("nvr_user", NVR_USER)
    NVR_PASSWORD = new_cfg.get("nvr_password", NVR_PASSWORD)
    ACTIVE_CHANNELS = new_cfg.get("active_channels", ACTIVE_CHANNELS)
    DEMO_MODE = new_cfg.get("demo_mode", DEMO_MODE)
    ABNORMAL_EVENT_CODES = new_cfg.get("abnormal_event_codes", ABNORMAL_EVENT_CODES)

def set_cosmos_prompt_profile(profile: str):
    global COSMOS_PROMPT_PROFILE
    cfg = load_config()
    cfg["cosmos_prompt_profile"] = profile
    save_config(cfg)
    COSMOS_PROMPT_PROFILE = profile
