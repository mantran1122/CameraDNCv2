import os
import json
from pathlib import Path
from dotenv import dotenv_values

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"


def _load_env_files_safely() -> None:
    """Load .env from repo root, CameraAI/.env, and storage/.env without letting blank keys wipe out existing env vars."""
    for candidate in (BASE_DIR.parent / ".env", BASE_DIR / ".env", STORAGE_DIR / ".env"):
        try:
            if candidate.is_file():
                for key, val in dotenv_values(candidate).items():
                    if not key:
                        continue
                    cleaned = (val or "").strip()
                    if cleaned or key not in os.environ:
                        os.environ[key] = cleaned
        except Exception:
            pass


_load_env_files_safely()
# Keep database/config local; video evidence is saved directly to NAS.
def _detect_clips_dir() -> Path:
    env_dir = os.getenv("CAMERAAI_CLIPS_DIR", "").strip()
    if env_dir:
        try:
            # An explicit cache path may not exist on the first startup yet.
            path = Path(env_dir).expanduser()
            return path if path.is_absolute() else BASE_DIR / path
        except Exception:
            pass
    for candidate in [
        Path("Z:/dataCameraAI"),
        Path(r"\\192.168.100.3\Common\dataCameraAI"),
        Path("//192.168.100.3/Common/dataCameraAI"),
    ]:
        try:
            if candidate.is_dir():
                return candidate
        except Exception:
            pass
    return (STORAGE_DIR / "clips").expanduser()

CLIPS_DIR = _detect_clips_dir()
CONFIG_FILE = STORAGE_DIR / "nvr_config.json"

# Remote evidence storage. The Synology password must only be supplied through
# the process environment or the git-ignored CameraAI/.env file.
STORAGE_BACKEND = os.getenv("CAMERAAI_STORAGE_BACKEND", "local").strip().lower()
SYNOLOGY_URL = os.getenv("CAMERAAI_SYNOLOGY_URL", "").strip().rstrip("/")
SYNOLOGY_USERNAME = os.getenv("CAMERAAI_SYNOLOGY_USERNAME", "").strip()
SYNOLOGY_PASSWORD = os.getenv("CAMERAAI_SYNOLOGY_PASSWORD", "")
SYNOLOGY_SHARE = "/" + os.getenv("CAMERAAI_SYNOLOGY_SHARE", "Ai-Camera").strip().strip("/")
SYNOLOGY_ROOT = os.getenv("CAMERAAI_SYNOLOGY_ROOT", "CameraAI/clips").strip().strip("/")
SYNOLOGY_VERIFY_TLS = os.getenv("CAMERAAI_SYNOLOGY_VERIFY_TLS", "true").strip().lower() in {
    "1", "true", "yes", "on"
}
SYNOLOGY_TIMEOUT_SECONDS = max(5, int(os.getenv("CAMERAAI_SYNOLOGY_TIMEOUT_SECONDS", "60")))
# Folder names for newly captured evidence use the local operating timezone,
# rather than an event timestamp that may have been queued before midnight.
# Google SSO OAuth2 Configuration
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
GOOGLE_ADMIN_EMAILS = [e.strip().lower() for e in os.getenv("GOOGLE_ADMIN_EMAILS", "admin@nctu.edu.vn").split(",") if e.strip()]

# Ensure directories exist
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
try:
    CLIPS_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass


def _load_session_secret() -> str:
    configured = os.getenv("CAMERAAI_SESSION_SECRET", "").strip()
    if configured:
        return configured
    secret_file = STORAGE_DIR / "session_secret.key"
    try:
        if secret_file.is_file():
            value = secret_file.read_text(encoding="utf-8").strip()
            if value:
                return value
        import secrets
        value = secrets.token_urlsafe(48)
        secret_file.write_text(value, encoding="utf-8")
        return value
    except Exception:
        import secrets
        return secrets.token_urlsafe(48)


SESSION_SECRET = _load_session_secret()
SESSION_MAX_AGE_SECONDS = max(300, int(os.getenv("CAMERAAI_SESSION_MAX_AGE_SECONDS", "28800")))
SESSION_COOKIE_SECURE = os.getenv("CAMERAAI_SESSION_COOKIE_SECURE", "false").strip().lower() in {
    "1", "true", "yes", "on"
}

# Default NVR Configuration
DEFAULT_CONFIG = {
    "nvr_host": os.getenv("NVR_HOST", "14.241.182.94"),
    "use_https": os.getenv("USE_HTTPS", "true").lower() in ("true", "1", "yes"),
    "nvr_port": int(os.getenv("NVR_PORT", "4443")),
    "rtsp_port": int(os.getenv("RTSP_PORT", "33554")),
    "nvr_user": os.getenv("NVR_USER", "user2"),
    "nvr_password": os.getenv("NVR_PASSWORD", "User#$168"),
    "active_channels": list(range(1, 33)),
    "demo_mode": False,
    "pre_buffer_sec": 5,
    "post_buffer_sec": 5,
    "clip_ready_delay_sec": 2,
    "metadata_retention_days": int(os.getenv("CAMERAAI_RETENTION_DAYS", "30")),
    "abnormal_event_codes": [
        "Intrusion",
        "Fight",
        "AudioMutation",
        "CrossLine",
        "SoundDetection",
        "RtspSessionDisconnect",
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
_raw_rtsp_port = int(_current_cfg.get("rtsp_port", 33554) or 33554)
RTSP_PORT = 33554 if _raw_rtsp_port in (36677, 37777, 8080, 4443) else _raw_rtsp_port
NVR_USER = _current_cfg.get("nvr_user", os.getenv("NVR_USER", ""))
NVR_PASSWORD = _current_cfg.get("nvr_password", os.getenv("NVR_PASSWORD", ""))
ACTIVE_CHANNELS = _current_cfg.get("active_channels", list(range(1, 33)))
CAMERA_NAMES = _current_cfg.get("camera_names", {})
DEMO_MODE = _current_cfg.get("demo_mode", False)
ABNORMAL_EVENT_CODES = _current_cfg.get("abnormal_event_codes", DEFAULT_CONFIG["abnormal_event_codes"])
CRITICAL_ANOMALY_CODES = [
    "Intrusion",
    "Fight",
    "CrossLine",
    "AudioMutation",
    "SoundDetection",
    "RtspSessionDisconnect",
]
ROUTINE_EVENT_CODES = [
    "VideoMotion",
    "HumanTrait",
    "FaceDetection",
    "VehicleTrait",
]
CAMERA_ALERT_RULES = _current_cfg.get("camera_alert_rules", {})

def is_channel_anomaly(channel: int, event_code: str) -> bool:
    """Determine if an event is considered a high/medium anomaly for a specific channel.
    If specific rules are defined for the camera, use them authoritatively;
    otherwise fallback to ABNORMAL_EVENT_CODES and CRITICAL_ANOMALY_CODES.
    """
    ch_key = str(channel)
    if ch_key in CAMERA_ALERT_RULES and isinstance(CAMERA_ALERT_RULES[ch_key], list):
        rules = CAMERA_ALERT_RULES[ch_key]
        if event_code in rules:
            return True
        if event_code == "SmartMotionHuman" and "HumanTrait" in rules:
            return True
        if event_code in ("SoundDetection", "AudioAnomaly") and "AudioMutation" in rules:
            return True
        return False
    return event_code in ABNORMAL_EVENT_CODES or event_code in CRITICAL_ANOMALY_CODES

PRE_BUFFER_SEC = _current_cfg.get("pre_buffer_sec", 5)
POST_BUFFER_SEC = _current_cfg.get("post_buffer_sec", 5)
CLIP_DURATION_SEC = PRE_BUFFER_SEC + POST_BUFFER_SEC
CLIP_READY_DELAY_SEC = _current_cfg.get("clip_ready_delay_sec", 2)
RETENTION_DAYS = max(1, int(os.getenv("CAMERAAI_RETENTION_DAYS", str(_current_cfg.get("metadata_retention_days", 30)))))
METADATA_RETENTION_DAYS = RETENTION_DAYS
# Local Edge Denoising & Legacy local models
USE_DEEPFILTER = os.getenv("USE_DEEPFILTER", "true").strip().lower() in {"1", "true", "yes", "on"}
COSMOS_AUDIO_URL = os.getenv("COSMOS_AUDIO_URL", "http://127.0.0.1:8765/transcribe")
COSMOS_AUDIO_MODEL = os.getenv("COSMOS_AUDIO_MODEL", "whisper-large-v3-turbo")
COSMOS_VIDEO_URL = os.getenv("COSMOS_VIDEO_URL", "http://127.0.0.1:8765/analyze")
COSMOS_PROMPT_PROFILE = _current_cfg.get("cosmos_prompt_profile", "comprehensive")

# Internal AI Server (API key must only be provided via git-ignored .env or storage/nvr_config.json)
QWEN_SERVER_URL = os.getenv("QWEN_SERVER_URL", "").strip() or _current_cfg.get("qwen_server_url", "https://llm.ttpmsandbox.us.kg/v1")
QWEN_API_KEY = os.getenv("QWEN_API_KEY", "").strip() or _current_cfg.get("qwen_api_key", "")
_env_qwen_model = os.getenv("QWEN_MODEL_NAME", "").strip() or _current_cfg.get("qwen_model_name", "")
QWEN_MODEL_NAME = "GLM-5.3-Flash" if (not _env_qwen_model or _env_qwen_model == "Qwen3.8-27B") else _env_qwen_model
QWEN_USER_AGENT = os.getenv(
    "QWEN_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
DENSE_FRAMES_COUNT = int(os.getenv("DENSE_FRAMES_COUNT", "8"))
MAX_VLM_FRAMES = int(os.getenv("MAX_VLM_FRAMES", "8"))

# Internal Audio AI Server (Speech-to-Text & Sound Anomaly Detection)
INTERNAL_AUDIO_SERVER_URL = (os.getenv("INTERNAL_AUDIO_SERVER_URL", "").strip() or "https://llm.ttpmsandbox.us.kg/v1/audio").rstrip("/")
INTERNAL_AUDIO_SERVER_API_KEY = os.getenv("INTERNAL_AUDIO_SERVER_API_KEY", "").strip() or QWEN_API_KEY
INTERNAL_AUDIO_MODEL_NAME = os.getenv("INTERNAL_AUDIO_MODEL_NAME", "").strip() or "Internal Audio AI (Server AI)"


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
    {"code": "AudioMutation", "label": "Âm thanh đột biến / La hét"},
    {"code": "AudioAnomaly", "label": "Âm thanh bất thường"},
    {"code": "SoundDetection", "label": "Phát hiện tiếng động"},
    {"code": "FaceDetection", "label": "Phát hiện khuôn mặt"},
    {"code": "HumanTrait", "label": "Phát hiện người"},
    {"code": "VehicleTrait", "label": "Phát hiện phương tiện"},
    {"code": "RtspSessionDisconnect", "label": "Mất kết nối luồng RTSP"},
]
AUDIO_EVENT_CODES = {"AudioAnomaly", "SoundDetection", "FightSound", "AudioMutation"}

def update_global_config(new_cfg: dict):
    global NVR_HOST, USE_HTTPS, NVR_PORT, RTSP_PORT, NVR_USER, NVR_PASSWORD, ACTIVE_CHANNELS, DEMO_MODE, ABNORMAL_EVENT_CODES, CAMERA_NAMES, CAMERA_ALERT_RULES
    raw_rtsp = int(new_cfg.get("rtsp_port", RTSP_PORT) or 33554)
    if raw_rtsp in (36677, 37777, 8080, 4443):
        new_cfg["rtsp_port"] = 33554

    # Load existing config to merge safely without dropping other settings or password
    existing_cfg = load_config()

    # Password preservation: only overwrite if a non-empty password was explicitly provided
    candidate_pw = str(new_cfg.get("nvr_password") or "").strip()
    if candidate_pw:
        NVR_PASSWORD = candidate_pw
        new_cfg["nvr_password"] = candidate_pw
    else:
        # Retain existing password in both file and memory
        new_cfg["nvr_password"] = existing_cfg.get("nvr_password") or NVR_PASSWORD

    # Preserve camera_names and camera_alert_rules if not explicitly provided
    if new_cfg.get("camera_names") is not None:
        CAMERA_NAMES = new_cfg["camera_names"]
    else:
        CAMERA_NAMES = existing_cfg.get("camera_names") or DEFAULT_CONFIG.get("camera_names") or {}
        new_cfg["camera_names"] = CAMERA_NAMES

    if new_cfg.get("camera_alert_rules") is not None:
        CAMERA_ALERT_RULES = new_cfg["camera_alert_rules"]
    else:
        CAMERA_ALERT_RULES = existing_cfg.get("camera_alert_rules") or {}
        new_cfg["camera_alert_rules"] = CAMERA_ALERT_RULES

    existing_cfg.update(new_cfg)
    save_config(existing_cfg)

    NVR_HOST = existing_cfg.get("nvr_host", NVR_HOST)
    USE_HTTPS = existing_cfg.get("use_https", USE_HTTPS)
    NVR_PORT = existing_cfg.get("nvr_port", NVR_PORT)
    RTSP_PORT = existing_cfg.get("rtsp_port", RTSP_PORT)
    NVR_USER = existing_cfg.get("nvr_user", NVR_USER)
    ACTIVE_CHANNELS = existing_cfg.get("active_channels", ACTIVE_CHANNELS)
    DEMO_MODE = existing_cfg.get("demo_mode", DEMO_MODE)
    ABNORMAL_EVENT_CODES = existing_cfg.get("abnormal_event_codes", ABNORMAL_EVENT_CODES)
    CAMERA_NAMES = existing_cfg.get("camera_names") or DEFAULT_CONFIG.get("camera_names") or {}
    CAMERA_ALERT_RULES = existing_cfg.get("camera_alert_rules") or {}

def set_cosmos_prompt_profile(profile: str):
    global COSMOS_PROMPT_PROFILE
    cfg = load_config()
    cfg["cosmos_prompt_profile"] = profile
    save_config(cfg)
    COSMOS_PROMPT_PROFILE = profile


# Nightly 22:00 -> 04:00 Automated Video Analysis & Daily Camera Reports
NIGHTLY_REPORT_DIR = STORAGE_DIR / "nightly_reports"
NIGHTLY_START_HOUR = int(os.getenv("CAMERAAI_NIGHTLY_START_HOUR", "22"))
NIGHTLY_END_HOUR = int(os.getenv("CAMERAAI_NIGHTLY_END_HOUR", "4"))
NIGHTLY_CUTOFF_HOUR = int(os.getenv("CAMERAAI_NIGHTLY_CUTOFF_HOUR", "22"))
try:
    NIGHTLY_REPORT_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

