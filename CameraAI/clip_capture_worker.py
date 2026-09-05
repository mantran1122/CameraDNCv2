"""Background capture of video evidence; intentionally separate from audio analysis."""

import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import config
import database
import video_clipper
from clip_storage import build_clip_reference, resolve_clip_path


class ClipCaptureWorker:
    def __init__(self, on_updated: Optional[Callable[[int], None]] = None):
        self._on_updated = on_updated
        self._queue: queue.Queue[Optional[int]] = queue.Queue()
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True, name="clip-capture-worker")
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=2)

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
            if event_id is not None:
                self._capture(event_id)

    def _capture(self, event_id: int) -> None:
        event = database.get_event_by_id(event_id)
        if not event:
            return
        saved = str(event.get("clip_filename") or "")
        if saved and resolve_clip_path(saved).is_file():
            return
        event_time = datetime.strptime(event["timestamp"], "%Y-%m-%d %H:%M:%S")
        delay = config.POST_BUFFER_SEC + config.CLIP_READY_DELAY_SEC - (datetime.now() - event_time).total_seconds()
        if delay > 0:
            time.sleep(delay)
        print(f"[CLIP] alert={event_id} capturing 10s evidence")
        filename = build_clip_reference(event["channel"], event_time, event_id)
        for attempt in range(1, 4):
            print(f"[CLIP] alert={event_id} capture attempt={attempt}/3")
            captured = video_clipper.clip_event_video(
                channel=event["channel"], event_timestamp=event_time,
                output_filename=filename,
                event_type=event["event_type"], event_code=event["event_code"],
            )
            if captured:
                break
            filename = None
            if attempt < 3:
                time.sleep(5)
        if filename:
            database.update_event_clip(event_id, filename)
            print(f"[CLIP] alert={event_id} evidence={filename}")
        else:
            print(f"[CLIP] alert={event_id} evidence capture failed")
            database.update_audio_analysis(
                event_id,
                status="video_missing",
                error_message="Không thể tạo video evidence 10 giây cho cảnh báo.",
            )
        if self._on_updated:
            self._on_updated(event_id)
