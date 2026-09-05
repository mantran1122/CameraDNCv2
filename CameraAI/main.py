import os
import json
import asyncio
import threading
import secrets
import uuid
import re
from pathlib import Path
from urllib.parse import quote
from typing import List, Optional
from datetime import date, datetime
import requests
from requests.auth import HTTPDigestAuth

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Query, BackgroundTasks, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import config
import database
import summary_engine
import video_clipper
import data_health
from clip_storage import resolve_clip_path
from audio_analysis_worker import AudioAnalysisWorker
from video_analysis_worker import VideoAnalysisWorker
from gemini_video_report import (
    generate_final_video_report,
    get_gemini_public_config,
    save_gemini_local_config,
)
from clip_capture_worker import ClipCaptureWorker
from postgres_sync import enabled as postgres_dual_write_enabled
from dahua_client import DahuaNVRListener
from simulator import NVRDataSimulator

import cv2
import numpy as np
import time

app = FastAPI(
    title="Dahua DHI-NVR5832-EI2 Internet AI Metadata & Anomaly Summarizer",
    description="Hệ thống Phân tích Metadata & Tóm tắt Hoạt động Ngày (Video + Audio) Kết nối Đầu ghi qua Internet/WAN/DDNS",
    version="2.0.0"
)

static_dir = config.BASE_DIR / "static"
templates_dir = config.BASE_DIR / "templates"
static_dir.mkdir(exist_ok=True)
templates_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.mount("/clips", StaticFiles(directory=str(config.CLIPS_DIR)), name="clips")

templates = Jinja2Templates(directory=str(templates_dir))
admin_security = HTTPBasic(auto_error=False)


def require_database_admin(credentials: Optional[HTTPBasicCredentials] = Depends(admin_security)):
    """Protect the database viewer with credentials kept outside source code."""
    expected_user = os.getenv("ADMIN_DATABASE_USERNAME", "")
    expected_password = os.getenv("ADMIN_DATABASE_PASSWORD", "")
    if not expected_user or not expected_password:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Trang quản trị DB chưa được bật. Hãy cấu hình ADMIN_DATABASE_USERNAME và ADMIN_DATABASE_PASSWORD.",
        )
    is_valid = (
        credentials is not None
        and secrets.compare_digest(credentials.username, expected_user)
        and secrets.compare_digest(credentials.password, expected_password)
    )
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Cần xác thực quản trị viên.",
            headers={"WWW-Authenticate": 'Basic realm="Database Administration"'},
        )
    return credentials.username

class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)

manager = ConnectionManager()

nvr_listener = None
simulator_thread = None
audio_analysis_worker = None
video_analysis_worker = None
clip_capture_worker = None
metadata_cleanup_stop = threading.Event()
metadata_cleanup_thread = None
postgres_sync_stop = threading.Event()
postgres_sync_thread = None
# The FastAPI/Uvicorn event loop belongs to the server thread. Listener and
# simulator threads use this stored reference to schedule WebSocket broadcasts.
server_event_loop: Optional[asyncio.AbstractEventLoop] = None

def broadcast_event_sync(event_obj: dict):
    loop = server_event_loop
    if loop is None or not loop.is_running():
        # This is expected while the application is starting or stopping.
        return

    try:
        asyncio.run_coroutine_threadsafe(manager.broadcast(event_obj), loop)
    except Exception as e:
        print(f"[WebSocket Broadcast Error] {e}")

def restart_listener_service():
    global nvr_listener, simulator_thread, audio_analysis_worker, video_analysis_worker, clip_capture_worker
    if nvr_listener:
        nvr_listener.stop()
    if simulator_thread:
        simulator_thread.stop()
    if audio_analysis_worker:
        audio_analysis_worker.stop()
    if video_analysis_worker:
        video_analysis_worker.stop()
    if clip_capture_worker:
        clip_capture_worker.stop()

    nvr_listener = None
    simulator_thread = None
    audio_analysis_worker = AudioAnalysisWorker(on_updated=broadcast_audio_analysis_update)
    audio_analysis_worker.start()
    video_analysis_worker = VideoAnalysisWorker(on_updated=broadcast_audio_analysis_update)
    video_analysis_worker.start()
    clip_capture_worker = ClipCaptureWorker(on_updated=broadcast_audio_analysis_update)
    clip_capture_worker.start()

    # Demo data must never be created while connected to a production NVR.
    if config.DEMO_MODE:
        simulator_thread = NVRDataSimulator(
            broadcast_callback=broadcast_event_sync,
            audio_job_callback=clip_capture_worker.enqueue,
        )
        simulator_thread.start()

    nvr_listener = DahuaNVRListener(
        broadcast_callback=broadcast_event_sync,
        audio_job_callback=clip_capture_worker.enqueue,
    )
    nvr_listener.start()

@app.on_event("startup")
async def startup_event():
    global server_event_loop, metadata_cleanup_thread, postgres_sync_thread
    server_event_loop = asyncio.get_running_loop()
    database.init_db()
    metadata_cleanup_stop.clear()
    metadata_cleanup_thread = threading.Thread(target=metadata_cleanup_loop, daemon=True, name="metadata-cleanup-worker")
    metadata_cleanup_thread.start()
    if postgres_dual_write_enabled():
        postgres_sync_stop.clear()
        postgres_sync_thread = threading.Thread(target=postgres_sync_loop, daemon=True, name="postgres-sync-worker")
        postgres_sync_thread.start()
        print("[PostgreSQL Sync] Dual-write enabled; SQLite remains the read source.")
    restart_listener_service()
    print("[Server Startup] Dahua Internet Metadata & Anomaly Summarizer online.")

@app.on_event("shutdown")
async def shutdown_event():
    global nvr_listener, simulator_thread, audio_analysis_worker, video_analysis_worker, clip_capture_worker, metadata_cleanup_thread, postgres_sync_thread, server_event_loop
    if nvr_listener:
        nvr_listener.stop()
    if simulator_thread:
        simulator_thread.stop()
    if audio_analysis_worker:
        audio_analysis_worker.stop()
    if video_analysis_worker:
        video_analysis_worker.stop()
    if clip_capture_worker:
        clip_capture_worker.stop()
    metadata_cleanup_stop.set()
    postgres_sync_stop.set()
    if metadata_cleanup_thread:
        metadata_cleanup_thread.join(timeout=2)
        metadata_cleanup_thread = None
    if postgres_sync_thread:
        postgres_sync_thread.join(timeout=2)
        postgres_sync_thread = None
    server_event_loop = None


def broadcast_audio_analysis_update(event_id: int):
    event = database.get_event_by_id(event_id)
    if event:
        event["audio_analysis"] = database.get_audio_analysis(event_id)
        event["video_analysis"] = database.get_video_analysis(event_id)
        broadcast_event_sync(event)

def purge_expired_metadata() -> None:
    filenames = database.delete_expired_events(config.METADATA_RETENTION_DAYS)
    removed_clips = 0
    for filename in filenames:
        clip_path = resolve_clip_path(filename)
        try:
            if clip_path.is_file():
                clip_path.unlink()
                removed_clips += 1
        except OSError as exc:
            print(f"[Cleanup] Could not remove expired clip {clip_path.name}: {exc}")
    if filenames:
        print(f"[Cleanup] Removed {len(filenames)} expired events and {removed_clips} clips (retention={config.METADATA_RETENTION_DAYS} days).")

def metadata_cleanup_loop() -> None:
    while not metadata_cleanup_stop.is_set():
        purge_expired_metadata()
        metadata_cleanup_stop.wait(6 * 60 * 60)

def postgres_sync_loop() -> None:
    while not postgres_sync_stop.is_set():
        result = database.sync_postgres_outbox(limit=100)
        if result.get("failed"):
            print(f"[PostgreSQL Sync] Pending retry: {result}")
        postgres_sync_stop.wait(30)

# --- ROUTES & APIS ---

@app.get("/", response_class=HTMLResponse)
async def read_index(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/admin/database", response_class=HTMLResponse)
async def database_admin_page(request: Request, _: str = Depends(require_database_admin)):
    return templates.TemplateResponse(request=request, name="admin_database.html")


@app.get("/api/admin/database")
async def database_admin_api(
    limit: int = Query(default=20, ge=1, le=100),
    _: str = Depends(require_database_admin),
):
    return database.get_database_overview(sample_limit=limit)

@app.get("/admin/data-health", response_class=HTMLResponse)
async def data_health_page(request: Request, _: str = Depends(require_database_admin)):
    return templates.TemplateResponse(request=request, name="admin_data_health.html")

@app.get("/api/admin/data-health")
async def data_health_api(refresh: bool = False, _: str = Depends(require_database_admin)):
    return data_health.get_data_health(force=refresh)

@app.get("/test-ai", response_class=HTMLResponse)
async def test_ai_page(request: Request, _: str = Depends(require_database_admin)):
    return templates.TemplateResponse(request=request, name="test_ai.html")

@app.post("/api/admin/test-videos/upload")
async def upload_test_video(video: UploadFile = File(...), _: str = Depends(require_database_admin)):
    """Store an operator-selected test video separately from camera evidence."""
    original_name = video.filename or "video.mp4"
    suffix = os.path.splitext(original_name)[1].lower()
    allowed_suffixes = {".mp4", ".mov", ".mkv", ".avi", ".webm"}
    if suffix not in allowed_suffixes:
        raise HTTPException(status_code=415, detail="Chỉ nhận MP4, MOV, MKV, AVI hoặc WEBM.")
    max_bytes = max(1, int(os.getenv("CAMERAAI_MANUAL_TEST_MAX_UPLOAD_MB", "2048"))) * 1024 * 1024
    now = datetime.now()
    reference = f"manual-tests/{now:%Y}/{now:%m}/{now:%d}/test_{now:%Y%m%dT%H%M%S}_{uuid.uuid4().hex[:12]}{suffix}"
    target = resolve_clip_path(reference)
    target.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with target.open("wb") as output:
            while chunk := await video.read(1024 * 1024):
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(status_code=413, detail=f"Video vượt giới hạn {max_bytes // 1024 // 1024} MB.")
                output.write(chunk)
    except Exception:
        if target.exists():
            target.unlink()
        raise
    finally:
        await video.close()
    event_id = database.save_event(
        event_code="ManualTest", event_type="video_anomaly", channel=1,
        timestamp=now.strftime("%Y-%m-%d %H:%M:%S"),
        description=f"Manual AI test: {os.path.basename(original_name)}", severity="info",
        metadata_dict={"source": "manual_upload", "original_filename": os.path.basename(original_name), "size_bytes": written},
        clip_filename=reference,
    )
    return {"event": database.get_event_by_id(event_id)}

@app.get("/api/events")
async def get_events_api(
    event_type: Optional[str] = None,
    channel: Optional[int] = None,
    only_anomalies: bool = False,
    limit: int = 50
):
    events = database.get_events(
        event_type=event_type,
        channel=channel,
        limit=limit,
        only_anomalies=only_anomalies
    )
    for event in events:
        event["audio_analysis"] = database.get_audio_analysis(event["id"])
        event["video_analysis"] = database.get_video_analysis(event["id"])
    return {"events": events, "count": len(events)}

@app.get("/api/events/{event_id}")
async def get_event_detail(event_id: int):
    ev = database.get_event_by_id(event_id)
    if not ev:
        return JSONResponse(status_code=404, content={"error": "Event not found"})
    ev["audio_analysis"] = database.get_audio_analysis(event_id)
    ev["video_analysis"] = database.get_video_analysis(event_id)
    return ev

@app.post("/api/events/{event_id}/audio-analysis")
async def request_audio_analysis(event_id: int):
    """Queue speech-to-text for the anomaly clip selected by an operator."""
    event = database.get_event_by_id(event_id)
    if not event:
        return JSONResponse(status_code=404, content={"error": "Event not found"})
    if event["event_type"] not in {"audio_anomaly", "video_anomaly"}:
        return JSONResponse(status_code=400, content={"error": "Chỉ sự kiện bất thường mới có thể phân tích âm thanh."})
    if not event.get("clip_filename"):
        database.create_audio_analysis(event_id, status="video_missing")
        database.update_audio_analysis(event_id, status="video_missing", error_message="Không tìm thấy video evidence của cảnh báo.")
        broadcast_audio_analysis_update(event_id)
        return JSONResponse(status_code=409, content={"error": "Không tìm thấy video evidence của cảnh báo."})
    clip_path = resolve_clip_path(str(event["clip_filename"]))
    if not clip_path.is_file():
        database.update_audio_analysis(event_id, status="video_missing", error_message="File video evidence không còn trên máy chủ.")
        broadcast_audio_analysis_update(event_id)
        return JSONResponse(status_code=409, content={"error": "Không tìm thấy file video evidence."})
    if audio_analysis_worker is None:
        return JSONResponse(status_code=503, content={"error": "Audio worker chưa sẵn sàng."})

    analysis = database.get_audio_analysis(event_id)
    active_statuses = {"processing", "extracting_audio", "transcribing", "analyzing"}
    if analysis and analysis["status"] in active_statuses | {"completed"}:
        return {"queued": False, "audio_analysis": analysis}

    if analysis is None:
        database.create_audio_analysis(event_id, status="not_analyzed")
    database.update_audio_analysis(event_id, status="processing", error_message=None)
    analysis = database.get_audio_analysis(event_id)
    broadcast_audio_analysis_update(event_id)
    print(f"[AUDIO] alert={event_id} queued by API")
    audio_analysis_worker.enqueue(event_id)
    return {"queued": True, "audio_analysis": analysis}


class VideoAnalysisOptions(BaseModel):
    max_frames_per_window: Optional[int] = None


@app.post("/api/events/{event_id}/video-analysis")
async def request_video_analysis(event_id: int, options: Optional[VideoAnalysisOptions] = None):
    """Queue manual visual analysis of representative frames from an event clip."""
    event = database.get_event_by_id(event_id)
    if not event:
        return JSONResponse(status_code=404, content={"error": "Event not found"})
    if event["event_type"] not in {"audio_anomaly", "video_anomaly"}:
        return JSONResponse(status_code=400, content={"error": "Chỉ sự kiện bất thường mới có thể phân tích video."})
    if not event.get("clip_filename"):
        database.create_video_analysis(event_id, status="video_missing")
        database.update_video_analysis(event_id, status="video_missing", error_message="Không tìm thấy video evidence của cảnh báo.")
        broadcast_audio_analysis_update(event_id)
        return JSONResponse(status_code=409, content={"error": "Không tìm thấy video evidence của cảnh báo."})
    clip_path = resolve_clip_path(str(event["clip_filename"]))
    if not clip_path.is_file():
        database.create_video_analysis(event_id, status="video_missing")
        database.update_video_analysis(event_id, status="video_missing", error_message="File video evidence không còn trên máy chủ.")
        broadcast_audio_analysis_update(event_id)
        return JSONResponse(status_code=409, content={"error": "Không tìm thấy file video evidence."})
    if video_analysis_worker is None:
        return JSONResponse(status_code=503, content={"error": "Video worker chưa sẵn sàng."})

    analysis = database.get_video_analysis(event_id)
    active_statuses = {"processing", "extracting_frames", "analyzing_frames", "analyzing_sequences"}
    if analysis and analysis["status"] in active_statuses | {"completed"}:
        return {"queued": False, "video_analysis": analysis}
    if analysis is None:
        database.create_video_analysis(event_id, status="not_analyzed")
    database.update_video_analysis(event_id, status="processing", error_message=None)
    analysis = database.get_video_analysis(event_id)
    broadcast_audio_analysis_update(event_id)
    max_frames = options.max_frames_per_window if options else None
    if max_frames is not None and not 4 <= max_frames <= 12:
        raise HTTPException(status_code=422, detail="Số frame mỗi cửa sổ phải từ 4 đến 12.")
    print(f"[VIDEO AI] alert={event_id} queued by API frames/window={max_frames or 'default'}")
    video_analysis_worker.enqueue(event_id, max_frames_per_window=max_frames)
    return {"queued": True, "video_analysis": analysis}


@app.post("/api/events/{event_id}/llm-analysis")
async def request_llm_analysis(event_id: int, _: str = Depends(require_database_admin)):
    """Combine saved Cosmos and PhoWhisper evidence into one Gemini report."""
    event = database.get_event_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện.")
    if not get_gemini_public_config()["configured"]:
        raise HTTPException(status_code=409, detail="Chưa cấu hình Gemini ở đầu trang Kiểm thử AI.")

    video_analysis = database.get_video_analysis(event_id)
    audio_analysis = database.get_audio_analysis(event_id)
    windows = video_analysis.get("frames", []) if video_analysis else []
    transcript = str((audio_analysis or {}).get("transcript") or "").strip()
    if not windows and not transcript:
        raise HTTPException(status_code=409, detail="Hãy phân tích hình ảnh hoặc âm thanh trước khi gọi Gemini.")

    report, model = await asyncio.to_thread(
        generate_final_video_report, event, windows, audio_analysis
    )
    if not report:
        raise HTTPException(
            status_code=502,
            detail="Gemini không tạo được kết luận. Kiểm tra API key, model và kết nối Internet.",
        )
    if audio_analysis is None:
        database.create_audio_analysis(event_id, status="not_analyzed")
    database.update_audio_analysis(event_id, suggestion=report)
    broadcast_audio_analysis_update(event_id)
    return {"status": "completed", "model": model, "suggestion": report}

@app.get("/api/summary/daily")
async def get_daily_summary_api(date_str: Optional[str] = None):
    summary = summary_engine.generate_daily_summary(date_str)
    return summary

def generate_frames(channel: int):
    rtsp_user = quote(str(config.NVR_USER), safe="")
    rtsp_password = quote(str(config.NVR_PASSWORD), safe="")
    rtsp_url = f"rtsp://{rtsp_user}:{rtsp_password}@{config.NVR_HOST}:{config.RTSP_PORT}/cam/realmonitor?channel={channel}&subtype=1"
    
    if config.DEMO_MODE:
        cap = None
    else:
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
    
    while True:
        if config.DEMO_MODE:
            frame = np.full((360, 640, 3), (20, 24, 33), dtype=np.uint8)
            cv2.putText(frame, f"LIVE CAM {channel:02d} (DEMO MODE)", (50, 180), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            cv2.putText(frame, f"NVR: {config.NVR_HOST}:{config.RTSP_PORT}", (50, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 200), 2)
            if int(time.time() * 2) % 2 == 0:
                cv2.circle(frame, (600, 30), 10, (0, 0, 255), -1)
            ret = True
            time.sleep(0.1)
        else:
            if cap is None or not cap.isOpened():
                break
            ret, frame = cap.read()
            if not ret:
                break
            
        ret, buffer = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 80])
        frame_bytes = buffer.tobytes()
        yield (b'--frame\r\n'
               b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
               
    if cap is not None:
        cap.release()

@app.get("/api/stream/live/{channel}")
async def live_stream(channel: int):
    return StreamingResponse(generate_frames(channel), media_type="multipart/x-mixed-replace; boundary=frame")

class NVRConfigModel(BaseModel):
    nvr_host: str
    use_https: bool = False
    nvr_port: int = 80
    rtsp_port: int = 554
    nvr_user: str = "admin"
    nvr_password: str
    active_channels: List[int] = list(range(1, 33))
    demo_mode: bool = False
    abnormal_event_codes: List[str] = []

class CosmosPromptProfileModel(BaseModel):
    profile: str


class GeminiConfigModel(BaseModel):
    api_key: str
    model: str = "gemini-2.0-flash"

COSMOS_PROMPT_PROFILES = {"generic", "comprehensive", "security", "safety", "traffic", "classroom", "crowd_operations", "student_affairs", "admissions"}
COSMOS_HIDDEN_PROMPT_PROFILES = {"live_admissions_prompt"}  # legacy template, not a selectable profile
COSMOS_PROMPT_PROFILES_DIR = Path(os.getenv(
    "CAMERAAI_COSMOS_PROMPTS_DIR",
    str(config.BASE_DIR.parent / "cosmos_code_base" / "prompts" / "profiles"),
))


def _is_valid_cosmos_profile_name(profile: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", profile))


def _available_cosmos_prompt_profiles() -> list[str]:
    profiles = set(COSMOS_PROMPT_PROFILES)
    if COSMOS_PROMPT_PROFILES_DIR.is_dir():
        profiles.update(
            path.stem.lower()
            for path in COSMOS_PROMPT_PROFILES_DIR.glob("*.txt")
            if _is_valid_cosmos_profile_name(path.stem.lower()) and path.stem.lower() not in COSMOS_HIDDEN_PROMPT_PROFILES
        )
    return sorted(profiles)


def _cosmos_prompt_file(profile: str) -> Path:
    if not _is_valid_cosmos_profile_name(profile):
        raise HTTPException(status_code=422, detail="Tên prompt không hợp lệ.")
    return COSMOS_PROMPT_PROFILES_DIR / f"{profile}.txt"

@app.get("/api/config/nvr")
async def get_nvr_config():
    return {
        "nvr_host": config.NVR_HOST,
        "use_https": config.USE_HTTPS,
        "nvr_port": config.NVR_PORT,
        "rtsp_port": config.RTSP_PORT,
        "nvr_user": config.NVR_USER,
        "active_channels": config.ACTIVE_CHANNELS,
        "demo_mode": config.DEMO_MODE,
        "abnormal_event_codes": config.ABNORMAL_EVENT_CODES,
        "abnormal_behavior_options": config.ABNORMAL_BEHAVIOR_OPTIONS,
        "ffmpeg_available": True
    }

@app.get("/api/admin/cosmos/prompt-profile")
async def get_cosmos_prompt_profile(_: str = Depends(require_database_admin)):
    return {"selected": config.COSMOS_PROMPT_PROFILE, "profiles": _available_cosmos_prompt_profiles()}


@app.get("/api/admin/gemini-config")
async def get_gemini_config(_: str = Depends(require_database_admin)):
    """Expose status only; never send the saved API key back to the browser."""
    return get_gemini_public_config()


@app.post("/api/admin/gemini-config")
async def set_gemini_config(payload: GeminiConfigModel, _: str = Depends(require_database_admin)):
    try:
        result = save_gemini_local_config(payload.api_key, payload.model)
    except (OSError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {**result, "message": "Đã lưu cấu hình Gemini cục bộ; có hiệu lực ngay."}

@app.post("/api/admin/cosmos/prompt-profile")
async def set_cosmos_prompt_profile(payload: CosmosPromptProfileModel, _: str = Depends(require_database_admin)):
    profile = payload.profile.strip().lower()
    if profile not in _available_cosmos_prompt_profiles():
        raise HTTPException(status_code=422, detail="Prompt profile không được hỗ trợ.")
    config.set_cosmos_prompt_profile(profile)
    return {"selected": profile, "message": "Profile đã lưu; áp dụng cho lần phân tích video kế tiếp."}


@app.get("/api/admin/cosmos/prompt-profiles/{profile}")
async def get_cosmos_prompt_text(profile: str, _: str = Depends(require_database_admin)):
    profile = profile.strip().lower()
    path = _cosmos_prompt_file(profile)
    if path.is_file():
        return {"profile": profile, "source": str(path), "text": path.read_text(encoding="utf-8")}
    if profile == "generic":
        return {"profile": profile, "source": "built-in", "text": "Prompt giám sát cơ bản tích hợp trong Cosmos (không có file profile riêng)."}
    raise HTTPException(status_code=404, detail="Không tìm thấy file prompt.")


@app.post("/api/admin/cosmos/prompt-profiles/upload")
async def upload_cosmos_prompt_profile(prompt_file: UploadFile = File(...), _: str = Depends(require_database_admin)):
    """Store an operator-created profile beside the deployed Cosmos profiles.

    Only `custom_*.txt` can be written so a web upload cannot overwrite a
    tracked built-in profile.  These files are ignored by Git and remain local.
    """
    original_name = prompt_file.filename or ""
    if Path(original_name).suffix.lower() != ".txt":
        raise HTTPException(status_code=422, detail="Chỉ nhận file prompt .txt.")
    stem = re.sub(r"[^a-z0-9_-]+", "_", Path(original_name).stem.lower()).strip("_-")
    if not stem:
        raise HTTPException(status_code=422, detail="Tên file prompt không hợp lệ.")
    profile = f"custom_{stem}"[:64]
    try:
        raw = await prompt_file.read(50_001)
        if len(raw) > 50_000:
            raise ValueError("Prompt vượt giới hạn 50 KB.")
        text = raw.decode("utf-8").strip()
        if not text:
            raise ValueError("File prompt đang trống.")
        COSMOS_PROMPT_PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        path = _cosmos_prompt_file(profile)
        path.write_text(text + "\n", encoding="utf-8")
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Không thể lưu prompt: {exc}") from exc
    return {"profile": profile, "text": text, "message": "Đã tải prompt lên. Chọn và lưu để dùng mặc định."}

@app.post("/api/config/nvr/test")
async def test_nvr_connection(cfg: NVRConfigModel):
    """
    Tests connection to Dahua NVR over Internet / DDNS / WAN using CGI device info API.
    """
    if cfg.demo_mode:
        return {
            "success": True,
            "demo": True,
            "device_model": "DHI-NVR5832-EI2 (Chế độ Giả lập)",
            "serial_number": "7G098234910293",
            "firmware": "v4.002.0000000.1.R",
            "message": "✅ Chế độ Giả lập (Demo Mode) đang hoạt động hoàn hảo!"
        }

    protocol = "https" if cfg.use_https else "http"
    url = f"{protocol}://{cfg.nvr_host}:{cfg.nvr_port}/cgi-bin/devInfo.cgi?action=getDeviceInfo"
    auth = HTTPDigestAuth(cfg.nvr_user, cfg.nvr_password)

    try:
        res = requests.get(url, auth=auth, timeout=8, verify=False)
        if res.status_code == 200:
            lines = res.text.splitlines()
            info_dict = {}
            for line in lines:
                if "=" in line:
                    k, v = line.split("=", 1)
                    info_dict[k.strip()] = v.strip()

            device_type = info_dict.get("deviceType", "Dahua NVR")
            serial_no = info_dict.get("serialNumber", "N/A")
            firmware_ver = info_dict.get("softwareVersion", "N/A")

            return {
                "success": True,
                "demo": False,
                "device_model": device_type,
                "serial_number": serial_no,
                "firmware": firmware_ver,
                "message": f"✅ KẾT NỐI THÀNH CÔNG TỚI ĐẦU GHI {device_type}! (S/N: {serial_no})"
            }
        elif res.status_code in [401, 403]:
            return {
                "success": False,
                "message": f"❌ Lỗi Xác thực ({res.status_code}): Sai Tên đăng nhập hoặc Mật khẩu NVR."
            }
        else:
            return {
                "success": False,
                "message": f"❌ Đầu ghi phản hồi mã lỗi HTTP {res.status_code}. Kiểm tra lại cấu hình NAT/Port Forwarding."
            }
    except requests.exceptions.Timeout:
        return {
            "success": False,
            "message": f"❌ Hết thời gian chờ (Timeout 8s). Không thể kết nối tới IP/Tên miền {cfg.nvr_host}:{cfg.nvr_port}. Kiểm tra DDNS/IP Tĩnh và Cổng HTTP."
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"❌ Không thể kết nối tới NVR qua Internet: {str(e)}"
        }

@app.post("/api/config/nvr")
async def update_nvr_config(cfg: NVRConfigModel):
    allowed_codes = {item["code"] for item in config.ABNORMAL_BEHAVIOR_OPTIONS}
    unsupported_codes = sorted(set(cfg.abnormal_event_codes) - allowed_codes)
    if unsupported_codes:
        return JSONResponse(
            status_code=422,
            content={"error": f"Mã hành vi metadata không hỗ trợ: {', '.join(unsupported_codes)}"},
        )
    cfg_dict = cfg.dict()
    # Keep the persisted configuration predictable if a client submits the
    # same checkbox value more than once.
    cfg_dict["abnormal_event_codes"] = list(dict.fromkeys(cfg.abnormal_event_codes))
    config.update_global_config(cfg_dict)
    restart_listener_service()
    return {"status": "success", "message": f"Cấu hình kết nối NVR ({cfg.nvr_host}) đã được cập nhật thành công!"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
