import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from html import escape
from pathlib import Path

# Add project root to sys.path to ensure modules like 'app' and 'src' are importable
# when running the script directly with streamlit (which adds app/ to the path instead of the root).
PROJ_ROOT = Path(__file__).resolve().parents[1]
if str(PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJ_ROOT))

from typing import Any, Dict, List, Tuple

import streamlit as st

from app.playback_media_server import register_playback_video
from app.ui import dashboard as ui
from src.result_utils import clean_text
from src.vector_store import (
    DEFAULT_DB_DIR,
    DEFAULT_EMBEDDING_MODEL,
    DEFAULT_SUMMARY_TABLE_NAME,
    DEFAULT_TABLE_NAME,
    index_result_file,
    search_video,
)
from src.video_utils import hhmmss_to_seconds


APP_DIR = PROJ_ROOT
STATIC_DIR = APP_DIR / "static"
OUTPUTS_DIR = APP_DIR / "outputs"
HISTORY_DIR = OUTPUTS_DIR / "history"
CONFIG_PATH = APP_DIR / "config.json"
PLAYBACK_INBOX = APP_DIR / "playback_inbox"


def _load_config() -> Dict[str, Any]:
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_config(cfg: Dict[str, Any]) -> None:
    try:
        existing = _load_config()
        existing.update(cfg)
        CONFIG_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


_cfg = _load_config()
SERVER_VIDEO_DIR = Path(os.getenv("COSMOS_SERVER_VIDEO_DIR", _cfg.get("inprogress_dir", r"D:\dev\dnc\data_test_cam")))
VIDEO_PATH = STATIC_DIR / "demo.mp4"
RESULT_PATH = OUTPUTS_DIR / "result_demo.json"
VECTOR_DB_DIR = APP_DIR / DEFAULT_DB_DIR

STATIC_DIR.mkdir(exist_ok=True)
OUTPUTS_DIR.mkdir(exist_ok=True)
HISTORY_DIR.mkdir(parents=True, exist_ok=True)
PLAYBACK_INBOX.mkdir(parents=True, exist_ok=True)

EventList = List[Dict[str, Any]]


def _load_playback_handoff() -> Dict[str, Any]:
    """Read only a complete, local Dahua playback handoff addressed to this URL token."""
    token = str(st.query_params.get("playback_token", "")).strip()
    if not token:
        return {}
    manifest_path = PLAYBACK_INBOX / "playback_handoff.json"
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        video = Path(str(data.get("video_path", ""))).resolve()
        inbox = PLAYBACK_INBOX.resolve()
        if (data.get("token") != token or data.get("source") != "dahua_playback" or
                video.suffix.lower() != ".mp4" or inbox not in video.parents or
                not video.is_file() or video.stat().st_size <= 0):
            raise ValueError("manifest hoặc video không hợp lệ")
        data["video"] = video
        return data
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        st.error(f"Không thể nhận video Playback: {exc}")
        return {}


def _reset_for_playback_token(token: str) -> None:
    if st.session_state.get("playback_token") == token:
        return
    st.session_state.playback_token = token
    st.session_state.events = []
    st.session_state.search_answer = ""
    st.session_state.selected_event_index = 0
    st.session_state.timeline_start_seconds = 0
    st.session_state.last_analysis_report = None
    if RESULT_PATH.exists():
        RESULT_PATH.unlink()


def _render_playback_handoff(handoff: Dict[str, Any], api: Any) -> None:
    video = Path(handoff["video"])
    token = str(handoff["token"])
    st.subheader("Video Playback từ đầu ghi")
    st.caption(f"Kênh {handoff.get('channel')} · {handoff.get('start_time')} → {handoff.get('end_time')}")
    media_url = register_playback_video(video, token)
    st.session_state.playback_media_url = media_url
    st.session_state.playback_media_path = str(video.resolve())
    st.video(media_url, format="video/mp4")
    st.caption(
        f"Đang phát trực tiếp từ file Playback ({video.stat().st_size / (1024 ** 3):.2f} GB); "
        "trình duyệt chỉ tải phần video cần xem."
    )
    attempted = st.session_state.setdefault("playback_attempted_tokens", set())
    if handoff.get("auto_analyze") and token not in attempted:
        attempted.add(token)
        if api.run_analysis(video):
            st.rerun()
    if st.button("Bắt đầu phân tích", key=f"playback_analyze_{token}", disabled=st.session_state.is_loading):
        st.session_state.last_analysis_report = None
        if api.run_analysis(video):
            st.rerun()
    _render_playback_analysis_report(video)


def _render_playback_analysis_report(video: Path) -> None:
    report = st.session_state.get("last_analysis_report") or {}
    if not report or Path(str(report.get("video_path", ""))) != video:
        return
    if report.get("ok"):
        st.success(_format_analysis_report(report))
        return
    error = clean_text(report.get("error", "")) or "Pipeline phân tích đã kết thúc với lỗi."
    st.error(f"Phân tích chưa chạy thành công: {error}")
    log_path = Path(str(report.get("log_path", "")))
    if log_path.is_file():
        st.caption(f"Log phân tích: {log_path}")
        try:
            tail = log_path.read_text(encoding="utf-8", errors="replace")[-4000:].strip()
        except OSError:
            tail = ""
        if tail:
            with st.expander("Xem log lỗi", expanded=True):
                st.code(tail, language="text")


def main() -> None:
    logo_icon = str(APP_DIR / "logo.png")
    st.set_page_config(page_title="DNC - VSS", page_icon=logo_icon if (APP_DIR / "logo.png").exists() else "🎥", layout="wide", initial_sidebar_state="expanded")
    init_state()
    ui.render_page_style()
    with st.sidebar:
        # Move Logo here - try SVG first for better quality, fallback to PNG
        logo_svg = APP_DIR / "logo.svg"
        logo_png = APP_DIR / "logo.png"
        if logo_svg.exists():
            st.image(str(logo_svg), use_container_width=True)
        elif logo_png.exists():
            st.image(str(logo_png), use_container_width=True)
        
        st.markdown("### :material/explore: Điều hướng")
        menu = st.radio(
            "Chức năng",
            [
                ":material/cloud_upload: Upload Video Mới",
                ":material/manage_search: Tìm Kiếm Toàn Lịch Sử",
                ":material/history: Lịch Sử Phân Tích",
                ":material/assessment: Báo Cáo & Xuất File",
            ],
            label_visibility="collapsed"
        )
        st.divider()
        render_openai_settings()

    ensure_history_snapshot()

    api = build_ui_api()
    handoff = _load_playback_handoff()
    if handoff:
        _reset_for_playback_token(str(handoff["token"]))
    # Auto-start folder monitor if it was enabled in config
    if st.session_state.get("folder_monitor_enabled", False):
        status = get_folder_monitor_status()
        if not status["running"]:
            folder = _server_video_dir()
            if folder.exists() and folder.is_dir():
                start_folder_monitor(api)

    if menu == ":material/cloud_upload: Upload Video Mới":
        if handoff:
            _render_playback_handoff(handoff, api)
            if RESULT_PATH.exists():
                data = load_result()
                if not st.session_state.events:
                    reset_search_state(data)
                ui.render_result_view(Path(handoff["video"]), st.session_state.events, st.session_state.search_answer, api)
        elif RESULT_PATH.exists():
            data = load_result()
            if not st.session_state.events:
                reset_search_state(data)
            ui.render_result_view(
                video_path=resolve_video_path(data, VIDEO_PATH),
                events=st.session_state.events,
                search_answer=st.session_state.search_answer,
                api=api,
            )
        else:
            ui.render_upload_view(VIDEO_PATH, api)

    elif menu == ":material/manage_search: Tìm Kiếm Toàn Lịch Sử":
        render_global_search_tab()

    elif menu == ":material/history: Lịch Sử Phân Tích":
        render_history_tab()

    elif menu == ":material/assessment: Báo Cáo & Xuất File":
        data = load_result() if RESULT_PATH.exists() else {}
        ui.render_report_tab(
            data=data,
            events=st.session_state.events,
            api=api,
        )


def init_state() -> None:
    # Load persisted config first
    cfg = _load_config()
    st.session_state.setdefault("video_token", None)
    st.session_state.setdefault("events", [])
    st.session_state.setdefault("title", "Nội dung tạo bởi AI")
    st.session_state.setdefault("search_answer", "")
    st.session_state.setdefault("selected_event_index", 0)
    st.session_state.setdefault("timeline_start_seconds", 0)
    st.session_state.setdefault("global_search_events", [])
    st.session_state.setdefault("global_search_answer", "")
    # Credentials belong to the operator environment or ignored local config,
    # never to source control.  An empty key keeps local/offline features usable.
    st.session_state.setdefault("openai_api_key", cfg.get("openai_api_key", os.getenv("OPENAI_API_KEY", "")))
    st.session_state.setdefault("openai_base_url", cfg.get("openai_base_url", os.getenv("OPENAI_BASE_URL", "https://integrate.api.nvidia.com/v1")))
    st.session_state.setdefault("openai_search_model", cfg.get("openai_search_model", os.getenv("OPENAI_SEARCH_MODEL", "nvidia/nvidia-nemotron-nano-9b-v2")))
    st.session_state.setdefault("last_analysis_report", None)
    st.session_state.setdefault("is_loading", False)
    st.session_state.setdefault("analysis_progress", {"percent": 0.0, "completed": 0, "total": 0, "stage": "Sẵn sàng"})
    st.session_state.setdefault("chat_history", [])
    st.session_state.setdefault("time_filter_min", 0)
    st.session_state.setdefault("time_filter_max", 86400)
    # Report defaults (override with persisted config if available)
    st.session_state.setdefault("report_title", cfg.get("report_title", "BÁO CÁO GIÁM SÁT VIDEO"))
    st.session_state.setdefault("report_header", cfg.get("report_header", "HỆ THỐNG GIÁM SÁT AN NINH\nCông ty DNC"))
    st.session_state.setdefault("report_footer", cfg.get("report_footer", "Ngưởi lập báo cáo: _______________\nNgày lập: {date}"))
    st.session_state.setdefault("report_include_stats", cfg.get("report_include_stats", True))
    st.session_state.setdefault("report_include_events", cfg.get("report_include_events", True))
    st.session_state.setdefault("report_include_details", cfg.get("report_include_details", True))
    # Email config defaults (override with persisted config if available)
    st.session_state.setdefault("smtp_server", cfg.get("smtp_server", "smtp.gmail.com"))
    st.session_state.setdefault("smtp_port", cfg.get("smtp_port", 587))
    st.session_state.setdefault("smtp_sender", cfg.get("smtp_sender", os.getenv("SMTP_SENDER", "tttien@nctu.edu.vn")))
    st.session_state.setdefault("smtp_password", cfg.get("smtp_password", os.getenv("SMTP_PASSWORD", "")))
    st.session_state.setdefault("report_recipients", cfg.get("report_recipients", ""))
    st.session_state.setdefault("smtp_enable_ssl", cfg.get("smtp_enable_ssl", True))
    st.session_state.setdefault("email_notify_enabled", cfg.get("email_notify_enabled", False))
    st.session_state.setdefault("email_notify_threshold", cfg.get("email_notify_threshold", "low"))
    # Inprogress / input folder
    st.session_state.setdefault("inprogress_dir", cfg.get("inprogress_dir", str(SERVER_VIDEO_DIR)))
    # Folder monitor auto-start flag
    st.session_state.setdefault("folder_monitor_enabled", cfg.get("folder_monitor_enabled", False))

def build_ui_api() -> ui.UiApi:
    def current_data() -> Dict[str, Any]:
        return load_result() if RESULT_PATH.exists() else {}

    return ui.UiApi(
        semantic_search=lambda query, limit, mode: semantic_search(current_data(), query, limit, mode),
        keyword_search=lambda query: keyword_search(current_data(), query),
        rebuild_index=rebuild_vector_index,
        reset_search=lambda: reset_search_state(current_data()),
        save_uploaded_video=save_uploaded_video,
        available_server_videos=available_server_videos,
        use_server_video=use_server_video,
        run_analysis=run_analysis,
        clear_outputs=clear_all_outputs,
        clear_vector_db=clear_vector_db,
        has_existing_result=lambda: RESULT_PATH.exists(),
        clear_video_data=lambda video_name: _clear_video_data(video_name),
        save_email_config=lambda cfg: _save_config(cfg),
        start_folder_monitor=lambda api: start_folder_monitor(api),
        stop_folder_monitor=stop_folder_monitor,
        get_folder_monitor_status=get_folder_monitor_status,
    )


def render_openai_settings() -> None:
    with st.expander(":material/settings: Cấu hình LLM metadata", expanded=False):
        api_key = st.text_input(
            "API key",
            value=st.session_state.openai_api_key,
            type="password",
            key="openai_api_key_input",
            help="Key dùng cho endpoint OpenAI-compatible.",
        )
        base_url = st.text_input(
            "Base URL",
            value=st.session_state.openai_base_url,
            key="openai_base_url_input",
        )
        model = st.text_input(
            "Model metadata",
            value=st.session_state.openai_search_model,
            key="openai_search_model_input",
        )

        st.session_state.openai_api_key = api_key.strip()
        st.session_state.openai_base_url = base_url.strip().rstrip("/") or "https://llm.chiasegpu.vn/v1"
        st.session_state.openai_search_model = model.strip() or "ai_model"
        if st.session_state.openai_api_key:
            os.environ["OPENAI_API_KEY"] = st.session_state.openai_api_key
        else:
            os.environ.pop("OPENAI_API_KEY", None)
        os.environ["OPENAI_BASE_URL"] = st.session_state.openai_base_url
        os.environ["OPENAI_SEARCH_MODEL"] = st.session_state.openai_search_model

        if st.button("💾 Lưu cấu hình LLM", use_container_width=True, key="btn_save_llm_cfg"):
            cfg = _load_config()
            cfg["openai_api_key"] = st.session_state.openai_api_key
            cfg["openai_base_url"] = st.session_state.openai_base_url
            cfg["openai_search_model"] = st.session_state.openai_search_model
            _save_config(cfg)
            st.success("✅ Đã lưu cấu hình LLM vào config.json!", icon=":material/check_circle:")


def ensure_history_snapshot() -> None:
    if not RESULT_PATH.exists():
        return
    try:
        data = load_result()
    except Exception:
        return
    video_id = clean_text(data.get("video_id", ""))
    if not video_id:
        return
    dst = HISTORY_DIR / f"{video_id}.json"
    if not dst.exists():
        dst.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def load_result() -> Dict[str, Any]:
    return json.loads(RESULT_PATH.read_text(encoding="utf-8"))


def resolve_video_path(data: Dict[str, Any], default_path: Path) -> Path:
    raw = clean_text(data.get("video_file", ""))
    raw = _from_wsl_path(raw)
    candidates = [default_path]
    if raw:
        normalized = raw.replace("\\", "/")
        candidates.extend([Path(raw), Path(normalized)])
        if not Path(normalized).is_absolute():
            candidates.append(APP_DIR / normalized)
        if not Path(raw).is_absolute():
            candidates.append(APP_DIR / raw)

    seen = set()
    for candidate in candidates:
        key = str(candidate)
        if key in seen:
            continue
        seen.add(key)
        try:
            if candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        except OSError:
            continue
    return default_path


def get_segments(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    if not isinstance(data, dict):
        return []
    return [item for item in data.get("segments", []) if isinstance(item, dict)]


def make_event(seg: Dict[str, Any]) -> Dict[str, Any] | None:
    start = clean_text(seg.get("start") or seg.get("start_time"))
    if not start:
        return None
    end = clean_text(seg.get("end") or seg.get("end_time"))
    score = _optional_float(seg.get("score"))
    return {
        "video_id": clean_text(seg.get("video_id", "")),
        "video_file": _from_wsl_path(clean_text(seg.get("video_file", ""))),
        "start": start,
        "end": end,
        "sec": _event_seconds(seg, start),
        "desc": clean_text(seg.get("description") or seg.get("summary") or seg.get("text")),
        "risk_level": clean_text(seg.get("risk_level", "none")),
        "abnormal": bool(seg.get("abnormal", False)),
        "chunk_path": _from_wsl_path(clean_text(seg.get("chunk_path", ""))),
        "chunk_index": seg.get("chunk_index"),
        "score": score,
    }


def all_events(data: Dict[str, Any]) -> EventList:
    return [event for seg in get_segments(data) if (event := make_event(seg))]


def reset_search_state(data: Dict[str, Any]) -> EventList:
    events = all_events(data)
    st.session_state.events = events
    st.session_state.title = "Nội dung tạo bởi AI"
    st.session_state.search_answer = ""
    st.session_state.selected_event_index = 0
    st.session_state.timeline_start_seconds = int(events[0].get("sec", 0)) if events else 0
    st.session_state.pop("filter_actions", None)
    st.session_state.pop("filter_today", None)
    st.session_state.pop("filter_from_date", None)
    st.session_state.pop("filter_to_date", None)
    st.session_state.pop("filter_validated_only", None)
    return events


def clear_all_outputs() -> Dict[str, Any]:
    deleted = 0
    errors: List[str] = []
    for pattern in ("*.json", "*.log"):
        for path in OUTPUTS_DIR.glob(pattern):
            try:
                path.unlink()
                deleted += 1
            except Exception as exc:
                errors.append(str(exc))
    for path in HISTORY_DIR.glob("*.json"):
        try:
            path.unlink()
            deleted += 1
        except Exception as exc:
            errors.append(str(exc))
    chunks_dir = OUTPUTS_DIR / "chunks"
    if chunks_dir.exists():
        for path in chunks_dir.glob("*"):
            try:
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)
                deleted += 1
            except Exception as exc:
                errors.append(str(exc))
    for path in STATIC_DIR.glob("*"):
        if path.name in (".keep", ".gitkeep"):
            continue
        try:
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                shutil.rmtree(path)
            deleted += 1
        except Exception as exc:
            errors.append(str(exc))
    return {"deleted": deleted, "errors": errors}


def clear_vector_db() -> Dict[str, Any]:
    deleted = 0
    errors: List[str] = []
    if VECTOR_DB_DIR.exists():
        for path in VECTOR_DB_DIR.glob("*"):
            try:
                if path.is_file():
                    path.unlink()
                elif path.is_dir():
                    shutil.rmtree(path)
                deleted += 1
            except Exception as exc:
                errors.append(str(exc))
    return {"deleted": deleted, "errors": errors}


def _clear_video_data(video_name: str) -> Dict[str, Any]:
    deleted = 0
    errors: List[str] = []
    # Delete current result
    if RESULT_PATH.exists():
        try:
            RESULT_PATH.unlink()
            deleted += 1
        except Exception as exc:
            errors.append(str(exc))
    # Delete related history files matching video name
    for path in HISTORY_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            vf = clean_text(data.get("video_file", ""))
            if video_name in vf:
                path.unlink()
                deleted += 1
        except Exception:
            continue
    # Delete chunks related to this video
    chunks_dir = OUTPUTS_DIR / "chunks"
    if chunks_dir.exists():
        for chunk in chunks_dir.glob("*"):
            if video_name in chunk.name:
                try:
                    if chunk.is_file():
                        chunk.unlink()
                    elif chunk.is_dir():
                        shutil.rmtree(chunk)
                    deleted += 1
                except Exception as exc:
                    errors.append(str(exc))
    return {"deleted": deleted, "errors": errors}


def keyword_search(data: Dict[str, Any], query: str) -> EventList:
    query_lower = clean_text(query).lower()
    if not query_lower:
        return all_events(data)

    matched = []
    for seg in get_segments(data):
        raw = json.dumps(seg, ensure_ascii=False).lower()
        if query_lower in raw:
            event = make_event(seg)
            if event:
                matched.append(event)
    return matched


def semantic_search(data: Dict[str, Any], query: str, limit: int, mode: str = "hybrid_lancedb") -> Tuple[EventList, str]:
    if not data:
        return [], "Chưa có kết quả phân tích để tìm kiếm."

    if mode == "openai_metadata":
        return _search_with_openai_metadata(data, query, limit)

    try:
        result = _search_video(data, query, limit)
    except RuntimeError:
        rebuild_vector_index()
        result = _search_video(data, query, limit)

    events = [event for item in result.get("segment_matches", []) if (event := make_event(item))]
    summary_matches = result.get("summary_matches", [])
    answer = _format_summary_answer(summary_matches[0], query) if summary_matches else ""
    return events, answer


def _search_video(data: Dict[str, Any], query: str, limit: int) -> Dict[str, Any]:
    return search_video(
        query=query,
        db_dir=VECTOR_DB_DIR,
        segment_table_name=DEFAULT_TABLE_NAME,
        summary_table_name=DEFAULT_SUMMARY_TABLE_NAME,
        embedding_model=DEFAULT_EMBEDDING_MODEL,
        video_id=data.get("video_id"),
        limit=limit,
    )


def rebuild_vector_index() -> Dict[str, Any]:
    history_files = history_result_files()
    if not history_files and not RESULT_PATH.exists():
        return {
            "indexed": False,
            "reason": f"Missing result files: {RESULT_PATH} and {HISTORY_DIR}",
            "count": 0,
        }
    total = 0
    summary_indexed = 0
    files = history_files[:] if history_files else []
    if RESULT_PATH.exists():
        files.append(RESULT_PATH)
    for path in files:
        info = index_result_file(
            result_path=path,
            db_dir=VECTOR_DB_DIR,
            table_name=DEFAULT_TABLE_NAME,
            summary_table_name=DEFAULT_SUMMARY_TABLE_NAME,
            embedding_model=DEFAULT_EMBEDDING_MODEL,
        )
        total += int(info.get("count", 0) or 0)
        if (info.get("summary_index") or {}).get("indexed"):
            summary_indexed += 1
    return {"indexed": True, "count": total, "summary_index": {"indexed": summary_indexed > 0}}


def save_uploaded_video(uploaded_file: Any) -> None:
    file_size = int(getattr(uploaded_file, "size", 0) or 0)
    if file_size <= 0:
        raise RuntimeError("File upload rỗng hoặc không đọc được dữ liệu video.")

    free_bytes = shutil.disk_usage(str(STATIC_DIR)).free
    reserve_bytes = 2 * 1024 * 1024 * 1024  # Keep 2GB headroom for chunking/indexing.
    if file_size and free_bytes < (file_size + reserve_bytes):
        raise RuntimeError(
            f"Khong du dung luong dia trong de upload. Can toi thieu ~{(file_size + reserve_bytes) / (1024**3):.1f}GB."
        )

    if hasattr(uploaded_file, "seek"):
        uploaded_file.seek(0)
    with VIDEO_PATH.open("wb") as file_obj:
        shutil.copyfileobj(uploaded_file, file_obj, length=8 * 1024 * 1024)
    if RESULT_PATH.exists():
        RESULT_PATH.unlink()
    st.session_state.last_analysis_report = None


def _server_video_dir() -> Path:
    custom = st.session_state.get("server_video_dir", "")
    if custom:
        return Path(custom)
    return Path(st.session_state.get("inprogress_dir", str(SERVER_VIDEO_DIR)))


# ── Folder monitor (auto-analysis) ──
FOLDER_MONITOR: Dict[str, Any] = {
    "running": False,
    "thread": None,
    "process": None,   # subprocess.Popen reference
    "watch_dir": "",   # resolved path to monitor (set on start)
    "current_file": "",
    "current_path": None,
    "message": "",
    "processed_count": 0,
    "error_count": 0,
    "skipped_count": 0,
    "retry_count": {},  # filepath -> retry count
    "max_retries": 2,
    "current_video_size": 0,
    "current_video_duration": 0.0,
    "current_chunk": 0,
    "total_chunks": 0,
    "analysis_start_time": 0.0,
    # Detailed status fields
    "stage": "idle",   # idle / waiting / model_loading / chunking / analyzing / summarizing / indexing / alerting / completed / error
    "status_detail": "",  # Human-readable detail
    "risk_level": "none",
    "risk_segments": 0,
    "high_risk_count": 0,
    "medium_risk_count": 0,
    "low_risk_count": 0,
    "log_tail": "",    # last log line
}


_SIGNATURE_INDEX_PATH = OUTPUTS_DIR / "analyzed_signatures.json"


# Cache ffprobe path at module load time (main thread)
_FFPROBE_CACHED: str | None = None

def _resolve_ffprobe() -> str:
    """Resolve ffprobe path once and cache it."""
    global _FFPROBE_CACHED
    if _FFPROBE_CACHED is not None:
        return _FFPROBE_CACHED
    import shutil
    ffprobe = shutil.which("ffprobe")
    if ffprobe:
        _FFPROBE_CACHED = ffprobe
        return _FFPROBE_CACHED
    # Fallback to project-local ffmpeg (various Windows layouts)
    candidates = [
        APP_DIR / "ffmpeg" / "bin" / "ffprobe.exe",
        APP_DIR / "ffmpeg" / "ffprobe.exe",
        APP_DIR / "ffprobe.exe",
    ]
    for candidate in candidates:
        if candidate.exists():
            _FFPROBE_CACHED = str(candidate)
            return _FFPROBE_CACHED
    _FFPROBE_CACHED = "ffprobe"
    return _FFPROBE_CACHED


def _get_ffprobe_path() -> str:
    """Return cached ffprobe path."""
    return _resolve_ffprobe()


def _get_video_duration_ffprobe(path: Path) -> float:
    """Get video duration in seconds (float, millisecond precision) using ffprobe."""
    try:
        ffprobe = _get_ffprobe_path()
        probe = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30, encoding="utf-8", errors="replace"
        )
        duration = float(probe.stdout.strip())
        return duration
    except Exception:
        return 0.0


def _get_file_signature(path: Path) -> Tuple[int, float]:
    """Return (size_bytes, duration_seconds) signature for a video file.
    Duration is from ffprobe, precise to milliseconds.
    If ffprobe fails, falls back to (size, mtime) so duplicate detection still works.
    """
    try:
        stat = path.stat()
        size = int(stat.st_size)
        duration = _get_video_duration_ffprobe(path)
        if duration > 0:
            return (size, duration)
        # Fallback: use modification time (seconds) when ffprobe unavailable
        return (size, float(stat.st_mtime))
    except Exception:
        return (0, 0.0)


def _load_signature_index() -> set:
    """Load set of analyzed file signatures."""
    if not _SIGNATURE_INDEX_PATH.exists():
        return set()
    try:
        data = json.loads(_SIGNATURE_INDEX_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return set(tuple(item) for item in data if isinstance(item, (list, tuple)) and len(item) == 2)
    except Exception:
        pass
    return set()


def _save_signature_index(sigs: set) -> None:
    """Save analyzed file signatures to JSON."""
    try:
        _SIGNATURE_INDEX_PATH.write_text(json.dumps([list(s) for s in sigs], ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _is_video_already_analyzed(video_path: Path) -> bool:
    """Check if a video has already been analyzed by its exact signature (size_bytes + duration/mtime).
    Also falls back to name-based check for legacy data.
    """
    video_name = video_path.name
    sig = _get_file_signature(video_path)
    if sig[0] <= 0:
        return False

    # 1) Check signature index (exact match: size + duration/mtime)
    sig_index = _load_signature_index()
    if sig in sig_index:
        return True

    # 2) Fallback: check history files by name for legacy compatibility
    for path in HISTORY_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            vf = clean_text(data.get("video_file", ""))
            vid = clean_text(data.get("video_id", ""))
            if video_name in vf or video_name in vid:
                return True
        except Exception:
            continue
    # 3) Fallback: check current result by name
    if RESULT_PATH.exists():
        try:
            data = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
            vf = clean_text(data.get("video_file", ""))
            vid = clean_text(data.get("video_id", ""))
            if video_name in vf or video_name in vid:
                return True
        except Exception:
            pass
    return False


def _clear_existing_analysis(video_path: Path) -> int:
    """Remove all existing analysis data (history, result, chunks) for a video.
    Returns number of items deleted.
    """
    deleted = 0
    video_name = video_path.name
    sig = _get_file_signature(video_path)

    # Remove signature from index
    if sig[0] > 0:
        sig_index = _load_signature_index()
        if sig in sig_index:
            sig_index.discard(sig)
            _save_signature_index(sig_index)

    # Remove matching history files
    for path in HISTORY_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            vf = clean_text(data.get("video_file", ""))
            vid = clean_text(data.get("video_id", ""))
            if video_name in vf or video_name in vid:
                path.unlink()
                deleted += 1
        except Exception:
            continue
    # Remove current result if it matches
    if RESULT_PATH.exists():
        try:
            data = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
            vf = clean_text(data.get("video_file", ""))
            vid = clean_text(data.get("video_id", ""))
            if video_name in vf or video_name in vid:
                RESULT_PATH.unlink()
                deleted += 1
        except Exception:
            pass
    # Remove chunks related to this video
    chunks_dir = OUTPUTS_DIR / "chunks"
    if chunks_dir.exists():
        for path in chunks_dir.glob("*"):
            if video_name in path.name:
                try:
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        shutil.rmtree(path)
                    deleted += 1
                except Exception:
                    pass
    return deleted


def _cleanup_partial_analysis(current_file: str = "") -> None:
    """Remove partial results and chunks for the file being processed."""
    # Only remove current result, not all history
    try:
        if RESULT_PATH.exists():
            RESULT_PATH.unlink()
    except Exception:
        pass
    # Clear chunks related to current file only
    chunks_dir = OUTPUTS_DIR / "chunks"
    if chunks_dir.exists() and current_file:
        # Try to find chunks by filename pattern
        stem = Path(current_file).stem
        for path in chunks_dir.glob("*"):
            if stem in path.name:
                try:
                    if path.is_file():
                        path.unlink()
                    elif path.is_dir():
                        shutil.rmtree(path)
                except Exception:
                    pass


# ── Email alert rate-limit tracker (thread-safe, shared state) ──
EMAIL_TRACKER: Dict[str, Any] = {
    "sent_today": 0,
    "last_reset_date": "",
    "paused_until": 0.0,
    "consecutive_errors": 0,
    "daily_limit": 100,
    "lock": threading.Lock(),
}


def _is_rate_limited() -> bool:
    now = time.time()
    today_str = datetime.now().strftime("%Y-%m-%d")
    with EMAIL_TRACKER["lock"]:
        # Reset counter if new day
        if EMAIL_TRACKER["last_reset_date"] != today_str:
            EMAIL_TRACKER["sent_today"] = 0
            EMAIL_TRACKER["last_reset_date"] = today_str
            EMAIL_TRACKER["consecutive_errors"] = 0
            EMAIL_TRACKER["paused_until"] = 0.0
            return False
        if now < EMAIL_TRACKER["paused_until"]:
            return True
        if EMAIL_TRACKER["sent_today"] >= EMAIL_TRACKER["daily_limit"]:
            # Auto-pause until next day if daily limit reached
            tomorrow = datetime.now() + timedelta(days=1)
            EMAIL_TRACKER["paused_until"] = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0).timestamp()
            return True
        return False


def _smtp_error_is_rate_limit(exc: Exception) -> bool:
    """Detect SMTP quota / rate-limit / daily-limit errors from exception text."""
    msg = str(exc).lower()
    rate_limit_codes = {"421", "450", "451", "452", "454", "550", "551", "552", "553"}
    rate_phrases = [
        "rate limit", "daily limit", "quota exceeded", "too many messages",
        "sending limit", "message limit", "try again later", "temporarily disabled",
        "login rate limit", "authentication rate limit", "suspicious",
    ]
    # Check code in message
    for code in rate_limit_codes:
        if code in msg:
            return True
    # Check phrases
    for phrase in rate_phrases:
        if phrase in msg:
            return True
    return False


def _build_alert_html(video_name: str, segments: List[Dict[str, Any]]) -> str:
    rows = []
    for seg in segments:
        rows.append(
            f"<tr>"
            f"<td>{seg.get('start','')}</td>"
            f"<td>{seg.get('end','')}</td>"
            f"<td><strong>{seg.get('risk_level','').upper()}</strong></td>"
            f"<td>{seg.get('description','')}</td>"
            f"</tr>"
        )
    return f"""
    <p>Hệ thống DNC-VSS phát hiện rủi ro trong video: <strong>{video_name}</strong></p>
    <table border="1" cellpadding="6" cellspacing="0" style="border-collapse:collapse;font-family:Arial,sans-serif;font-size:13px;">
      <tr style="background:#0f766e;color:#fff;">
        <th>Bắt đầu</th><th>Kết thúc</th><th>Rủi ro</th><th>Mô tả</th>
      </tr>
      {''.join(rows)}
    </table>
    <p><em>Email tự động từ hệ thống giám sát DNC-VSS.</em></p>
    """


def _send_alert_email_core(video_name: str, segments: List[Dict[str, Any]], cfg: Dict[str, Any]) -> None:
    """Core SMTP send – runs inside a background thread. Never raises."""
    recipients = cfg.get("report_recipients", "").strip()
    sender = cfg.get("smtp_sender", "").strip()
    password = cfg.get("smtp_password", "").strip()
    server_addr = cfg.get("smtp_server", "smtp.gmail.com").strip()
    port = int(cfg.get("smtp_port", 587))
    use_ssl = bool(cfg.get("smtp_enable_ssl", True))
    if not recipients or not sender or not password:
        return
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
    except ImportError:
        return
    html_body = _build_alert_html(video_name, segments)
    msg = MIMEMultipart()
    msg["From"] = sender
    msg["To"] = recipients
    _ts = datetime.now().strftime('%H:%M:%S %d/%m/%Y')
    _uid = datetime.now().strftime('%Y%m%d%H%M%S')
    msg["Subject"] = f"[CẢNH BÁO DNC-VSS #{_uid}] Phát hiện rủi ro trong video \"{video_name}\" – {_ts}"
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    try:
        server = smtplib.SMTP(server_addr, port, timeout=15)
        if use_ssl:
            server.starttls()
        server.login(sender, password)
        server.sendmail(sender, [r.strip() for r in recipients.split(",") if r.strip()], msg.as_string())
        server.quit()
        with EMAIL_TRACKER["lock"]:
            EMAIL_TRACKER["sent_today"] += 1
            EMAIL_TRACKER["consecutive_errors"] = 0
    except Exception as exc:
        with EMAIL_TRACKER["lock"]:
            EMAIL_TRACKER["consecutive_errors"] += 1
            err_count = EMAIL_TRACKER["consecutive_errors"]
        # If rate-limit detected, pause until next day
        if _smtp_error_is_rate_limit(exc):
            tomorrow = datetime.now() + timedelta(days=1)
            pause_ts = datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0).timestamp()
            with EMAIL_TRACKER["lock"]:
                EMAIL_TRACKER["paused_until"] = pause_ts
        # Exponential backoff for transient errors (max ~10 min)
        elif err_count <= 6:
            backoff = min(2 ** err_count, 600)
            with EMAIL_TRACKER["lock"]:
                EMAIL_TRACKER["paused_until"] = time.time() + backoff


def _send_alert_email(video_name: str, segments: List[Dict[str, Any]], cfg: Dict[str, Any]) -> None:
    """Fire-and-forget alert email in a background thread. Never blocks or crashes caller."""
    try:
        t = threading.Thread(
            target=_send_alert_email_core,
            args=(video_name, segments, cfg),
            daemon=True,
            name="alert-email-sender",
        )
        t.start()
    except Exception:
        pass


def _check_and_send_alert(video_name: str) -> None:
    """Read latest result and enqueue alert email if risk >= configured threshold."""
    if _is_rate_limited():
        return
    try:
        cfg = _load_config()
    except Exception:
        return
    if not cfg.get("email_notify_enabled", False):
        return
    threshold = cfg.get("email_notify_threshold", "low")
    risk_order = {"none": 0, "low": 1, "medium": 2, "high": 3}
    min_level = risk_order.get(threshold, 1)
    if not RESULT_PATH.exists():
        return
    try:
        data = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
    except Exception:
        return
    segments = get_segments(data)
    alert_segments = []
    for seg in segments:
        level = risk_order.get(clean_text(seg.get("risk_level", "none")), 0)
        if level >= min_level:
            alert_segments.append(seg)
    if alert_segments:
        _send_alert_email(video_name, alert_segments, cfg)


def _update_monitor_stage(line: str) -> None:
    """Parse log line and update detailed stage/status for folder monitor UI."""
    line_lower = line.lower()
    FOLDER_MONITOR["log_tail"] = line[:200]

    # Exclude false positives from model checkpoint / tqdm logs
    is_tqdm_line = "|" in line and ("it/s]" in line or "s/it]" in line or "<?, ?it/s]" in line)
    is_checkpoint_line = any(k in line_lower for k in ["safetensors", "checkpoint shards", "loading weights", "completed |", "bytes]"]) or is_tqdm_line
    is_index_json_line = "safetensors.index.json" in line_lower or "checkpoint index" in line_lower

    # Stage detection from log keywords
    if any(k in line_lower for k in ["load model", "loading model", "init model", "prepare model"]):
        FOLDER_MONITOR["stage"] = "model_loading"
        FOLDER_MONITOR["status_detail"] = "Đang nạp mô hình AI..."
    elif any(k in line_lower for k in ["prepared", "prepare", "chunk video", "cut chunk", "splitting"]):
        FOLDER_MONITOR["stage"] = "chunking"
        FOLDER_MONITOR["status_detail"] = "Đang cắt video thành các đoạn (chunk)..."
    elif any(k in line_lower for k in ["saved segment", "processing segment", "analyze chunk", "infer chunk"]):
        FOLDER_MONITOR["stage"] = "analyzing"
        completed, total = _parse_analysis_progress(line, FOLDER_MONITOR.get("current_chunk", 0), FOLDER_MONITOR.get("total_chunks", 0))
        if total > 0:
            FOLDER_MONITOR["current_chunk"] = completed
            FOLDER_MONITOR["total_chunks"] = total
            FOLDER_MONITOR["status_detail"] = f"Đang xử lý chunk thứ {completed}/{total}..."
        else:
            FOLDER_MONITOR["status_detail"] = "Đang phân tích nội dung video..."
    elif any(k in line_lower for k in ["summary", "summarize", "tom tat"]):
        FOLDER_MONITOR["stage"] = "summarizing"
        FOLDER_MONITOR["status_detail"] = "Đang tóm tắt nội dung video..."
    elif any(k in line_lower for k in ["index", "lancedb", "vector"]) and not is_index_json_line:
        FOLDER_MONITOR["stage"] = "indexing"
        FOLDER_MONITOR["status_detail"] = "Đang lập chỉ mục tìm kiếm ngữ nghĩa..."
    elif any(k in line_lower for k in ["alert", "email", "send mail", "cảnh báo"]):
        FOLDER_MONITOR["stage"] = "alerting"
        FOLDER_MONITOR["status_detail"] = "Đang gửi cảnh báo email..."
    # Only mark completed from highly-specific output lines (not generic progress bars)
    elif ("done. result saved to:" in line_lower or "vector index saved to:" in line_lower) and not is_checkpoint_line:
        FOLDER_MONITOR["stage"] = "completed"
        FOLDER_MONITOR["status_detail"] = "Hoàn tất phân tích."


def _monitor_progress_callback(line: str) -> None:
    """Parse analysis log and update folder monitor chunk progress + stage."""
    _update_monitor_stage(line)


def _folder_monitor_worker(api: Any) -> None:
    FOLDER_MONITOR["message"] = "Worker đã khởi động."
    while FOLDER_MONITOR["running"]:
        try:
            watch_dir = FOLDER_MONITOR.get("watch_dir", "")
            folder = Path(watch_dir) if watch_dir else _server_video_dir()
            FOLDER_MONITOR["message"] = f"Quét thư mục: {folder}"
            if not folder.exists() or not folder.is_dir():
                FOLDER_MONITOR["message"] = f"Thư mục không tồn tại: {folder}"
                time.sleep(1)
                continue
            # List all files in folder for debugging
            all_files = [p.name for p in folder.iterdir() if p.is_file()]
            FOLDER_MONITOR["message"] = f"Thư mục {folder.name}: {len(all_files)} file ({', '.join(all_files[:5])})"
            videos = []
            for pattern in ("*.mp4", "*.mpeg", "*.mpg", "*.mov", "*.avi", "*.mkv"):
                found = list(folder.glob(pattern))
                if found:
                    videos.extend(found)
            FOLDER_MONITOR["message"] = f"Tìm thấy {len(videos)} video trong {folder.name}"
            # Sort by newest first (most recently modified)
            videos = sorted(
                [p for p in videos if p.is_file() and p.stat().st_size > 0],
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not videos:
                FOLDER_MONITOR["message"] = "Đang chờ file video mới..."
                time.sleep(1)
                continue
            video = videos[0]
            # ── Handle already-analyzed files: clear old data then skip ──
            sig = _get_file_signature(video)
            sig_index = _load_signature_index()
            is_dup = _is_video_already_analyzed(video)
            FOLDER_MONITOR["message"] = f"Kiểm tra: {video.name} | sig={sig} | index={len(sig_index)} | dup={is_dup}"
            if is_dup:
                cleared = _clear_existing_analysis(video)
                FOLDER_MONITOR["skipped_count"] += 1
                FOLDER_MONITOR["message"] = f"Đã phân tích, xóa {cleared} dữ liệu cũ: {video.name}"
                try:
                    video.unlink()
                except Exception:
                    pass
                time.sleep(1)
                continue
            FOLDER_MONITOR["current_file"] = video.name
            FOLDER_MONITOR["current_path"] = str(video)
            FOLDER_MONITOR["current_video_size"] = video.stat().st_size
            FOLDER_MONITOR["current_video_duration"] = _get_video_duration_ffprobe(video)
            FOLDER_MONITOR["current_chunk"] = 0
            FOLDER_MONITOR["total_chunks"] = 0
            FOLDER_MONITOR["analysis_start_time"] = time.perf_counter()
            FOLDER_MONITOR["stage"] = "chunking"
            FOLDER_MONITOR["status_detail"] = "Đang chuẩn bị phân tích..."
            FOLDER_MONITOR["risk_level"] = "none"
            FOLDER_MONITOR["risk_segments"] = 0
            FOLDER_MONITOR["high_risk_count"] = 0
            FOLDER_MONITOR["medium_risk_count"] = 0
            FOLDER_MONITOR["low_risk_count"] = 0
            FOLDER_MONITOR["message"] = f"Đang phân tích: {video.name}"
            try:
                # Copy to static/demo.mp4 (direct copy, no st.session_state)
                with video.open("rb") as src, VIDEO_PATH.open("wb") as dst:
                    shutil.copyfileobj(src, dst, length=16 * 1024 * 1024)
                if RESULT_PATH.exists():
                    RESULT_PATH.unlink()
                # Run analysis (no UI) — store process ref for kill on stop
                ok, _, _, _ = _run_analysis_subprocess(VIDEO_PATH, progress_callback=_monitor_progress_callback)
                FOLDER_MONITOR["process"] = None
                if ok:
                    FOLDER_MONITOR["processed_count"] += 1
                    FOLDER_MONITOR["stage"] = "completed"
                    FOLDER_MONITOR["status_detail"] = "Hoàn tất phân tích."
                    # Parse risk stats from result
                    try:
                        if RESULT_PATH.exists():
                            data = json.loads(RESULT_PATH.read_text(encoding="utf-8"))
                            segments = get_segments(data)
                            high = sum(1 for s in segments if clean_text(s.get("risk_level", "")) == "high")
                            medium = sum(1 for s in segments if clean_text(s.get("risk_level", "")) == "medium")
                            low = sum(1 for s in segments if clean_text(s.get("risk_level", "")) == "low")
                            FOLDER_MONITOR["high_risk_count"] = high
                            FOLDER_MONITOR["medium_risk_count"] = medium
                            FOLDER_MONITOR["low_risk_count"] = low
                            FOLDER_MONITOR["risk_segments"] = high + medium + low
                            if high > 0:
                                FOLDER_MONITOR["risk_level"] = "high"
                            elif medium > 0:
                                FOLDER_MONITOR["risk_level"] = "medium"
                            elif low > 0:
                                FOLDER_MONITOR["risk_level"] = "low"
                    except Exception:
                        pass
                    FOLDER_MONITOR["message"] = f"Hoàn tất: {video.name}"
                    # Save file signature to index so we detect duplicates by metadata
                    try:
                        sig = _get_file_signature(video)
                        if sig[0] > 0:
                            sig_index = _load_signature_index()
                            sig_index.add(sig)
                            _save_signature_index(sig_index)
                            FOLDER_MONITOR["message"] = f"Đã lưu signature: {sig} | index_size={len(sig_index)}"
                    except Exception as exc:
                        FOLDER_MONITOR["message"] = f"Lỗi lưu signature: {exc}"
                    # Save to history snapshot
                    try:
                        ensure_history_snapshot()
                        FOLDER_MONITOR["message"] = f"Đã lưu lịch sử: {video.name}"
                    except Exception as hist_exc:
                        FOLDER_MONITOR["message"] = f"Lỗi lưu lịch sử: {hist_exc}"
                    # Send alert email if risk detected
                    try:
                        _check_and_send_alert(video.name)
                    except Exception:
                        pass
                    # Delete original file
                    try:
                        video.unlink()
                        FOLDER_MONITOR["message"] = f"Đã xóa: {video.name}"
                    except Exception as del_exc:
                        FOLDER_MONITOR["message"] = f"Xong, không xóa được: {del_exc}"
                else:
                    FOLDER_MONITOR["stage"] = "error"
                    FOLDER_MONITOR["status_detail"] = "Phân tích thất bại."
                    # Retry logic
                    retries = FOLDER_MONITOR["retry_count"].get(str(video), 0) + 1
                    FOLDER_MONITOR["retry_count"][str(video)] = retries
                    if retries <= FOLDER_MONITOR["max_retries"]:
                        FOLDER_MONITOR["message"] = f"Lỗi, thử lại lần {retries}/{FOLDER_MONITOR['max_retries']}: {video.name}"
                        time.sleep(1)
                        continue  # retry same file
                    else:
                        FOLDER_MONITOR["error_count"] += 1
                        FOLDER_MONITOR["message"] = f"Lỗi sau {FOLDER_MONITOR['max_retries']} lần thử: {video.name}"
                        # Move to error subfolder
                        err_dir = folder / "error"
                        err_dir.mkdir(exist_ok=True)
                        try:
                            video.rename(err_dir / video.name)
                        except Exception:
                            pass
                        FOLDER_MONITOR["retry_count"].pop(str(video), None)
            except Exception as exc:
                FOLDER_MONITOR["error_count"] += 1
                FOLDER_MONITOR["stage"] = "error"
                FOLDER_MONITOR["status_detail"] = f"Lỗi: {exc}"
                FOLDER_MONITOR["message"] = f"Lỗi: {exc}"
            finally:
                FOLDER_MONITOR["process"] = None
                FOLDER_MONITOR["current_path"] = None
                FOLDER_MONITOR["analysis_start_time"] = 0.0
            time.sleep(0.5)
        except Exception:
            time.sleep(1)
    FOLDER_MONITOR["message"] = "Đã dừng giám sát."
    FOLDER_MONITOR["current_file"] = ""
    FOLDER_MONITOR["current_path"] = None
    FOLDER_MONITOR["watch_dir"] = ""
    FOLDER_MONITOR["current_video_size"] = 0
    FOLDER_MONITOR["current_video_duration"] = 0.0
    FOLDER_MONITOR["current_chunk"] = 0
    FOLDER_MONITOR["total_chunks"] = 0
    FOLDER_MONITOR["analysis_start_time"] = 0.0
    FOLDER_MONITOR["stage"] = "idle"
    FOLDER_MONITOR["status_detail"] = ""
    FOLDER_MONITOR["risk_level"] = "none"
    FOLDER_MONITOR["risk_segments"] = 0
    FOLDER_MONITOR["high_risk_count"] = 0
    FOLDER_MONITOR["medium_risk_count"] = 0
    FOLDER_MONITOR["low_risk_count"] = 0
    FOLDER_MONITOR["log_tail"] = ""


def start_folder_monitor(api: Any) -> None:
    if FOLDER_MONITOR["running"]:
        return
    FOLDER_MONITOR["running"] = True
    # Resolve watch dir from session_state/config before thread starts only if not already set
    if not FOLDER_MONITOR.get("watch_dir", "").strip():
        try:
            watch_dir = str(_server_video_dir())
        except Exception:
            cfg = _load_config()
            watch_dir = cfg.get("inprogress_dir", str(SERVER_VIDEO_DIR))
        FOLDER_MONITOR["watch_dir"] = watch_dir
    FOLDER_MONITOR["message"] = "Đang khởi động giám sát..."
    t = threading.Thread(target=_folder_monitor_worker, args=(api,), daemon=True)
    FOLDER_MONITOR["thread"] = t
    t.start()


def stop_folder_monitor() -> None:
    FOLDER_MONITOR["running"] = False
    FOLDER_MONITOR["message"] = "Đang dừng và dọn dẹp..."
    # Kill running subprocess
    proc = FOLDER_MONITOR.get("process")
    if proc is not None and hasattr(proc, "poll") and proc.poll() is None:
        try:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        except Exception:
            pass
    FOLDER_MONITOR["process"] = None
    # Get current file name before clearing
    current_file = FOLDER_MONITOR.get("current_file", "")
    current_path = FOLDER_MONITOR.get("current_path")
    # Cleanup partial results only for this file
    _cleanup_partial_analysis(current_file)
    # Delete the file currently being processed
    if current_path:
        try:
            Path(current_path).unlink()
        except Exception:
            pass
    FOLDER_MONITOR["current_file"] = ""
    FOLDER_MONITOR["current_path"] = None
    FOLDER_MONITOR["stage"] = "idle"
    FOLDER_MONITOR["status_detail"] = ""
    FOLDER_MONITOR["risk_level"] = "none"
    FOLDER_MONITOR["risk_segments"] = 0
    FOLDER_MONITOR["high_risk_count"] = 0
    FOLDER_MONITOR["medium_risk_count"] = 0
    FOLDER_MONITOR["low_risk_count"] = 0
    FOLDER_MONITOR["log_tail"] = ""


def get_folder_monitor_status() -> Dict[str, Any]:
    elapsed = 0.0
    start = FOLDER_MONITOR.get("analysis_start_time", 0)
    if start > 0:
        elapsed = time.perf_counter() - start
    return {
        "running": FOLDER_MONITOR["running"],
        "watch_dir": FOLDER_MONITOR.get("watch_dir", ""),
        "current_file": FOLDER_MONITOR["current_file"],
        "message": FOLDER_MONITOR["message"],
        "processed": FOLDER_MONITOR["processed_count"],
        "errors": FOLDER_MONITOR["error_count"],
        "skipped": FOLDER_MONITOR["skipped_count"],
        "video_size": FOLDER_MONITOR.get("current_video_size", 0),
        "video_duration": FOLDER_MONITOR.get("current_video_duration", 0.0),
        "current_chunk": FOLDER_MONITOR.get("current_chunk", 0),
        "total_chunks": FOLDER_MONITOR.get("total_chunks", 0),
        "elapsed_seconds": elapsed,
        "stage": FOLDER_MONITOR.get("stage", "idle"),
        "status_detail": FOLDER_MONITOR.get("status_detail", ""),
        "risk_level": FOLDER_MONITOR.get("risk_level", "none"),
        "risk_segments": FOLDER_MONITOR.get("risk_segments", 0),
        "high_risk_count": FOLDER_MONITOR.get("high_risk_count", 0),
        "medium_risk_count": FOLDER_MONITOR.get("medium_risk_count", 0),
        "low_risk_count": FOLDER_MONITOR.get("low_risk_count", 0),
        "log_tail": FOLDER_MONITOR.get("log_tail", ""),
    }


def available_server_videos() -> List[Path]:
    srv = _server_video_dir()
    if not srv.exists() or not srv.is_dir():
        return []
    videos: List[Path] = []
    for pattern in ("*.mp4", "*.mpeg", "*.mpg", "*.mov"):
        videos.extend(srv.glob(pattern))
    return sorted(
        [path for path in videos if path.is_file() and path.stat().st_size > 0],
        key=lambda path: path.name.lower(),
    )


def use_server_video(source_path: Path) -> None:
    source_path = Path(source_path)
    if not source_path.exists() or not source_path.is_file() or source_path.stat().st_size <= 0:
        raise RuntimeError(f"Video không hợp lệ: {source_path}")

    free_bytes = shutil.disk_usage(str(STATIC_DIR)).free
    reserve_bytes = 2 * 1024 * 1024 * 1024
    required_bytes = source_path.stat().st_size + reserve_bytes
    if free_bytes < required_bytes:
        raise RuntimeError(f"Không đủ dung lượng đĩa. Cần tối thiểu ~{required_bytes / (1024**3):.1f}GB.")

    with source_path.open("rb") as src, VIDEO_PATH.open("wb") as dst:
        shutil.copyfileobj(src, dst, length=16 * 1024 * 1024)

    if RESULT_PATH.exists():
        RESULT_PATH.unlink()
    st.session_state.video_token = f"{source_path.name}:{source_path.stat().st_size}"
    st.session_state.last_analysis_report = None


def _run_analysis_subprocess(video_path: Path, progress_callback: Any = None) -> Tuple[bool, Path, float, List[str]]:
    """Run analysis subprocess without UI. Returns (ok, log_path, elapsed_seconds, logs)."""
    started_at = time.perf_counter()
    backend = os.getenv("COSMOS_MODEL_BACKEND", "vllm").lower()
    run_in_wsl = _should_run_in_wsl(backend)
    python_exe = APP_DIR / "local_env" / ".venv" / "Scripts" / "python.exe"
    if not python_exe.exists():
        python_exe = Path(sys.executable)

    for folder in [
        APP_DIR / "local_env" / "pip_temp",
        APP_DIR / "local_env" / "pip_cache",
        APP_DIR / "local_env" / "hf_cache",
        APP_DIR / "local_env" / "torch_cache",
    ]:
        folder.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUNBUFFERED"] = "1"
    env["TEMP"] = str(APP_DIR / "local_env" / "pip_temp")
    env["TMP"] = str(APP_DIR / "local_env" / "pip_temp")
    env["PIP_CACHE_DIR"] = str(APP_DIR / "local_env" / "pip_cache")
    env["HF_HOME"] = str(APP_DIR / "local_env" / "hf_cache")
    env["HUGGINGFACE_HUB_CACHE"] = str(APP_DIR / "local_env" / "hf_cache" / "hub")
    env["TRANSFORMERS_CACHE"] = str(APP_DIR / "local_env" / "hf_cache" / "transformers")
    env["SENTENCE_TRANSFORMERS_HOME"] = str(APP_DIR / "local_env" / "hf_cache" / "sentence_transformers")
    env["TORCH_HOME"] = str(APP_DIR / "local_env" / "torch_cache")
    env["CUDA_MODULE_LOADING"] = "LAZY"
    env["PYTORCH_CUDA_ALLOC_CONF"] = "garbage_collection_threshold:0.85,max_split_size_mb:256"
    env["TRANSFORMERS_VERBOSITY"] = "error"
    env["TOKENIZERS_PARALLELISM"] = "false"
    env["OMP_NUM_THREADS"] = os.getenv("OMP_NUM_THREADS", "8")
    env["MKL_NUM_THREADS"] = os.getenv("MKL_NUM_THREADS", "8")

    args = _analysis_args(video_path, run_in_wsl=run_in_wsl)
    if run_in_wsl:
        command = _wsl_command(args)
    else:
        command = [str(python_exe), "main.py", *args]

    log_path = OUTPUTS_DIR / f"ui_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
    process = subprocess.Popen(
        command,
        cwd=str(APP_DIR),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        bufsize=1,
    )
    FOLDER_MONITOR["process"] = process

    logs: List[str] = []
    try:
        with log_path.open("w", encoding="utf-8") as log_file:
            log_file.write(f"Command: {' '.join(command)}\n")
            log_file.write(f"Video: {video_path}\n\n")
            log_file.flush()
            if process.stdout is not None:
                for line in process.stdout:
                    line_stripped = line.rstrip()
                    logs.append(line_stripped)
                    log_file.write(line)
                    log_file.flush()
                    if progress_callback:
                        try:
                            progress_callback(line_stripped)
                        except Exception:
                            pass
            ok = process.wait() == 0
            log_file.write(f"\nExit code: {process.returncode}\n")
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=10)

    elapsed_seconds = time.perf_counter() - started_at
    return ok, log_path, elapsed_seconds, logs


def run_analysis(video_path: Path) -> bool:
    started_at = time.perf_counter()
    file_size_bytes = video_path.stat().st_size if video_path.exists() else 0
    if not video_path.exists() or not video_path.is_file() or file_size_bytes <= 0:
        st.session_state.last_analysis_report = {
            "ok": False,
            "elapsed_seconds": 0.0,
            "segment_count": 0,
            "file_size_bytes": file_size_bytes,
            "video_path": str(video_path),
            "error": "Video đầu vào không tồn tại hoặc đang rỗng 0 byte.",
        }
        st.error("Video đầu vào không hợp lệ hoặc rỗng 0 byte. Hãy upload video MP4 hợp lệ trước khi phân tích.")
        return False

    st.session_state.is_loading = True
    st.session_state.analysis_progress = {"percent": 0.0, "completed": 0, "total": 0, "stage": "Đang khởi tạo phân tích"}
    progress_slot = st.empty()
    status_slot = st.empty()
    progress_bar = progress_slot.progress(0, text="Đang khởi tạo phân tích…")

    def update_progress(line: str) -> None:
        current = st.session_state.analysis_progress
        preparing = re.search(r"Preparing video chunks:\s*(\d+)\s*/\s*(\d+)", line)
        if preparing:
            prepared_count, prepared_total = int(preparing.group(1)), max(1, int(preparing.group(2)))
            percent = min(15.0, prepared_count / prepared_total * 15.0)
            stage = f"Đang chuẩn bị video · {prepared_count}/{prepared_total} đoạn"
            st.session_state.analysis_progress = {
                "percent": percent, "completed": 0, "total": 0, "stage": stage
            }
            progress_bar.progress(int(percent), text=stage)
            status_slot.caption(f"FFmpeg đang chuẩn bị đoạn {prepared_count}/{prepared_total}")
            return
        completed, total = _parse_analysis_progress(line, int(current.get("completed", 0)), int(current.get("total", 0)))
        lowered = line.lower()
        stage = current.get("stage", "Đang phân tích")
        for keyword, label in (("prepared", "Đang chuẩn bị phân đoạn"), ("saved segment", "Đang phân tích phân đoạn"), ("summar", "Đang tóm tắt"), ("index", "Đang lập chỉ mục")):
            if keyword in lowered:
                stage = label
                break
        percent = 15.0 + (_analysis_percent(completed, total) * 0.85) if total else 15.0
        st.session_state.analysis_progress = {"percent": percent, "completed": completed, "total": total, "stage": stage}
        progress_bar.progress(int(percent), text=f"{stage} · {completed}/{total} phân đoạn" if total else stage)
        status_slot.caption(f"Tiến trình thực: {completed}/{total} phân đoạn" if total else "Đang chờ hệ thống xác định số phân đoạn…")

    try:
        ok, log_path, elapsed_seconds, logs = _run_analysis_subprocess(video_path, progress_callback=update_progress)
    finally:
        st.session_state.is_loading = False
        progress_slot.empty()
        status_slot.empty()
    result_data = load_result() if ok and RESULT_PATH.exists() else {}
    segment_count = len(get_segments(result_data)) if result_data else 0
    report = {
        "ok": ok,
        "elapsed_seconds": elapsed_seconds,
        "segment_count": segment_count,
        "file_size_bytes": file_size_bytes,
        "video_path": str(video_path),
        "log_path": str(log_path),
        "error": "" if ok else (logs[-1] if logs else "Process phân tích kết thúc lỗi trước khi có log."),
    }
    st.session_state.last_analysis_report = report
    if ok:
        st.success(_format_analysis_report(report))
        st.toast("Phân tích video đã hoàn tất", icon=":material/check_circle:")
        ensure_history_snapshot()
    else:
        st.error(f"Phân tích thất bại sau {_format_duration(elapsed_seconds)}. Xem console để biết chi tiết.")

    return ok


def _parse_analysis_progress(line: str, completed_segments: int, total_segments: int) -> Tuple[int, int]:
    prepared_match = re.search(r"Prepared\s+(\d+)\s+segment", line)
    if prepared_match:
        return completed_segments, int(prepared_match.group(1))

    match = re.search(r"Saved segment\s+(\d+)\s*/\s*(\d+)", line)
    if not match:
        return completed_segments, total_segments
    completed = int(match.group(1))
    total = int(match.group(2))
    # Clamp to avoid false positives from stale/repeated log lines
    completed = min(completed, total)
    completed = max(completed, completed_segments)
    return completed, total


def _render_console_html(text: str, height: int) -> str:
    return (
        f"<pre style=\"height:{int(height)}px; overflow:auto; white-space:pre-wrap; "
        "background:#11110f; color:#f5f1e8; border:1px solid #d8ded3; "
        "border-radius:8px; padding:12px; font-size:12px; line-height:1.45;\">"
        f"{escape(text)}"
        "</pre>"
    )


def _analysis_percent(completed_segments: int, total_segments: int) -> float:
    if total_segments <= 0:
        return 0.0
    return min(100.0, max(0.0, completed_segments / total_segments * 100.0))


def _format_analysis_report(report: Dict[str, Any]) -> str:
    return (
        f"Hoàn tất trong {_format_duration(float(report.get('elapsed_seconds', 0)))}. "
        f"Số phân đoạn: {int(report.get('segment_count', 0))}. "
        f"Kích thước video: {_format_bytes(int(report.get('file_size_bytes', 0)))}."
    )


def _format_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours} giờ {minutes} phút {secs} giây"
    if minutes:
        return f"{minutes} phút {secs} giây"
    return f"{secs} giây"


def _format_bytes(value: int) -> str:
    size = float(max(0, value))
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if size < 1024 or unit == "TB":
            return f"{size:.2f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.2f} TB"


def _append_optional_arg(command: List[str], flag: str, env_name: str) -> None:
    value = os.getenv(env_name)
    if value:
        command.extend([flag, value])


def _is_playback_video(video_path: Path) -> bool:
    try:
        return video_path.resolve().parent == PLAYBACK_INBOX.resolve()
    except OSError:
        return False


def _append_analysis_tuning(args: List[str], video_path: Path) -> None:
    if _is_playback_video(video_path):
        mode = os.getenv("COSMOS_PLAYBACK_MODE", "fast").strip().lower()
        profiles = {
            "fast": {
                "chunk_seconds": "90",
                "sample_fps": "0.025",
                "max_new_tokens": "192",
                "max_image_side": "768",
            },
            "balanced": {
                "chunk_seconds": "30",
                "sample_fps": "0.1",
                "max_new_tokens": "192",
                "max_image_side": "960",
            },
            "detail": {
                "chunk_seconds": "15",
                "sample_fps": "0.2",
                "max_new_tokens": "256",
                "max_image_side": "1280",
            },
        }
        selected = profiles.get(mode, profiles["fast"])
        tuning = (
            ("--chunk-seconds", "COSMOS_PLAYBACK_CHUNK_SECONDS", selected["chunk_seconds"]),
            ("--sample-fps", "COSMOS_PLAYBACK_SAMPLE_FPS", selected["sample_fps"]),
            ("--max-new-tokens", "COSMOS_PLAYBACK_MAX_NEW_TOKENS", selected["max_new_tokens"]),
            ("--chunk-encoder", "COSMOS_PLAYBACK_CHUNK_ENCODER", "copy"),
            ("--max-image-side", "COSMOS_PLAYBACK_MAX_IMAGE_SIDE", selected["max_image_side"]),
            ("--cleanup-every", "COSMOS_PLAYBACK_CLEANUP_EVERY", "1"),
            ("--device-map", "COSMOS_PLAYBACK_DEVICE_MAP", "cuda:0"),
        )
        for flag, env_name, default in tuning:
            args.extend([flag, os.getenv(env_name, default)])
        if os.getenv("COSMOS_PLAYBACK_DIRECT_SAMPLING", "1").strip().lower() not in {"0", "false", "no"}:
            args.append("--direct-sampling")
        return
    _append_optional_arg(args, "--chunk-seconds", "COSMOS_CHUNK_SECONDS")
    _append_optional_arg(args, "--sample-fps", "COSMOS_SAMPLE_FPS")
    _append_optional_arg(args, "--max-new-tokens", "COSMOS_MAX_NEW_TOKENS")
    _append_optional_arg(args, "--chunk-encoder", "COSMOS_CHUNK_ENCODER")


def _analysis_args(video_path: Path, run_in_wsl: bool) -> List[str]:
    def p(path: Path) -> str:
        return _to_wsl_path(path) if run_in_wsl else str(path)

    args = [
        "--video",
        p(video_path),
        "--model",
        os.getenv("COSMOS_MODEL", "nvidia/Cosmos-Reason2-2B"),
        "--hardware-profile",
        os.getenv("COSMOS_HARDWARE_PROFILE", "rtx5070ti_16gb"),
        "--output",
        p(RESULT_PATH),
        "--chunks-dir",
        p(OUTPUTS_DIR / "chunks"),
        "--vector-db",
        p(VECTOR_DB_DIR),
    ]
    _append_analysis_tuning(args, video_path)
    _append_optional_arg(args, "--dtype", "COSMOS_DTYPE")
    _append_optional_arg(args, "--attn-implementation", "COSMOS_ATTN_IMPLEMENTATION")
    _append_optional_arg(args, "--model-backend", "COSMOS_MODEL_BACKEND")
    _append_optional_arg(args, "--gpu-memory-utilization", "COSMOS_GPU_MEMORY_UTILIZATION")
    _append_optional_arg(args, "--max-model-len", "COSMOS_MAX_MODEL_LEN")
    _append_optional_arg(args, "--vllm-batch-size", "COSMOS_VLLM_BATCH_SIZE")
    return args


def _should_run_in_wsl(backend: str) -> bool:
    if backend != "vllm":
        return False
    try:
        subprocess.run(
            ["wsl.exe", "--help"],
            capture_output=True,
            timeout=5,
        )
        return True
    except Exception:
        return False


def _wsl_command(args: List[str]) -> List[str]:
    wsl_app_dir = _to_wsl_path(APP_DIR)
    wsl_python = os.getenv("COSMOS_WSL_PYTHON", "~/cosmos_vllm_venv/bin/python")
    quoted = " ".join(shlex.quote(item) for item in ["main.py", *args])
    script = (
        "set -e; "
        f"cd {shlex.quote(wsl_app_dir)}; "
        'export PATH="$HOME/cosmos_vllm_venv/bin:$PATH"; '
        "export PYTHONUNBUFFERED=1; "
        f"export HF_HOME={shlex.quote(_to_wsl_path(APP_DIR / 'local_env' / 'hf_cache'))}; "
        f"export HUGGINGFACE_HUB_CACHE={shlex.quote(_to_wsl_path(APP_DIR / 'local_env' / 'hf_cache' / 'hub'))}; "
        f"export SENTENCE_TRANSFORMERS_HOME={shlex.quote(_to_wsl_path(APP_DIR / 'local_env' / 'hf_cache' / 'sentence_transformers'))}; "
        f"{wsl_python} {quoted}"
    )
    return ["wsl.exe", "--cd", wsl_app_dir, "--", "bash", "-lc", script]


def _to_wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    tail = resolved.as_posix().split(":", 1)[-1]
    return f"/mnt/{drive}{tail}"


def _from_wsl_path(value: str) -> str:
    normalized = clean_text(value).replace("\\", "/")
    if not normalized.startswith("/mnt/") or len(normalized) < 7:
        return value
    drive = normalized[5]
    if normalized[6] != "/":
        return value
    return f"{drive.upper()}:{normalized[6:]}".replace("/", "\\")


def _event_seconds(seg: Dict[str, Any], start: str) -> int:
    value = seg.get("start_seconds")
    try:
        return int(float(value))
    except Exception:
        return hhmmss_to_seconds(start)


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def _format_summary_answer(summary: Dict[str, Any], query: str) -> str:
    score = summary.get("score")
    score_text = f" Độ khớp tóm tắt: {score:.3f}." if isinstance(score, (int, float)) else ""
    return clean_text(
        f"Câu hỏi: {query}. "
        f"{summary.get('overview', '')} "
        f"{summary.get('meaning', '')}"
        f"{score_text}"
    )


def history_result_files() -> List[Path]:
    candidates = []
    candidates.extend(HISTORY_DIR.glob("*.json"))
    candidates.extend(OUTPUTS_DIR.glob("*.json"))

    latest_by_video_id: Dict[str, Path] = {}
    anonymous_files: List[Path] = []
    seen = set()
    for path in candidates:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, dict) or not get_segments(data):
            continue

        video_id = clean_text(data.get("video_id", ""))
        if not video_id:
            anonymous_files.append(path)
            continue

        current = latest_by_video_id.get(video_id)
        if current is None or path.stat().st_mtime > current.stat().st_mtime:
            latest_by_video_id[video_id] = path

    result_files = [*latest_by_video_id.values(), *anonymous_files]

    return sorted(result_files, key=lambda p: p.stat().st_mtime, reverse=True)


def load_history_items() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for path in history_result_files():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        items.append(
            {
                "path": path,
                "video_id": clean_text(data.get("video_id", path.stem)),
                "video_file": clean_text(data.get("video_file", "")),
                "segment_count": len(get_segments(data)),
                "summary": data.get("video_summary", {}),
                "data": data,
            }
        )
    return items


def render_global_search_tab() -> None:
    st.subheader(":material/manage_search: Tìm kiếm trên toàn bộ lịch sử video")
    query = st.text_area(
        "Câu hỏi",
        value="đoạn nào có nhiều người tụ tập hoặc sử dụng điện thoại",
        height=90,
        key="global_query",
    )
    limit = st.slider("Số đoạn trả về", min_value=3, max_value=30, value=10, key="global_limit")
    mode = st.radio(
        "Chế độ tìm kiếm",
        options=["hybrid_lancedb", "openai_metadata"],
        format_func=lambda x: "Hybrid LanceDB (vector + metadata)" if x == "hybrid_lancedb" else "LLM trên metadata",
        key="global_mode",
    )

    if st.button("Tìm trên lịch sử", icon=":material/search:", type="primary", width="stretch", key="global_search_btn"):
        with st.spinner("Đang tìm trên toàn bộ lịch sử..."):
            events, answer = semantic_search_global(query, limit, mode)
            st.session_state.global_search_events = events
            st.session_state.global_search_answer = answer

    if st.button("Lập chỉ mục lại toàn bộ lịch sử", icon=":material/sync:", width="stretch", key="global_reindex_btn"):
        info = rebuild_vector_index()
        st.success(f"Đã index {info.get('count', 0)} segment.", icon=":material/check_circle:")

    if st.session_state.global_search_answer:
        st.info(st.session_state.global_search_answer, icon=":material/info:")
    events = st.session_state.global_search_events
    if events:
        render_search_results(events)
    else:
        st.caption("Chưa có kết quả tìm kiếm.")


def semantic_search_global(query: str, limit: int, mode: str) -> Tuple[EventList, str]:
    if not clean_text(query):
        return [], "Vui lòng nhập câu hỏi tìm kiếm."

    history_items = load_history_items()
    if not history_items:
        return [], "Chưa có lịch sử phân tích. Hãy phân tích ít nhất một video trước khi tìm kiếm."

    if mode == "openai_metadata":
        segments: List[Dict[str, Any]] = []
        for item in history_items:
            segments.extend(get_segments(item.get("data", {})))
        return _search_with_openai_metadata({"segments": segments}, query, limit)

    try:
        result = search_video(
            query=query,
            db_dir=VECTOR_DB_DIR,
            segment_table_name=DEFAULT_TABLE_NAME,
            summary_table_name=DEFAULT_SUMMARY_TABLE_NAME,
            embedding_model=DEFAULT_EMBEDDING_MODEL,
            video_id=None,
            limit=limit,
        )
    except Exception as first_exc:
        try:
            index_info = rebuild_vector_index()
            if not index_info.get("indexed"):
                return [], f"Chưa lập được chỉ mục lịch sử: {index_info.get('reason', 'unknown')}"
            result = search_video(
                query=query,
                db_dir=VECTOR_DB_DIR,
                segment_table_name=DEFAULT_TABLE_NAME,
                summary_table_name=DEFAULT_SUMMARY_TABLE_NAME,
                embedding_model=DEFAULT_EMBEDDING_MODEL,
                video_id=None,
                limit=limit,
            )
        except Exception as second_exc:
            return [], f"Tìm kiếm LanceDB lỗi: {first_exc}. Reindex cũng lỗi: {second_exc}"

    events = [event for item in result.get("segment_matches", []) if (event := make_event(item))]
    summary_matches = result.get("summary_matches", [])
    answer = _format_summary_answer(summary_matches[0], query) if summary_matches else f"Tìm thấy {len(events)} đoạn phù hợp."
    return events, answer


def render_history_tab() -> None:
    st.subheader("Danh sách video đã phân tích")
    items = load_history_items()
    if not items:
        st.caption("Chưa có lịch sử phân tích.")
        return

    for idx, item in enumerate(items):
        summary = item.get("summary", {}) or {}
        c1, c2 = st.columns([3, 1], vertical_alignment="center")
        with c1:
            st.markdown(f"**{item.get('video_id', 'n/a')}**")
            st.caption(f"{item.get('video_file', 'n/a')} | segments: {item.get('segment_count', 0)}")
            st.write(clean_text(summary.get("overview", ""))[:280])
        with c2:
            if st.button("Xem chi tiết", key=f"history_detail_{idx}", width="stretch"):
                show_video_history_dialog(item)


@st.dialog("Chi tiết video đã phân tích")
def show_video_history_dialog(item: Dict[str, Any]) -> None:
    data = item.get("data", {})
    st.markdown(f"**Video ID:** `{item.get('video_id', 'n/a')}`")
    st.caption(item.get("video_file", "n/a"))
    segments = get_segments(data)
    if not segments:
        st.caption("Không có phân đoạn.")
        return

    rows = []
    for seg in segments:
        rows.append(
            {
                "Bắt đầu": clean_text(seg.get("start", "")),
                "Kết thúc": clean_text(seg.get("end", "")),
                "Rủi ro": clean_text(seg.get("risk_level", "none")),
                "Chú thích": clean_text(seg.get("description", "")),
            }
        )
    st.dataframe(rows, width="stretch", hide_index=True)

    st.markdown("**Preview các phân đoạn**")
    for i, seg in enumerate(segments[:12]):
        st.markdown(
            f"`#{i+1}` {clean_text(seg.get('start',''))} -> {clean_text(seg.get('end',''))}: "
            f"{clean_text(seg.get('description',''))}"
        )
        chunk = _resolve_media_path(clean_text(seg.get("chunk_path", "")))
        if chunk:
            st.video(str(chunk), format="video/mp4")


def _resolve_media_path(path_value: str) -> Path | None:
    raw = clean_text(path_value)
    if not raw:
        return None
    raw = _from_wsl_path(raw)
    normalized = raw.replace("\\", "/")
    candidates = [Path(raw), Path(normalized), APP_DIR / raw, APP_DIR / normalized]
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
        except OSError:
            continue
    return None


def render_search_results(events: EventList) -> None:
    st.markdown("**Kết quả tìm kiếm**")
    header = st.columns([1.3, 0.65, 0.65, 0.55, 3.2], vertical_alignment="center")
    header[0].markdown("**Video ID**")
    header[1].markdown("**Bắt đầu**")
    header[2].markdown("**Kết thúc**")
    header[3].markdown("**Rủi ro**")
    header[4].markdown("**Chú thích**")

    for index, event in enumerate(events):
        cols = st.columns([1.3, 0.65, 0.65, 0.55, 3.2], vertical_alignment="center")
        video_id = clean_text(event.get("video_id", "")) or "unknown"
        if cols[0].button(video_id, key=f"global_result_video_{index}", width="stretch"):
            show_search_event_dialog(event)
        cols[1].write(clean_text(event.get("start", "")))
        cols[2].write(clean_text(event.get("end", "")))
        cols[3].write(clean_text(event.get("risk_level", "none")))
        cols[4].write(clean_text(event.get("desc", "")))


@st.dialog("Xem kết quả video")
def show_search_event_dialog(event: Dict[str, Any]) -> None:
    video_id = clean_text(event.get("video_id", "")) or "unknown"
    start = clean_text(event.get("start", ""))
    end = clean_text(event.get("end", ""))
    start_seconds = int(event.get("sec", 0) or 0)

    st.markdown(f"**Video ID:** `{video_id}`")
    st.caption(f"{start} -> {end} | Rủi ro: {clean_text(event.get('risk_level', 'none'))}")
    st.write(clean_text(event.get("desc", "")))

    chunk = _resolve_media_path(clean_text(event.get("chunk_path", "")))
    full_video = _resolve_media_path(clean_text(event.get("video_file", "")))

    if chunk:
        st.markdown("**Phân đoạn**")
        st.video(str(chunk), format="video/mp4")
    elif full_video:
        st.markdown("**Video gốc tại thời điểm tìm thấy**")
        try:
            st.video(str(full_video), format="video/mp4", start_time=max(0, start_seconds))
        except TypeError:
            st.video(str(full_video), format="video/mp4")
    else:
        st.warning("Không tìm thấy file video hoặc chunk tương ứng trên máy.")

    if full_video and chunk:
        with st.expander("Xem video gốc"):
            try:
                st.video(str(full_video), format="video/mp4", start_time=max(0, start_seconds))
            except TypeError:
                st.video(str(full_video), format="video/mp4")


def _events_table(events: EventList) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for i, event in enumerate(events, start=1):
        rows.append(
            {
                "STT": i,
                "Video ID": clean_text(event.get("video_id", "")),
                "Bắt đầu": clean_text(event.get("start", "")),
                "Kết thúc": clean_text(event.get("end", "")),
                "Rủi ro": clean_text(event.get("risk_level", "none")),
                "Chú thích": clean_text(event.get("desc", "")),
            }
        )
    return rows



def _search_with_openai_metadata(data: Dict[str, Any], query: str, limit: int) -> Tuple[EventList, str]:
    api_key = os.getenv("OPENAI_API_KEY")
    base_url = os.getenv("OPENAI_BASE_URL", "https://llm.chiasegpu.vn/v1").rstrip("/")
    model_name = os.getenv("OPENAI_SEARCH_MODEL", "ai_model")
    segments = get_segments(data)
    if not api_key:
        return [], "Thiếu API key nên chưa thể tìm bằng LLM metadata."
    if not segments:
        return [], "Không có segment metadata để tìm kiếm."

    candidates = []
    for idx, seg in enumerate(segments):
        candidates.append(
            {
                "i": idx,
                "start": clean_text(seg.get("start", "")),
                "end": clean_text(seg.get("end", "")),
                "description": clean_text(seg.get("description", "")),
                "risk_level": clean_text(seg.get("risk_level", "none")),
                "abnormal": bool(seg.get("abnormal", False)),
                "phone_detected": bool(seg.get("phone_detected", False)),
                "crowd_detected": bool(seg.get("crowd_detected", False)),
            }
        )

    try:
        from openai import OpenAI

        client = OpenAI(api_key=api_key, base_url=base_url)
        prompt = (
            "Bạn là bộ xếp hạng tìm kiếm video từ metadata. "
            "Chọn các segment phù hợp câu hỏi nhất. "
            "Trả về JSON đúng dạng: {\"indices\":[...],\"answer\":\"...\"}. "
            f"Giới hạn tối đa {max(1, int(limit))} chỉ số. "
            "Chỉ dùng thông tin đã cho, không bịa."
        )
        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": json.dumps({"query": query, "segments": candidates}, ensure_ascii=False),
            },
        ]
        try:
            completion = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0,
                response_format={"type": "json_object"},
            )
        except Exception:
            completion = client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=0,
            )
        raw = completion.choices[0].message.content or "{}"
        parsed = _loads_llm_json(raw)
        indices = parsed.get("indices") if isinstance(parsed, dict) else []
        answer = clean_text(parsed.get("answer", "")) if isinstance(parsed, dict) else ""
    except Exception as exc:
        return [], f"Tìm kiếm LLM metadata lỗi ({base_url}, model={model_name}): {exc}"

    picked: EventList = []
    for idx in indices if isinstance(indices, list) else []:
        try:
            i = int(idx)
        except Exception:
            continue
        if i < 0 or i >= len(segments):
            continue
        event = make_event(segments[i])
        if event:
            picked.append(event)
        if len(picked) >= max(1, int(limit)):
            break

    return picked, answer or f"Tìm thấy {len(picked)} đoạn phù hợp theo LLM metadata."


def _loads_llm_json(raw: str) -> Dict[str, Any]:
    cleaned = clean_text(raw)
    try:
        value = json.loads(cleaned)
        return value if isinstance(value, dict) else {}
    except Exception:
        pass
    match = re.search(r"\{.*\}", cleaned, flags=re.DOTALL)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}
if __name__ == "__main__":
    main()
