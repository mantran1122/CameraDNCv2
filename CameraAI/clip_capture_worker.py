"""Background capture of video evidence; multi-threaded pool with stream copy & async NAS mirror."""

import concurrent.futures
import queue
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import config
import database
import video_clipper
from clip_storage import build_clip_reference, mirror_clip, resolve_clip_path, storage_timestamp


def ensure_disk_space(min_free_gb: float = 4.0, target_free_gb: float = 7.0) -> bool:
    """
    Guarantees the host filesystem NEVER exhausts space.
    If free disk space is below min_free_gb, automatically deletes the oldest
    unprotected video clips in config.CLIPS_DIR until target_free_gb is available.
    Returns True if safe to capture, False if critically low (< 1.5 GB).
    """
    try:
        clips_dir = Path(config.CLIPS_DIR).resolve()
        if not clips_dir.exists():
            clips_dir.mkdir(parents=True, exist_ok=True)
        stat = shutil.disk_usage(clips_dir)
        free_gb = stat.free / (1024 ** 3)
        if free_gb >= min_free_gb:
            return True

        print(f"[DISK GUARD] ⚠️ Low disk space ({free_gb:.2f} GB < {min_free_gb} GB). Emergency purging oldest clips...")
        protected_clips = set()
        try:
            protected_clips = database.get_protected_clip_filenames()
        except Exception:
            pass

        all_clips = []
        for p in clips_dir.rglob("*.mp4"):
            try:
                if p.name == "sample_valid.mp4" or p.name in protected_clips:
                    continue
                rel = p.relative_to(clips_dir).as_posix()
                if rel in protected_clips:
                    continue
                all_clips.append((p.stat().st_mtime, p))
            except Exception:
                continue

        all_clips.sort(key=lambda x: x[0])  # Oldest first
        purged = 0
        freed_bytes = 0

        for _, clip_path in all_clips:
            try:
                sz = clip_path.stat().st_size
                clip_path.unlink(missing_ok=True)
                purged += 1
                freed_bytes += sz
                cur_free = shutil.disk_usage(clips_dir).free / (1024 ** 3)
                if cur_free >= target_free_gb:
                    break
            except Exception:
                continue

        cur_free_gb = shutil.disk_usage(clips_dir).free / (1024 ** 3)
        print(f"[DISK GUARD] ✅ Purged {purged} old clips ({freed_bytes / (1024**2):.1f} MB freed). Free space now: {cur_free_gb:.2f} GB")
        return cur_free_gb >= 1.5
    except Exception as e:
        print(f"[DISK GUARD Warning] Error during disk check: {e}")
        return True


class ClipCaptureWorker:
    def __init__(self, on_updated: Optional[Callable[[int], None]] = None, max_workers: int = 4):
        self._on_updated = on_updated
        self._max_workers = max_workers
        self._queue: queue.Queue[Optional[int]] = queue.Queue()
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._capture_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None
        self._nas_executor: Optional[concurrent.futures.ThreadPoolExecutor] = None

    def start(self) -> None:
        self._running.set()
        if not self._capture_executor:
            self._capture_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=self._max_workers, thread_name_prefix="clip-capture"
            )
        if not self._nas_executor:
            self._nas_executor = concurrent.futures.ThreadPoolExecutor(
                max_workers=2, thread_name_prefix="nas-mirror"
            )
        self._thread = threading.Thread(target=self._run, daemon=True, name="clip-capture-dispatcher")
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=2)
        if self._capture_executor:
            self._capture_executor.shutdown(wait=False)
            self._capture_executor = None
        if self._nas_executor:
            self._nas_executor.shutdown(wait=False)
            self._nas_executor = None

    def clear_queue(self) -> int:
        """Purge all pending tasks in the queue immediately."""
        cleared = 0
        while not self._queue.empty():
            try:
                self._queue.get_nowait()
                cleared += 1
            except queue.Empty:
                break
        print(f"[ClipCaptureWorker] Purged {cleared} pending alert tasks from queue.")
        return cleared

    def enqueue(self, event_id: int) -> None:
        if not self._thread or not self._thread.is_alive():
            self.start()
        self._queue.put(event_id)

    def _run(self) -> None:
        while self._running.is_set():
            try:
                event_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if event_id is None:
                break
            if self._capture_executor:
                self._capture_executor.submit(self._safe_capture, event_id)

    def _safe_capture(self, event_id: int) -> None:
        try:
            self._capture(event_id)
        except Exception as exc:
            print(f"[CLIP Error] Exception in capture worker for alert={event_id}: {exc}")

    def _safe_mirror(self, event_id: int, clip_file: str) -> None:
        try:
            mirrored = mirror_clip(clip_file)
            if config.STORAGE_BACKEND == "synology":
                print(f"[CLIP NAS] alert={event_id} synology_mirrored={mirrored}")
        except Exception as exc:
            print(f"[CLIP NAS Warning] Failed to mirror clip={clip_file} to NAS: {exc}")

    def _capture(self, event_id: int) -> None:
        event = database.get_event_by_id(event_id)
        if not event:
            return
        saved = str(event.get("clip_filename") or "")
        if saved and resolve_clip_path(saved, fetch_remote=False).is_file():
            return

        try:
            event_time = datetime.strptime(event["timestamp"], "%Y-%m-%d %H:%M:%S")
        except Exception:
            event_time = datetime.now()

        # Stale Drop Policy: Drop events older than 60s to prevent queue backlog
        age_sec = (datetime.now() - event_time).total_seconds()
        if age_sec > 60:
            print(f"[CLIP] alert={event_id} skipped (stale event: {age_sec:.1f}s old)")
            database.update_audio_analysis(
                event_id,
                status="video_expired",
                error_message="Sự kiện quá hạn (>60 giây) trước khi kịp cắt video.",
            )
            return

        delay = max(0.0, min(1.0, 1.0 - age_sec))
        if delay > 0:
            time.sleep(delay)

        # Disk Guard: Check free disk space before cutting clip to protect OS & DB
        if not ensure_disk_space(min_free_gb=4.0, target_free_gb=7.0):
            print(f"[DISK GUARD] 🛑 Low disk space (<1.5GB)! Skipped clip capture for alert={event_id} to protect system.")
            database.update_audio_analysis(
                event_id,
                status="video_skipped",
                error_message="Tạm dừng trích xuất clip do ổ đĩa máy chủ sắp đầy.",
            )
            return

        print(f"[CLIP] alert={event_id} capturing 10s evidence")
        filename = build_clip_reference(event["channel"], storage_timestamp(), event_id)
        captured_file = None
        # Single pass: video_clipper.clip_event_video internally already executes
        # 4 different modes (stream copy -> re-encode -> live sub-stream -> live main-stream)
        captured = video_clipper.clip_event_video(
            channel=event["channel"],
            event_timestamp=event_time,
            output_filename=filename,
            event_type=event.get("event_type", "video_anomaly"),
            event_code=event.get("event_code", "Intrusion"),
        )
        if captured:
            captured_file = filename

        if captured_file:
            # 1. Update DB immediately so users and AI can view video instantly (< 5s)
            database.update_event_clip(event_id, captured_file)
            print(f"[CLIP] alert={event_id} evidence={captured_file} (saved locally)")

            # 2. Upload to NAS in independent background thread pool
            if self._nas_executor and config.STORAGE_BACKEND == "synology":
                self._nas_executor.submit(self._safe_mirror, event_id, captured_file)
        else:
            print(f"[CLIP] alert={event_id} evidence capture failed")
            database.update_audio_analysis(
                event_id,
                status="video_missing",
                error_message="Không thể tạo video evidence 10 giây cho cảnh báo.",
            )

        if self._on_updated:
            try:
                self._on_updated(event_id)
            except Exception as exc:
                print(f"[CLIP Update Error] {exc}")
