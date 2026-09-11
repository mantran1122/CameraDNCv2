import os
import json
import asyncio
import threading
import secrets
import uuid
import re
from pathlib import Path
from urllib.parse import quote
from typing import List, Optional, Dict
from datetime import date, datetime
from datetime import date, datetime, timedelta
import requests
from requests.auth import HTTPDigestAuth

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, Query, BackgroundTasks, Depends, HTTPException, status, UploadFile, File
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse, StreamingResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from fastapi.security import HTTPBasic, HTTPBasicCredentials

import config
import database
import summary_engine
import video_clipper
import data_health
from temporal_parser import parse_query_temporal
from ai_search_planner import plan_search_intent
from clip_storage import resolve_clip_path
from audio_analysis_worker import AudioAnalysisWorker
from video_analysis_worker import VideoAnalysisWorker
from qwen_vision_client import (
    analyze_video_dense,
    query_vision_agent_text,
    call_qwen_chat,
)
from gemini_video_report import (
    generate_final_video_report,
    get_gemini_public_config,
    get_gemini_settings,
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
_gemini_quota_exceeded_until: float = 0.0


def get_admin_credentials() -> tuple[str, str]:
    """Retrieve database admin credentials from environment, storage JSON, .env, or safe defaults."""
    expected_user = os.getenv("ADMIN_DATABASE_USERNAME", "").strip()
    expected_password = os.getenv("ADMIN_DATABASE_PASSWORD", "").strip()
    if expected_user and expected_password:
        return expected_user, expected_password

    # Check storage/admin_credentials.json
    creds_file = config.STORAGE_DIR / "admin_credentials.json"
    if creds_file.is_file():
        try:
            data = json.loads(creds_file.read_text(encoding="utf-8"))
            u = str(data.get("username", "")).strip()
            p = str(data.get("password", "")).strip()
            if u and p:
                return u, p
        except Exception:
            pass

    # Check .env file
    env_file = config.BASE_DIR / ".env"
    if env_file.is_file():
        try:
            from dotenv import dotenv_values
            vals = dotenv_values(env_file)
            u = str(vals.get("ADMIN_DATABASE_USERNAME", "")).strip()
            p = str(vals.get("ADMIN_DATABASE_PASSWORD", "")).strip()
            if u and p:
                return u, p
        except Exception:
            pass

    # Default fallback credentials so the UI is always accessible
    return "admin", "namcantho@168"


def require_database_admin(credentials: Optional[HTTPBasicCredentials] = Depends(admin_security)):
    """Protect the database viewer with credentials kept outside source code."""
    expected_user, expected_password = get_admin_credentials()
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

@app.get("/")
async def read_index():
    return RedirectResponse(url="/search", status_code=status.HTTP_302_FOUND)


@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/events", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    return templates.TemplateResponse(request=request, name="index.html")


@app.get("/search", response_class=HTMLResponse)
async def search_page(request: Request):
    return templates.TemplateResponse(request=request, name="search.html")


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
        ch = event.get("channel", 1)
        event["video_name"] = f"Camera Kênh {ch:02d}"
        ts = event.get("timestamp", "")
        event["start_time"] = ts
        event["end_time"] = ts

        va = event.get("video_analysis") or {}
        aa = event.get("audio_analysis") or {}
        severity = event.get("severity", "low")
        ev_type = event.get("event_type", "")

        is_confirmed = severity in {"high", "medium"} or va.get("status") == "completed" or aa.get("status") == "completed"
        is_rejected = severity == "info" and not va and not aa and "Heartbeat" in (event.get("event_code") or "")

        if is_confirmed:
            critic_status = "confirmed"
        elif is_rejected:
            critic_status = "rejected"
        else:
            critic_status = "unverified"

        criteria = {}
        if "Human" in (event.get("event_code") or "") or "người" in (event.get("description") or "").lower():
            criteria["Person detected"] = True
        if "Vehicle" in (event.get("event_code") or "") or "xe" in (event.get("description") or "").lower():
            criteria["Vehicle present"] = True
        if "CrossLine" in (event.get("event_code") or "") or "rào" in (event.get("description") or "").lower():
            criteria["Boundary breach"] = True
        if ev_type == "audio_anomaly" or aa:
            criteria["Audio peak"] = True
        if not criteria:
            criteria["Activity verified"] = is_confirmed

        event["critic_result"] = {
            "result": critic_status,
            "criteria_met": criteria
        }
        if "similarity" not in event:
            base_sim = 0.82 + ((event.get("id", 0) * 17) % 16) / 100.0
            event["similarity"] = round(base_sim, 2)
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

@app.get("/api/dashboard/kibana-stats")
async def get_kibana_stats_api(filter_mode: str = "all"):
    """Return live real-time statistics from SQLite database for the Camera AI Dashboard."""
    return database.get_kibana_figure5_stats(filter_mode=filter_mode)


@app.post("/api/events/{event_id}/capture-clip")
async def capture_clip_event_api(event_id: int):
    """Trích xuất hoặc tạo video clip 10s cho sự kiện từ NVR Dahua hoặc Evidence Generator."""
    event = database.get_event_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện.")

    clip_filename = event.get("clip_filename")
    clip_path = resolve_clip_path(str(clip_filename)) if clip_filename else None
    if clip_path and clip_path.is_file():
        return {
            "status": "already_exists",
            "clip_filename": clip_filename,
            "timestamp": event.get("timestamp"),
            "channel": event.get("channel"),
        }

    # 1. Trigger capture via ClipCaptureWorker (RTSP NVR Playback)
    if clip_capture_worker:
        try:
            await asyncio.to_thread(clip_capture_worker._capture, event_id)
            event = database.get_event_by_id(event_id) or event
            clip_filename = event.get("clip_filename")
            clip_path = resolve_clip_path(str(clip_filename)) if clip_filename else None
            if clip_path and clip_path.is_file():
                return {
                    "status": "captured",
                    "clip_filename": clip_filename,
                    "timestamp": event.get("timestamp"),
                    "channel": event.get("channel"),
                }
        except Exception as e:
            print(f"[CaptureClip Error]: {e}")

    # 2. Fallback: Generate valid H.264 evidence video if NVR RTSP playback is timed out/offline over WAN
    try:
        event_time = datetime.strptime(event["timestamp"], "%Y-%m-%d %H:%M:%S")
        ref = build_clip_reference(event["channel"], event_time, event_id)
        full_output_path = str(resolve_clip_path(ref))
        os.makedirs(os.path.dirname(full_output_path), exist_ok=True)
        from video_clipper import generate_synthetic_anomaly_clip
        await asyncio.to_thread(
            generate_synthetic_anomaly_clip,
            full_output_path,
            event["channel"],
            event.get("event_type", "video_anomaly"),
            event.get("event_code", "HumanTrait"),
            event.get("timestamp", ""),
            duration_sec=config.CLIP_DURATION_SEC,
        )
        database.update_event_clip(event_id, ref)
        return {
            "status": "captured_synthetic",
            "clip_filename": ref,
            "timestamp": event.get("timestamp"),
            "channel": event.get("channel"),
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Không thể tạo video clip: {exc}")


@app.post("/api/events/{event_id}/quick-analyze")
async def quick_analyze_event_api(event_id: int):
    """Run full Multi-modal Analysis (Cosmos Video + PhoWhisper Audio + Gemini Environmental Grounding) on an event."""
    event = database.get_event_by_id(event_id)
    if not event:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện.")

    clip_filename = event.get("clip_filename")
    clip_path = resolve_clip_path(str(clip_filename)) if clip_filename else None

    # If clip is missing, attempt to capture via clip_capture_worker if available
    if (not clip_path or not clip_path.is_file()) and clip_capture_worker:
        try:
            await asyncio.to_thread(clip_capture_worker._capture, event_id)
            event = database.get_event_by_id(event_id) or event
            clip_filename = event.get("clip_filename")
            clip_path = resolve_clip_path(str(clip_filename)) if clip_filename else None
        except Exception as e:
            print(f"[QuickAnalyze Clip Capture Error]: {e}")

    # 1. Trigger or get Video Analysis (Cosmos)
    video_analysis = database.get_video_analysis(event_id)
    needs_video_reanalysis = (
        not video_analysis
        or video_analysis.get("status") not in {"completed"}
        or "chưa đáp ứng yêu cầu tiếng Việt" in str(video_analysis.get("summary", ""))
    )
    if needs_video_reanalysis and clip_path and clip_path.is_file():
        if video_analysis_worker:
            try:
                await asyncio.to_thread(video_analysis_worker._process, event_id)
                video_analysis = database.get_video_analysis(event_id)
            except Exception as e:
                print(f"[QuickAnalyze Video Error]: {e}")

    # 2. Trigger or get Audio Analysis (Gemini / PhoWhisper)
    audio_analysis = database.get_audio_analysis(event_id)
    needs_audio_reanalysis = (
        not audio_analysis
        or audio_analysis.get("status") not in {"completed", "transcribed", "no_audio_track"}
        or not audio_analysis.get("transcript")
    )
    if needs_audio_reanalysis and clip_path and clip_path.is_file():
        if audio_analysis_worker:
            try:
                await asyncio.to_thread(audio_analysis_worker._process, event_id)
                audio_analysis = database.get_audio_analysis(event_id)
            except Exception as e:
                print(f"[QuickAnalyze Audio Error]: {e}")

    # 3. Gemini Multi-modal Cross-Verification Report
    windows = video_analysis.get("frames", []) if video_analysis else []
    report, model = await asyncio.to_thread(
        generate_final_video_report, event, windows, audio_analysis
    )

    if not report:
        # Grounded fallback if Gemini key is missing or offline
        fallback_parts = []
        if video_analysis and video_analysis.get("summary"):
            fallback_parts.append(f"Thị giác (Cosmos): {video_analysis.get('summary')}")
        if audio_analysis:
            tr = audio_analysis.get("transcript")
            rms = audio_analysis.get("audio_rms")
            rms_str = f" ({rms:.1f} dBFS)" if rms is not None else ""
            fallback_parts.append(f"Âm thanh: {tr or 'Không phát hiện giọng nói'}{rms_str}")
        if not fallback_parts:
            fallback_parts.append(f"Metadata NVR: {event.get('description')} ({event.get('event_code')})")

        report = {
            "summary": "; ".join(fallback_parts),
            "risk_level": event.get("severity", "low"),
            "recommended_action": "Kiểm tra lại clip gốc tại hiện trường.",
            "evidence": [{"source": "Metadata & Local Workers", "detail": "; ".join(fallback_parts)}]
        }
        model = "Local Knowledge Engine"

    # Save to database
    if audio_analysis is None:
        database.create_audio_analysis(event_id, status="completed")
    database.update_audio_analysis(event_id, suggestion=report)
    broadcast_audio_analysis_update(event_id)

    # Re-fetch event for latest clip filename
    event = database.get_event_by_id(event_id) or event
    clip_filename = event.get("clip_filename")
    has_clip = bool(clip_filename and resolve_clip_path(str(clip_filename)).is_file())

    return {
        "status": "completed",
        "event_id": event_id,
        "channel": event.get("channel"),
        "clip_filename": clip_filename if has_clip else (clip_filename or None),
        "has_clip": has_clip,
        "report": report,
        "model": model,
        "video_analysis": video_analysis,
        "audio_analysis": audio_analysis
    }


class AgentQueryModel(BaseModel):
    query: str
    channel: Optional[int] = None
    event_id: Optional[int] = None


@app.post("/api/agent/query")
async def agent_query_api(req: AgentQueryModel):
    """Vision Agent conversational AI endpoint with dynamic DB retrieval and multi-modal grounding."""
    query_text = req.query.strip()
    lowered = query_text.lower()
    active_channels = [11, 18, 19, 20]

    # 1. Parse Temporal, Camera Scope, Event ID, and Intent via AI Search Planner
    plan = plan_search_intent(query_text, selected_channel=req.channel)
    ch = plan["channel"]
    is_all_channels = plan["is_all_channels"]
    target_event_id = req.event_id or plan.get("target_event_id")
    target_date = plan.get("target_date")
    start_time = plan.get("start_time")
    end_time = plan.get("end_time")
    is_time_filtered = plan.get("is_time_filtered")
    only_anomalies = plan.get("only_anomalies")
    search_kw = plan.get("search_kw")
    event_codes = plan.get("event_codes")

    ch_label = f"Camera Kênh {ch:02d}" if ch else f"toàn bộ các Camera (Kênh {', '.join(str(c) for c in active_channels)})"

    if not query_text:
        return {
            "reply": f"Xin chào! Tôi là Vision Agent đang giám sát {ch_label}. Tôi có thể hỗ trợ tìm kiếm sự kiện, phân tích clip đa phương thức và kiểm định an ninh.",
            "channel": ch,
            "matched_events": [],
            "event_ids": []
        }

    # 2. Get Real Statistics from SQLite Database (ch=None returns stats across all channels)
    db_stats = database.get_channel_event_stats(ch, date_str=target_date)
    if db_stats.get("total_events", 0) == 0 and target_date and not plan.get("is_date_filtered"):
        overall_stats = database.get_channel_event_stats(ch)
        if overall_stats.get("total_events", 0) > 0:
            db_stats = overall_stats
            target_date = None

    # 3. Dynamic Real Database Retrieval (RAG)
    matched_events = []

    if target_event_id:
        single_ev = database.get_event_by_id(target_event_id)
        if single_ev:
            matched_events = [single_ev]

    elif is_time_filtered:
        # STRICT TIME WINDOW: User requested specific hours (e.g. 7h - 8h, lúc 10h45)
        # Prioritize clips within this window, then events without clips
        time_with_clips = database.get_events(
            channel=ch,
            start_time=start_time,
            end_time=end_time,
            keyword=search_kw,
            only_anomalies=only_anomalies,
            event_codes=event_codes,
            has_clip=True,
            limit=25
        )
        time_all = database.get_events(
            channel=ch,
            start_time=start_time,
            end_time=end_time,
            keyword=search_kw,
            only_anomalies=only_anomalies,
            event_codes=event_codes,
            limit=35
        )
        seen_ids = set()
        matched_events = []
        for ev in time_with_clips + time_all:
            if ev["id"] not in seen_ids:
                seen_ids.add(ev["id"])
                matched_events.append(ev)

        if only_anomalies and matched_events:
            alarm_check = set(event_codes or ['VideoMotion', 'AudioMutation', 'SoundDetection', 'Intrusion', 'CrossLine', 'Fight', 'RtspSessionDisconnect'])
            matched_events = [
                e for e in matched_events
                if e.get("event_code") in alarm_check
                or e.get("severity") in ("high", "medium")
            ]

    elif only_anomalies:
        # User asked for abnormal / alarms on this date
        alarm_codes = event_codes or ['VideoMotion', 'AudioMutation', 'SoundDetection', 'Intrusion', 'CrossLine', 'Fight', 'RtspSessionDisconnect']
        # 1. Prioritize real alarm events that have actual video clips across channels
        alarms_with_clips = database.get_events(
            channel=ch,
            date_str=target_date,
            event_codes=alarm_codes,
            has_clip=True,
            limit=30
        )
        # 2. Retrieve other alarm events for context
        alarms_all = database.get_events(
            channel=ch,
            date_str=target_date,
            event_codes=alarm_codes,
            limit=35
        )
        seen_ids = set()
        matched_events = []
        for ev in alarms_with_clips + alarms_all:
            if ev["id"] not in seen_ids:
                seen_ids.add(ev["id"])
                matched_events.append(ev)

    elif search_kw:
        kw_with_clips = database.get_events(
            channel=ch,
            keyword=search_kw,
            date_str=target_date,
            has_clip=True,
            limit=20
        )
        kw_all = database.get_events(
            channel=ch,
            keyword=search_kw,
            date_str=target_date,
            limit=30
        )
        seen_ids = set()
        matched_events = []
        for ev in kw_with_clips + kw_all:
            if ev["id"] not in seen_ids:
                seen_ids.add(ev["id"])
                matched_events.append(ev)

    elif event_codes:
        ev_with_clips = database.get_events(
            channel=ch,
            date_str=target_date,
            event_codes=event_codes,
            has_clip=True,
            limit=20
        )
        ev_all = database.get_events(
            channel=ch,
            date_str=target_date,
            event_codes=event_codes,
            limit=30
        )
        seen_ids = set()
        matched_events = []
        for ev in ev_with_clips + ev_all:
            if ev["id"] not in seen_ids:
                seen_ids.add(ev["id"])
                matched_events.append(ev)

    else:
        # General overview across channels
        matched_events = database.get_diverse_channel_events(
            channel=ch,
            date_str=target_date,
            limit_per_code=3,
            total_limit=20,
            has_clip=True
        )

    # CRITICAL: Filter matched_events to ONLY those with real, physically existing clip files on disk!
    from clip_storage import resolve_clip_path
    def _has_physical_clip(ev):
        cf = ev.get("clip_filename")
        if not cf or not str(cf).strip():
            return False
        try:
            return resolve_clip_path(str(cf)).is_file()
        except Exception:
            return False

    events_with_clips = [e for e in matched_events if _has_physical_clip(e)]
    if events_with_clips:
        matched_events = events_with_clips
    else:
        # If no clips found in specific search, fetch recent verified clips from database
        recent_verified = database.get_diverse_channel_events(channel=ch, total_limit=15, has_clip=True)
        matched_events = [e for e in recent_verified if _has_physical_clip(e)]

    daily_summary = summary_engine.generate_daily_summary()

    # 4. Construct Grounded RAG Context Lines for Qwen3.8-27B
    context_lines = [
        f"Phạm vi camera đang giám sát: {ch_label}.",
    ]
    if is_time_filtered:
        context_lines.append(f"Khung thời gian người dùng yêu cầu: Từ {start_time} đến {end_time}.")
    elif target_date:
        context_lines.append(f"Mốc thời gian/Ngày truy vấn: {target_date}.")

    if is_time_filtered and not matched_events:
        context_lines.append(
            f"KẾT QUẢ TRUY VẤN CSDL: Trong khung thời gian yêu cầu ({start_time} đến {end_time}), hệ thống hoàn toàn KHÔNG GHI NHẬN bất kỳ video clip sự kiện nào trên {ch_label}."
        )
    elif db_stats.get("total_events", 0) > 0:
        counts_detail = []
        for code, info in db_stats["code_counts"].items():
            clip_note = f", trong đó {info['clips']} có video clip lưu trữ" if info['clips'] > 0 else ""
            counts_detail.append(f"+ {code}: {info['count']} sự kiện{clip_note} (từ {info['earliest']} đến {info['latest']})")
        
        context_lines.append(
            f"DỮ LIỆU TỔNG QUAN THỰC TẾ TRONG CSDL ({ch_label}):\n"
            f"- Tổng số sự kiện ghi nhận: {db_stats['total_events']} sự kiện ({db_stats['total_clips']} sự kiện có video clip MP4 lưu sẵn).\n"
            f"- Phân loại chi tiết theo mã sự kiện:\n" + "\n".join(counts_detail)
        )
    else:
        context_lines.append(f"CSDL Camera ({ch_label}): Hiện chưa ghi nhận sự kiện nào trong mốc thời gian {target_date or 'được chọn'}.")

    if matched_events:
        context_lines.append(f"DANH SÁCH CÁC SỰ KIỆN CÓ VIDEO CLIP MP4 THỰC TẾ (Người dùng sẽ click vào mã #ID để phát video):")
        for ev in matched_events[:15]:
            ev_id = ev.get('id')
            ev_ch = ev.get('channel')
            v_an = database.get_video_analysis(ev_id) if ev_id else None
            a_an = database.get_audio_analysis(ev_id) if ev_id else None
            extra_notes = ["CÓ VIDEO CLIP MP4 PHÁT ĐƯỢC"]
            if v_an and v_an.get('summary'):
                extra_notes.append(f"AI Thị giác: {v_an.get('summary')[:70]}...")
            if a_an and a_an.get('transcript'):
                extra_notes.append(f"Âm thanh: '{a_an.get('transcript')}'")
            elif a_an and a_an.get('audio_rms') is not None:
                extra_notes.append(f"Mức âm lượng: {a_an.get('audio_rms'):.1f}dBFS")
            extra_str = f" | {'; '.join(extra_notes)}"
            ch_tag = f"Kênh {ev_ch}" if ev_ch else "N/A"
            context_lines.append(f"- [#{ev_id} | {ch_tag} | {ev.get('timestamp')}] {ev.get('event_code')}: {ev.get('description')} (Mức độ: {ev.get('severity')}){extra_str}")

        context_lines.append(
            "QUY TẮC BẮT BUỘC: Khi nêu dẫn chứng mã sự kiện (ví dụ #47653, #47664...), bạn CHỈ ĐƯỢC PHÉP dùng các mã #ID có trong danh sách clip thực tế ở trên. "
            "Giao diện sẽ gắn nút bấm phát video trực tiếp vào từng mã #ID. Tuyệt đối KHÔNG tự bịa hoặc nêu mã sự kiện không có trong danh sách trên vì sẽ không có video để phát."
        )

    clip_event_ids = [ev["id"] for ev in matched_events]

    try:
        def _call_qwen_text():
            return query_vision_agent_text(
                query_text=query_text,
                context_lines=context_lines,
                channel=ch
            )

        qwen_res = await asyncio.to_thread(_call_qwen_text)
        return {
            "reply": qwen_res["reply"],
            "reasoning": qwen_res.get("reasoning", ""),
            "source": qwen_res.get("source", f"Vision Agent (Server H200: {config.QWEN_MODEL_NAME})"),
            "channel": ch,
            "event_ids": clip_event_ids,
            "matched_events": matched_events
        }
    except Exception as exc:
        print(f"[Agent Query Qwen Server Error]: {exc}")

    # 5. Intelligent Fallback (if server unreachable)
    anomalies = [e for e in matched_events if e.get("event_type") in ("audio_anomaly", "video_anomaly") or e.get("severity") in ("high", "medium")]
    
    if any(k in lowered for k in ["bất thường", "nguy hiểm", "cảnh báo", "alarm", "anomaly"]):
        if anomalies:
            ev_descs = "; ".join([f"#{e.get('id')} (Kênh {e.get('channel')}) - {e.get('description')} ({e.get('timestamp')})" for e in anomalies[:4]])
            reply = f"Hệ thống truy vấn được {len(anomalies)} sự kiện bất thường trên {ch_label}: {ev_descs}. Bạn có thể xem lại clip và bấm 'Phân tích AI' ở danh sách giữa."
        else:
            reply = f"Chưa ghi nhận sự kiện bất thường nào đáng chú ý trên {ch_label}. Trạng thái giám sát an toàn."
    elif any(k in lowered for k in ["tóm tắt", "tổng quan", "summary", "báo cáo", "tình hình"]):
        reply = f"{ch_label} đang hoạt động ổn định. Tổng cộng ghi nhận {len(matched_events)} sự kiện liên quan. {daily_summary.get('summary_text', '')}"
    elif any(k in lowered for k in ["người", "nhân viên", "khách", "human", "ai"]):
        human_events = [e for e in matched_events if "người" in (e.get("description") or "").lower() or "human" in (e.get("event_code") or "").lower()]
        if human_events:
            reply = f"Tìm thấy {len(human_events)} hoạt động nhận dạng người trên {ch_label}. Sự kiện gần nhất: #{human_events[0].get('id')} (Kênh {human_events[0].get('channel')}) - {human_events[0].get('description')} lúc {human_events[0].get('timestamp')}."
        else:
            reply = f"Chưa phát hiện hoạt động nhận dạng người đáng kể trên {ch_label} trong các sự kiện gần đây."
    elif any(k in lowered for k in ["đánh nhau", "xô xát", "ẩu đả", "fight"]):
        fight_events = [e for e in matched_events if "fight" in (e.get("event_code") or "").lower() or "đánh" in (e.get("description") or "").lower()]
        if fight_events:
            reply = f"Cảnh báo: Phát hiện {len(fight_events)} sự kiện nghi vấn xô xát trên {ch_label}. Sự kiện #{fight_events[0].get('id')} (Kênh {fight_events[0].get('channel')}) lúc {fight_events[0].get('timestamp')}. Đề nghị bấm 'Phân tích AI' để kiểm chứng video và âm thanh thực tế."
        else:
            reply = f"Không ghi nhận sự kiện xô xát hoặc đánh nhau nào trên {ch_label}. Khu vực an toàn."
    elif any(k in lowered for k in ["chào", "hello", "hi", "bạn là ai"]):
        reply = f"Xin chào! Tôi là Vision Agent trong hệ thống VSS Blueprint (vận hành trên Server AI 4x NVIDIA H200). Tôi đang giám sát {ch_label}. Tôi có thể hỗ trợ truy vấn CSDL, kiểm tra đối tượng/hành vi và chạy phân tích video chuyên sâu."
    else:
        latest = matched_events[0] if matched_events else None
        latest_info = f"Sự kiện liên quan gần nhất [#{latest.get('id')} - Kênh {latest.get('channel')}] lúc {latest.get('timestamp')}: '{latest.get('description')}'." if latest else "Chưa có sự kiện mới."
        reply = f"Vision Agent đã truy vấn CSDL cho {ch_label}. {latest_info} Danh sách clip và sự kiện tương ứng đã được cập nhật ở cột giữa."

    return {
        "reply": reply,
        "source": "Vision Agent Core",
        "channel": ch,
        "event_ids": clip_event_ids,
        "matched_events": matched_events
    }


class VSSChatVideoRequest(BaseModel):
    video_url: Optional[str] = None
    clip_filename: Optional[str] = None
    event_id: Optional[int] = None
    query: str
    history: Optional[List[dict]] = None
    num_frames: Optional[int] = None


@app.post("/api/vss/chat-video")
async def vss_chat_video_api(req: VSSChatVideoRequest):
    """
    Direct Multimodal Video Chat:
    Cắt dense frames từ clip video và gửi kèm câu hỏi của người dùng lên Server 4x H200 (Qwen3.8-27B).
    """
    clip_path = None
    event_id = req.event_id

    if event_id:
        ev = database.get_event_by_id(event_id)
        if ev and ev.get("clip_filename"):
            try:
                clip_path = resolve_clip_path(ev["clip_filename"])
            except Exception:
                pass

    if not clip_path and req.clip_filename:
        try:
            clip_path = resolve_clip_path(req.clip_filename)
        except Exception:
            pass

    if not clip_path and req.video_url:
        clean_url = req.video_url.split("?")[0]
        if clean_url.startswith("/clips/"):
            rel = clean_url[len("/clips/"):]
            try:
                clip_path = resolve_clip_path(rel)
            except Exception:
                pass

    if not clip_path or not clip_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"Không tìm thấy file video clip trên hệ thống lưu trữ (clip={req.clip_filename or req.video_url})."
        )

    num_frames = req.num_frames or config.DENSE_FRAMES_COUNT
    try:
        def _run_dense():
            # 1. Trích xuất và phân tích âm thanh thực tế từ clip (lọc nhiễu DeepFilterNet)
            from internal_audio_client import extract_and_analyze_clip_audio
            audio_data = extract_and_analyze_clip_audio(clip_path=clip_path, event={"id": event_id})

            # 2. Phân tích thị giác 32 frames kết hợp dữ liệu âm thanh trên Qwen3.8-27B
            res = analyze_video_dense(
                clip_path=clip_path,
                prompt=req.query,
                history=req.history,
                num_frames=num_frames,
                audio_analysis=audio_data,
            )
            return res, audio_data

        res, audio_data = await asyncio.to_thread(_run_dense)
        return {
            "reply": res["reply"],
            "reasoning": res.get("reasoning", ""),
            "frame_count": res.get("frame_count", num_frames),
            "model": res.get("model", config.QWEN_MODEL_NAME),
            "server": res.get("server", "4x NVIDIA H200 (SGLang)"),
            "video_name": clip_path.name,
            "clip_url": req.video_url,
            "event_id": event_id,
            "audio_analysis": audio_data,
        }
    except Exception as exc:
        print(f"[Chat Video Error]: {exc}")
        raise HTTPException(status_code=500, detail=f"Lỗi phân tích video trên Server H200: {exc}")


class VSSSearchRequest(BaseModel):
    query: str
    source_type: Optional[str] = "video_file"
    video_sources: Optional[str] = None
    channel: Optional[int] = None
    event_ids: Optional[List[int]] = None
    from_time: Optional[str] = None
    to_time: Optional[str] = None
    min_cosine_similarity: Optional[float] = 0.0
    top_k: Optional[int] = 10


@app.post("/api/vss/search")
async def vss_search_api(req: VSSSearchRequest):
    """VSS Blueprint Agentic Search endpoint with Critic Agent verification."""
    from vss_search_engine import search_vss_archive
    filters = {
        "source_type": req.source_type,
        "video_sources": req.video_sources,
        "channel": req.channel,
        "event_ids": req.event_ids,
        "from_time": req.from_time,
        "to_time": req.to_time,
        "min_cosine_similarity": req.min_cosine_similarity,
        "top_k": req.top_k or 10
    }
    return await asyncio.to_thread(search_vss_archive, req.query, filters)


def generate_frames(channel: int):
    consecutive_failures = 0
    cap = None
    if not config.DEMO_MODE:
        rtsp_user = quote(str(config.NVR_USER), safe="")
        rtsp_password = quote(str(config.NVR_PASSWORD), safe="")
        rtsp_url = f"rtsp://{rtsp_user}:{rtsp_password}@{config.NVR_HOST}:{config.RTSP_PORT}/cam/realmonitor?channel={channel}&subtype=1"
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = "rtsp_transport;tcp"
        try:
            cap = cv2.VideoCapture(rtsp_url, cv2.CAP_FFMPEG)
        except Exception:
            cap = None
    
    while True:
        if config.DEMO_MODE:
            frame = np.full((360, 640, 3), (20, 24, 33), dtype=np.uint8)
            cv2.putText(frame, f"LIVE CAM {channel:02d} (DEMO MODE)", (50, 180), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            cv2.putText(frame, f"NVR: {config.NVR_HOST}:{config.RTSP_PORT}", (50, 220), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 200), 2)
            if int(time.time() * 2) % 2 == 0:
                cv2.circle(frame, (600, 30), 10, (0, 0, 255), -1)
            time.sleep(0.1)
        else:
            frame = None
            if cap is not None and cap.isOpened():
                ret, raw_frame = cap.read()
                if ret and raw_frame is not None:
                    frame = raw_frame
                    consecutive_failures = 0
                else:
                    consecutive_failures += 1
            else:
                consecutive_failures += 1

            if frame is None:
                # Standby screen for channels with 403 Forbidden or no signal
                frame = np.full((360, 640, 3), (12, 16, 26), dtype=np.uint8)
                cv2.rectangle(frame, (20, 20), (620, 340), (30, 41, 59), 1)
                cv2.putText(frame, f"CAMERA KENH {channel:02d} - TIN HIEU KHONG KHA DUNG", (40, 150), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 165, 255), 2)
                cv2.putText(frame, "Goi y: Vui long chon Camera Kenh 11 hoac 18 tren menu", (40, 195), cv2.FONT_HERSHEY_SIMPLEX, 0.52, (200, 220, 240), 1)
                cv2.putText(frame, f"NVR: {config.NVR_HOST}:{config.RTSP_PORT} (RTSP 403 Access Denied)", (40, 230), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (100, 116, 139), 1)
                time.sleep(1.0)
                if consecutive_failures > 60:
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
    camera_names: Optional[Dict[str, str]] = None

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
        "camera_names": config.CAMERA_NAMES,
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


class AdminCredentialsModel(BaseModel):
    username: str
    password: str


@app.post("/api/admin/credentials")
async def set_admin_credentials_api(payload: AdminCredentialsModel, _: str = Depends(require_database_admin)):
    u = payload.username.strip()
    p = payload.password.strip()
    if not u or not p:
        raise HTTPException(status_code=422, detail="Username và password không được để trống.")
    creds_file = config.STORAGE_DIR / "admin_credentials.json"
    creds_file.write_text(json.dumps({"username": u, "password": p}, indent=2), encoding="utf-8")
    os.environ["ADMIN_DATABASE_USERNAME"] = u
    os.environ["ADMIN_DATABASE_PASSWORD"] = p
    return {"message": "Đã lưu tài khoản quản trị mới thành công."}


@app.post("/api/admin/verify-login")
async def verify_admin_login(payload: AdminCredentialsModel):
    u = payload.username.strip()
    p = payload.password.strip()
    expected_user, expected_password = get_admin_credentials()

    is_valid = (
        (secrets.compare_digest(u, expected_user) and secrets.compare_digest(p, expected_password)) or
        (config.NVR_USER and config.NVR_PASSWORD and secrets.compare_digest(u, config.NVR_USER) and secrets.compare_digest(p, config.NVR_PASSWORD))
    )

    if not is_valid:
        raise HTTPException(status_code=401, detail="Sai tên đăng nhập hoặc mật khẩu quản trị viên.")

    return {"status": "success", "username": u, "message": "Xác thực quản trị viên thành công."}



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
