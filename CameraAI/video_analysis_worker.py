"""Manual background analysis of representative frames from an event clip."""

import json
import math
import queue
import threading
import time
import zipfile
from datetime import datetime, timedelta
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional

import cv2
import requests

import config
import database
from clip_storage import resolve_clip_path
from gemini_video_report import build_vietnamese_fallback, generate_final_video_report


_RISK_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3}


class VideoAnalysisWorker:
    def __init__(self, on_updated: Optional[Callable[[int], None]] = None):
        self._on_updated = on_updated
        self._queue: queue.Queue[Optional[tuple[int, int | None]]] = queue.Queue()
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True, name="video-analysis-worker")
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def enqueue(self, event_id: int, max_frames_per_window: int | None = None) -> None:
        if not self._thread or not self._thread.is_alive():
            self.start()
        print(f"[VIDEO AI] alert={event_id} analysis requested frames/window={max_frames_per_window or 'default'}")
        self._queue.put((event_id, max_frames_per_window))

    def _run(self) -> None:
        while self._running.is_set():
            try:
                event_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if event_id is None:
                continue
            event_id, max_frames_per_window = event_id
            try:
                self._process(event_id, max_frames_per_window=max_frames_per_window)
            except Exception as exc:
                print(f"[VIDEO AI] alert={event_id} failed: {exc}")
                self._set_status(event_id, "failed", error_message=str(exc))

    def _set_status(self, event_id: int, status: str, **values) -> None:
        database.update_video_analysis(event_id, status=status, **values)
        if self._on_updated:
            self._on_updated(event_id)

    def _process(self, event_id: int, max_frames_per_window: int | None = None) -> None:
        event = database.get_event_by_id(event_id)
        if not event:
            return
        saved_clip = str(event.get("clip_filename") or "")
        clip_path = resolve_clip_path(saved_clip) if saved_clip else None
        if clip_path is None or not clip_path.is_file():
            self._set_status(event_id, "video_missing", error_message="Không tìm thấy video evidence của cảnh báo.")
            return

        self._set_status(event_id, "extracting_frames", error_message=None)
        sequences = self._extract_adaptive_sequences(clip_path, max_frames_per_window=max_frames_per_window)
        if not sequences:
            self._set_status(event_id, "failed", error_message="Không đọc được frame nào từ video evidence.")
            return

        health_url = config.COSMOS_VIDEO_URL.rsplit("/", 1)[0] + "/health"
        try:
            health = requests.get(health_url, timeout=5)
            health_data = health.json() if health.ok else {}
        except requests.RequestException as exc:
            self._set_status(event_id, "failed", error_message=f"Cosmos chưa sẵn sàng: {exc}")
            return
        if health_data.get("status") != "ready":
            self._set_status(event_id, "failed", error_message=f"Cosmos chưa sẵn sàng: {health_data.get('status', health.status_code)}")
            return

        self._set_status(event_id, "analyzing_sequences")
        event_time = datetime.strptime(event["timestamp"], "%Y-%m-%d %H:%M:%S")
        results = []
        for sequence in sequences:
            window_start = sequence["start_seconds"]
            window_end = sequence["end_seconds"]
            captured_at = (event_time - timedelta(seconds=config.PRE_BUFFER_SEC) + timedelta(seconds=window_start)).astimezone()
            payload = self._analyze_sequence(sequence["frames"], event, captured_at, window_start, window_end)
            results.append({
                "window_start_seconds": window_start,
                "window_end_seconds": window_end,
                "frame_offsets_seconds": [offset for offset, _ in sequence["frames"]],
                "captured_at": captured_at.isoformat(timespec="seconds"),
                "inference_ms": payload.get("inference_ms"),
                "result": payload["result"],
            })

        aggregate = self._aggregate(results)
        audio_analysis = database.get_audio_analysis(event_id)
        gemini_report, gemini_model = generate_final_video_report(event, results, audio_analysis)
        final_report = gemini_report or build_vietnamese_fallback(results)
        aggregate["summary"] = final_report["summary"]
        aggregate["risk_level"] = final_report["risk_level"]
        if final_report["recommended_action"]:
            aggregate["summary"] += "\nKhuyến nghị: " + final_report["recommended_action"]
        self._set_status(
            event_id,
            "completed",
            summary=aggregate["summary"],
            risk_level=aggregate["risk_level"],
            events=aggregate["events"],
            frames=results,
            video_model=" + ".join(part for part in [health_data.get("video_model"), gemini_model] if part),
            analyzed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )
        # Keep the report in the existing suggestion field so both the main
        # event modal and /test-ai display the same Gemini conclusion.
        if gemini_report:
            if audio_analysis is None:
                database.create_audio_analysis(event_id, status="not_analyzed")
            database.update_audio_analysis(event_id, suggestion=gemini_report)
            if self._on_updated:
                self._on_updated(event_id)

    @staticmethod
    def _extract_adaptive_sequences(clip_path: Path, max_frames_per_window: int | None = None) -> list[dict]:
        """Split a clip into bounded temporal windows and retain diverse frames.

        We keep evenly spaced context frames plus frames with the largest visual
        change.  This is more useful for fights/falls than fixed offsets and
        prevents a long playback recording from overflowing the VLM context.
        """
        capture = cv2.VideoCapture(str(clip_path))
        try:
            fps = float(capture.get(cv2.CAP_PROP_FPS) or 0)
            frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            duration = frame_count / fps if fps > 0 and frame_count > 0 else 0.0
            if duration <= 0:
                return []
            frame_limit = config.VIDEO_ANALYSIS_MAX_FRAMES_PER_WINDOW if max_frames_per_window is None else int(max_frames_per_window)
            frame_limit = min(12, max(4, frame_limit))
            windows = []
            start = 0.0
            while start < duration:
                end = min(duration, start + config.VIDEO_ANALYSIS_WINDOW_SECONDS)
                frames = VideoAnalysisWorker._select_window_frames(
                    capture, start, end, frame_limit
                )
                if frames:
                    windows.append({"start_seconds": round(start, 3), "end_seconds": round(end, 3), "frames": frames})
                start = end
            return windows
        finally:
            capture.release()

    @staticmethod
    def _select_window_frames(capture, start: float, end: float, max_frames: int) -> list[tuple[float, bytes]]:
        duration = max(0.01, end - start)
        candidate_count = min(40, max(max_frames * 3, int(math.ceil(duration * 2))))
        candidates = []
        previous_gray = None
        for index in range(candidate_count):
            offset = start + (duration * index / max(1, candidate_count - 1))
            # OpenCV may seek one frame beyond EOF; clamp to a valid timestamp.
            capture.set(cv2.CAP_PROP_POS_MSEC, max(0.0, offset) * 1000)
            ok, frame = capture.read()
            if not ok or frame is None:
                continue
            preview = cv2.resize(frame, (160, 90), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(preview, cv2.COLOR_BGR2GRAY)
            motion = 0.0 if previous_gray is None else float(cv2.absdiff(gray, previous_gray).mean())
            previous_gray = gray
            candidates.append((offset, frame, motion))
        if not candidates:
            return []

        # First/last and evenly-spaced moments establish context; high-motion
        # candidates fill the remaining slots so short physical interactions are
        # less likely to be missed.
        selected_indexes = {0, len(candidates) - 1}
        base_count = min(4, max_frames)
        for index in range(base_count):
            selected_indexes.add(round(index * (len(candidates) - 1) / max(1, base_count - 1)))
        for index, _candidate in sorted(enumerate(candidates), key=lambda item: item[1][2], reverse=True):
            if len(selected_indexes) >= max_frames:
                break
            selected_indexes.add(index)

        frames = []
        for index in sorted(selected_indexes):
            offset, frame, _motion = candidates[index]
            encoded, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 90])
            if encoded:
                frames.append((round(offset, 3), buffer.tobytes()))
        return frames

    @staticmethod
    def _analyze_sequence(
        frames: list[tuple[float, bytes]], event: dict, captured_at: datetime, window_start: float, window_end: float
    ) -> dict:
        sequence_url = config.COSMOS_VIDEO_URL.rsplit("/", 1)[0] + "/analyze-sequence"
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            for index, (offset, jpeg_bytes) in enumerate(frames):
                bundle.writestr(f"{index:02d}_{offset:08.3f}.jpg", jpeg_bytes)
        headers = {
            "Content-Type": "application/zip",
            "X-Cosmos-Device-Id": str(config.NVR_HOST),
            "X-Cosmos-Channel": str(event["channel"]),
            "X-Cosmos-Captured-At": captured_at.isoformat(timespec="seconds"),
            "X-Cosmos-Analysis-Source": "event_clip",
            "X-Cosmos-Prompt-Profile": config.COSMOS_PROMPT_PROFILE,
            "X-Cosmos-Window-Start": str(round(window_start, 3)),
            "X-Cosmos-Window-End": str(round(window_end, 3)),
            "X-Cosmos-Frame-Offsets": json.dumps([offset for offset, _ in frames]),
        }
        response = None
        for attempt in range(3):
            response = requests.post(sequence_url, data=archive.getvalue(), headers=headers, timeout=180)
            if response.status_code != 429:
                break
            time.sleep(attempt + 1)
        if response is None or not response.ok:
            code = response.status_code if response is not None else "unknown"
            raise RuntimeError(f"Cosmos sequence analysis failed: HTTP {code}")
        payload = response.json()
        if payload.get("status") != "ok" or not isinstance(payload.get("result"), dict):
            raise RuntimeError(payload.get("detail", "Cosmos trả kết quả chuỗi video không hợp lệ."))
        return payload

    @staticmethod
    def _analyze_frame(jpeg_bytes: bytes, event: dict, captured_at: datetime) -> dict:
        """Legacy single-frame helper retained for integrations outside this worker."""
        headers = {
            "Content-Type": "application/octet-stream",
            "X-Cosmos-Device-Id": str(config.NVR_HOST),
            "X-Cosmos-Channel": str(event["channel"]),
            "X-Cosmos-Captured-At": captured_at.isoformat(timespec="seconds"),
            "X-Cosmos-Analysis-Source": "event_clip",
            "X-Cosmos-Prompt-Profile": config.COSMOS_PROMPT_PROFILE,
        }
        response = requests.post(config.COSMOS_VIDEO_URL, data=jpeg_bytes, headers=headers, timeout=90)
        if not response.ok:
            raise RuntimeError(f"Cosmos video analysis failed: HTTP {response.status_code}")
        payload = response.json()
        if payload.get("status") != "ok" or not isinstance(payload.get("result"), dict):
            raise RuntimeError(payload.get("detail", "Cosmos trả kết quả video không hợp lệ."))
        return payload

    @staticmethod
    def _aggregate(frames: list[dict]) -> dict:
        risk_level = "none"
        summaries = []
        max_counts = {}
        for frame in frames:
            result = frame["result"]
            risk = str(result.get("risk_level", "none")).lower()
            if _RISK_ORDER.get(risk, 0) > _RISK_ORDER[risk_level]:
                risk_level = risk
            summary = " ".join(str(result.get("summary", "")).split())
            if summary:
                start = frame.get("window_start_seconds")
                end = frame.get("window_end_seconds")
                prefix = f"[{start:.1f}s–{end:.1f}s] " if isinstance(start, (float, int)) and isinstance(end, (float, int)) else ""
                rendered = prefix + summary
                if rendered not in summaries:
                    summaries.append(rendered)
            for item in result.get("events", []):
                if not isinstance(item, dict):
                    continue
                label = str(item.get("label", "")).strip()
                try:
                    count = max(0, int(item.get("count", 0)))
                except (TypeError, ValueError):
                    continue
                if label:
                    max_counts[label] = max(max_counts.get(label, 0), count)
        return {
            "summary": "\n".join(summaries),
            "risk_level": risk_level,
            "events": [{"label": label, "count": count} for label, count in sorted(max_counts.items())],
        }
