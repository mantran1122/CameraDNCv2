"""Background capture of video evidence; multi-threaded pool with stream copy & async NAS mirror."""

import concurrent.futures
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import config
import database
import video_clipper
from clip_storage import build_clip_reference, mirror_clip, resolve_clip_path, storage_timestamp


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

        # Stale Drop Policy: Drop events older than 15 minutes to prevent queue backlog
        age_sec = (datetime.now() - event_time).total_seconds()
        if age_sec > 15 * 60:
            print(f"[CLIP] alert={event_id} skipped (stale event: {age_sec / 60:.1f} mins old)")
            database.update_audio_analysis(
                event_id,
                status="video_expired",
                error_message="Sự kiện quá hạn (>15 phút) trước khi kịp cắt video.",
            )
            return

        delay = config.POST_BUFFER_SEC + config.CLIP_READY_DELAY_SEC - age_sec
        if 0 < delay <= 15:
            time.sleep(delay)

        print(f"[CLIP] alert={event_id} capturing 10s evidence")
        filename = build_clip_reference(event["channel"], storage_timestamp(), event_id)
        captured_file = None
        for attempt in range(1, 4):
            print(f"[CLIP] alert={event_id} capture attempt={attempt}/3")
            captured = video_clipper.clip_event_video(
                channel=event["channel"],
                event_timestamp=event_time,
                output_filename=filename,
                event_type=event.get("event_type", "video_anomaly"),
                event_code=event.get("event_code", "Intrusion"),
            )
            if captured:
                captured_file = filename
                break
            if attempt < 3:
                time.sleep(2)

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
