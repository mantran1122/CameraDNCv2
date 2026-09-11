import os
import json
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
STORAGE_DIR = BASE_DIR / "storage"
# Keep database/config local; video evidence is saved directly to NAS.
def _detect_clips_dir() -> Path:
    env_dir = os.getenv("CAMERAAI_CLIPS_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()
    for candidate in [Path("Z:/dataCameraAI"), Path(r"\\192.168.100.3\Common\dataCameraAI")]:
        try:
            if candidate.is_dir():
                return candidate
        except Exception:
            pass
    return (STORAGE_DIR / "clips").expanduser()

CLIPS_DIR = _detect_clips_dir()
CONFIG_FILE = STORAGE_DIR / "nvr_config.json"

# Ensure directories exist
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
CLIPS_DIR.mkdir(parents=True, exist_ok=True)

# Default NVR Configuration
DEFAULT_CONFIG = {
    "nvr_host": os.getenv("NVR_HOST", "14.241.182.94"),
    "use_https": os.getenv("USE_HTTPS", "true").lower() in ("true", "1", "yes"),
    "nvr_port": int(os.getenv("NVR_PORT", "4443")),
    "rtsp_port": int(os.getenv("RTSP_PORT", "33554")),
    "nvr_user": os.getenv("NVR_USER", "user2"),
    "nvr_password": os.getenv("NVR_PASSWORD", "User#$168"),
    "active_channels": [3, 11, 18, 19, 20],
    "demo_mode": False,
    "pre_buffer_sec": 5,
    "post_buffer_sec": 5,
    "clip_ready_delay_sec": 2,
    "metadata_retention_days": 3,
    "abnormal_event_codes": [
        "Intrusion",
        "Fight",
        "AudioAnomaly",
        "CrossLine",
        "SoundDetection",
        "VideoMotion",
        "HumanTrait",
        "FaceDetection",
        "VehicleTrait"
    ],
    "camera_names": {
        "1": "1.T1. ĐÀO TẠO VÀ NCKH CAM1",
        "2": "2.T1. ĐÀO TẠO VÀ NCKH CAM2",
        "3": "3.T1. TTĐT CHUẨN ĐẦU RA CAM1",
        "4": "4.T1. TTĐT CHUẨN ĐẦU RA CAM2",
        "5": "5.T1. TVTS VÀ HƯỚNG NGHIỆP CAM1",
        "6": "6.T1. TVTS VÀ HƯỚNG NGHIỆP CAM2",
        "7": "7.T1. TÀI CHÍNH-KẾ HOẠCH CAM1",
        "8": "8.T1. TÀI CHÍNH-KẾ HOẠCH CAM2",
        "9": "9.T1. TỔ CHỨC - HÀNH CHÍNH CAM1",
        "10": "10.T1. TỔ CHỨC - HÀNH CHÍNH CAM2",
        "11": "11.T1. QUẢN LÝ HSSV",
        "12": "12.T1. QTTB",
        "13": "13.TH. KHOA KINH TẾ",
        "14": "14.HAM. KHOA CƠ BẢN",
        "15": "15.HAM. QTKQ",
        "16": "16.T1. Y TẾ",
        "17": "17.T1. PHÒNG HỌP",
        "18": "18.T1. SẢNH CAM1",
        "19": "19.T1. SẢNH CAM2",
        "20": "20.T1. SẢNH CAM3",
        "21": "21.T1. HÀNH LANG TCHC",
        "22": "22.T1. HL ĐÀO TẠO",
        "23": "23.T1. HÀNH LANG CHỦ TỊCH",
        "24": "24.T1. HÀNH LANG HIỆU TRƯỞNG",
        "25": "25",
        "26": "26",
        "27": "27",
        "28": "28",
        "29": "Channel29",
        "30": "30",
        "31": "31",
        "32": "32"
    }
}

def load_config():
    if CONFIG_FILE.exists():
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                merged = DEFAULT_CONFIG.copy()
                merged.update(data)
                # Đảm bảo các sự kiện quan trọng như HumanTrait không bị thiếu do nvr_config cũ
                if "abnormal_event_codes" in merged:
                    curr_codes = set(merged["abnormal_event_codes"])
                    if "HumanTrait" not in curr_codes:
                        merged["abnormal_event_codes"].append("HumanTrait")
                return merged
        except Exception as e:
            print(f"[Config] Error loading nvr_config.json: {e}")
    else:
        try:
            save_config(DEFAULT_CONFIG.copy())
        except Exception as e:
            print(f"[Config] Error auto-saving initial nvr_config.json: {e}")
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
CAMERA_NAMES = _current_cfg.get("camera_names", {})
DEMO_MODE = _current_cfg.get("demo_mode", False)
ABNORMAL_EVENT_CODES = _current_cfg.get("abnormal_event_codes", DEFAULT_CONFIG["abnormal_event_codes"])
PRE_BUFFER_SEC = _current_cfg.get("pre_buffer_sec", 5)
POST_BUFFER_SEC = _current_cfg.get("post_buffer_sec", 5)
CLIP_DURATION_SEC = PRE_BUFFER_SEC + POST_BUFFER_SEC
CLIP_READY_DELAY_SEC = _current_cfg.get("clip_ready_delay_sec", 2)
METADATA_RETENTION_DAYS = max(1, int(_current_cfg.get("metadata_retention_days", 3)))
# Local Edge Denoising & Legacy local models
USE_DEEPFILTER = os.getenv("USE_DEEPFILTER", "true").strip().lower() in {"1", "true", "yes", "on"}
COSMOS_AUDIO_URL = os.getenv("COSMOS_AUDIO_URL", "http://127.0.0.1:8765/transcribe")
COSMOS_AUDIO_MODEL = os.getenv("COSMOS_AUDIO_MODEL", "whisper-large-v3-turbo")
COSMOS_VIDEO_URL = os.getenv("COSMOS_VIDEO_URL", "http://127.0.0.1:8765/analyze")
COSMOS_PROMPT_PROFILE = _current_cfg.get("cosmos_prompt_profile", "comprehensive")

# Internal AI Server (4x NVIDIA H200 - Qwen3.8-27B SGLang)
QWEN_SERVER_URL = os.getenv("QWEN_SERVER_URL", "https://llm.ttpmsandbox.us.kg/v1")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "")
QWEN_MODEL_NAME = os.getenv("QWEN_MODEL_NAME", "Qwen3.8-27B")
QWEN_USER_AGENT = os.getenv(
    "QWEN_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DENSE_FRAMES_COUNT = int(os.getenv("DENSE_FRAMES_COUNT", "32"))

# Internal Audio AI Server (Speech-to-Text & Sound Anomaly Detection)
INTERNAL_AUDIO_SERVER_URL = os.getenv("INTERNAL_AUDIO_SERVER_URL", "https://llm.ttpmsandbox.us.kg/v1/audio").rstrip("/")
INTERNAL_AUDIO_SERVER_API_KEY = os.getenv("INTERNAL_AUDIO_SERVER_API_KEY", QWEN_API_KEY).strip()
INTERNAL_AUDIO_MODEL_NAME = os.getenv("INTERNAL_AUDIO_MODEL_NAME", "Internal Audio AI (Server H200)")


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
    global NVR_HOST, USE_HTTPS, NVR_PORT, RTSP_PORT, NVR_USER, NVR_PASSWORD, ACTIVE_CHANNELS, DEMO_MODE, ABNORMAL_EVENT_CODES, CAMERA_NAMES
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
    if "camera_names" in new_cfg:
        CAMERA_NAMES = new_cfg["camera_names"]

def set_cosmos_prompt_profile(profile: str):
    global COSMOS_PROMPT_PROFILE
    cfg = load_config()
    cfg["cosmos_prompt_profile"] = profile
    save_config(cfg)
    COSMOS_PROMPT_PROFILE = profile
