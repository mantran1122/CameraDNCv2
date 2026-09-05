"""Background processing for audio attached to an NVR anomaly event."""

import hashlib
import json
import os
import queue
import subprocess
import tempfile
import threading
import time
import math
import wave
from array import array
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

import requests

import config
import database
from clip_storage import resolve_clip_path
from gemini_video_report import generate_final_video_report, get_gemini_public_config


class AudioAnalysisWorker:
    def __init__(self, on_updated: Optional[Callable[[int], None]] = None):
        self._on_updated = on_updated
        self._queue: queue.Queue[Optional[int]] = queue.Queue()
        self._running = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._running.set()
        self._thread = threading.Thread(target=self._run, daemon=True, name="audio-analysis-worker")
        self._thread.start()

    def stop(self) -> None:
        self._running.clear()
        self._queue.put(None)
        if self._thread:
            self._thread.join(timeout=2)
        self._thread = None

    def enqueue(self, event_id: int) -> None:
        # A configuration restart may have stopped the old worker while a
        # browser still has a modal open. Never leave that request in
        # ``processing`` merely because the consumer thread is gone.
        if not self._thread or not self._thread.is_alive():
            self.start()
        print(f"[AUDIO] alert={event_id} analysis requested")
        self._queue.put(event_id)

    def _run(self) -> None:
        while self._running.is_set():
            try:
                event_id = self._queue.get(timeout=0.5)
            except queue.Empty:
                continue
            if event_id is None:
                continue
            try:
                self._process(event_id)
            except Exception as exc:
                print(f"[AUDIO] alert={event_id} unhandled worker error: {exc}")
                self._set_status(event_id, "stt_failed", error_message=f"Audio worker lỗi: {exc}")

    def _set_status(self, event_id: int, status: str, **values) -> None:
        database.update_audio_analysis(event_id, status=status, **values)
        if self._on_updated:
            self._on_updated(event_id)

    def _process(self, event_id: int) -> None:
        event = database.get_event_by_id(event_id)
        if not event:
            return

        try:
            saved_clip = str(event.get("clip_filename") or "")
            clip_path = resolve_clip_path(saved_clip) if saved_clip else None
            if clip_path is None or not clip_path.is_file():
                self._set_status(event_id, "video_missing", error_message="Không tìm thấy video evidence của cảnh báo.")
                return

            print(f"[AUDIO] alert={event_id} video={clip_path}")
            self._set_status(event_id, "extracting_audio")
            if not self._has_audio_stream(clip_path):
                transcription = {"transcript": "", "speech_detected": 0, "ignored_reason": "no_audio_track"}
                print(f"[AUDIO] alert={event_id} audio_stream=false status=no_audio_track")
                self._set_status(event_id, "no_audio_track", **transcription)
                return

            wav_path = self._extract_wav(clip_path)
            try:
                audio_rms = self._wav_rms_dbfs(wav_path)
                print(f"[AUDIO] alert={event_id} audio_stream=true rms={audio_rms:.1f}dBFS")
                if audio_rms < -50:
                    self._set_status(event_id, "audio_too_quiet", audio_rms=audio_rms, ignored_reason="audio_too_quiet")
                    return
                self._transcribe(event_id, event, wav_path)
            finally:
                Path(wav_path).unlink(missing_ok=True)
        except Exception as exc:
            self._set_status(event_id, "stt_failed", error_message=str(exc))

    def _has_audio_stream(self, clip_path: Path) -> bool:
        result = subprocess.run(
            [config.FFPROBE_PATH, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(clip_path)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {result.stderr.strip() or result.returncode}")
        return bool(result.stdout.strip())

    def _extract_wav(self, clip_path: Path) -> str:
        handle, wav_path = tempfile.mkstemp(prefix="camera_audio_", suffix=".wav")
        os.close(handle)
        result = subprocess.run(
            [config.FFMPEG_PATH, "-y", "-i", str(clip_path), "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", wav_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        if result.returncode != 0 or not os.path.exists(wav_path) or os.path.getsize(wav_path) == 0:
            Path(wav_path).unlink(missing_ok=True)
            raise RuntimeError("Không thể tách WAV 16 kHz từ clip.")
        return wav_path

    @staticmethod
    def _wav_rms_dbfs(wav_path: str) -> float:
        with wave.open(wav_path, "rb") as wav_file:
            if wav_file.getsampwidth() != 2:
                raise RuntimeError("WAV không phải PCM 16-bit.")
            samples = array("h")
            samples.frombytes(wav_file.readframes(wav_file.getnframes()))
        if not samples:
            return -120.0
        rms = math.sqrt(sum(sample * sample for sample in samples) / len(samples))
        return 20 * math.log10(max(rms / 32768.0, 1e-6))

    def _transcribe(self, event_id: int, event: dict, wav_path: str) -> None:
        self._set_status(event_id, "transcribing")
        health_url = config.COSMOS_AUDIO_URL.rsplit("/", 1)[0] + "/health"
        try:
            health = requests.get(health_url, timeout=5)
            health_data = health.json() if health.ok else {}
        except requests.RequestException as exc:
            self._set_status(event_id, "stt_failed", error_message=f"Cosmos chưa sẵn sàng: {exc}")
            return
        if health_data.get("status") != "ready":
            self._set_status(event_id, "stt_failed", error_message=f"Cosmos chưa sẵn sàng: {health_data.get('status', health.status_code)}")
            return

        wav_bytes = Path(wav_path).read_bytes()
        headers = {
            "Content-Type": "application/octet-stream",
            "X-Cosmos-Device-Id": config.NVR_HOST,
            "X-Cosmos-Channel": str(event["channel"]),
            "X-Cosmos-Captured-At": event["timestamp"],
            "X-Cosmos-Audio-Source": "event_clip",
            "X-Cosmos-Audio-Sha256": hashlib.sha256(wav_bytes).hexdigest(),
        }
        response = requests.post(config.COSMOS_AUDIO_URL, data=wav_bytes, headers=headers, timeout=90)
        if not response.ok:
            self._set_status(event_id, "stt_failed", error_message=f"Cosmos transcription failed: HTTP {response.status_code}")
            return
        result = response.json()
        if result.get("status") != "ok":
            self._set_status(event_id, "stt_failed", error_message=result.get("detail", "Cosmos transcription failed"))
            return
        transcription = {
            "transcript": result.get("text", ""),
            "speech_detected": int(bool(result.get("speech_detected"))),
            "audio_rms": result.get("audio_rms"),
            "active_speech_seconds": result.get("active_speech_seconds"),
            "ignored_reason": result.get("ignored_reason"),
            "audio_model": result.get("audio_model"),
        }
        if not transcription["transcript"].strip() or not transcription["speech_detected"]:
            self._set_status(event_id, "no_speech_detected", **transcription)
            return
        self._set_status(event_id, "analyzing", **transcription)
        suggestion, suggestion_error = self._create_suggestion(event, transcription)
        if suggestion_error:
            self._set_status(event_id, "transcribed", error_message=suggestion_error)
            return
        self._set_status(
            event_id,
            "completed",
            suggestion=suggestion,
            # A suggestion outage must not discard a valid transcription or mark
            # the audio analysis itself as failed.
            error_message=suggestion_error,
            analyzed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )

    def _create_suggestion(self, event: dict, transcription: dict) -> tuple[Optional[dict], Optional[str]]:
        """Create a strictly evidence-grounded suggestion after transcription.

        Gemini is the primary final-report layer and combines the available
        Cosmos windows with PhoWhisper text.  The older OpenAI-compatible
        endpoint remains as an optional fallback for existing deployments.
        """
        gemini_config = get_gemini_public_config()
        if gemini_config["configured"]:
            video_analysis = database.get_video_analysis(int(event["id"])) if event.get("id") else None
            windows = video_analysis.get("frames", []) if video_analysis else []
            audio_evidence = dict(transcription)
            audio_evidence["status"] = "completed"
            report, _ = generate_final_video_report(event, windows, audio_evidence)
            if report:
                return report, None
            return None, "Gemini không tạo được kết luận. Kiểm tra API key, model và kết nối Internet."

        if not config.AUDIO_SUGGESTION_API_URL:
            return None, "Chưa cấu hình Gemini. Hãy nhập API key ở đầu trang Kiểm thử AI."

        evidence = {
            "nvr_metadata": event.get("metadata", {}),
            "event_code": event.get("event_code"),
            "event_description": event.get("description"),
            "audio_transcript": transcription.get("transcript") or "",
            "speech_detected": bool(transcription.get("speech_detected")),
            "ignored_reason": transcription.get("ignored_reason"),
        }
        prompt = (
            "Bạn là trợ lý vận hành camera. Chỉ dùng evidence bên dưới; không suy đoán "
            "hành vi như cãi vã, đập phá hoặc đánh nhau chỉ từ dB. Trả về đúng JSON: "
            '{"summary": string, "risk_level": "none|low|medium|high", '
            '"recommended_action": string, "evidence": [{"source": "NVR metadata|audio transcript|không có audio", "detail": string}]}. '
            "Nếu transcript rỗng, chỉ mô tả metadata NVR và dùng evidence nguồn 'không có audio' hoặc 'NVR metadata'.\n"
            f"Evidence: {json.dumps(evidence, ensure_ascii=False)}"
        )
        headers = {"Content-Type": "application/json"}
        if config.AUDIO_SUGGESTION_API_KEY:
            headers["Authorization"] = f"Bearer {config.AUDIO_SUGGESTION_API_KEY}"
        payload = {
            "model": config.AUDIO_SUGGESTION_MODEL or "audio-event-summarizer",
            "messages": [
                {"role": "system", "content": "Return valid JSON only."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
        try:
            response = requests.post(config.AUDIO_SUGGESTION_API_URL, json=payload, headers=headers, timeout=30)
            response.raise_for_status()
            body = response.json()
            raw = body.get("choices", [{}])[0].get("message", {}).get("content", body)
            suggestion = json.loads(raw) if isinstance(raw, str) else raw
            return self._validate_suggestion(suggestion), None
        except (requests.RequestException, ValueError, TypeError, KeyError, IndexError) as exc:
            return None, f"Không thể tạo gợi ý LLM: {exc}"

    @staticmethod
    def _validate_suggestion(value: object) -> dict:
        if not isinstance(value, dict):
            raise ValueError("LLM trả về JSON không phải object")
        required = ("summary", "risk_level", "recommended_action", "evidence")
        if any(not isinstance(value.get(field), str) for field in required[:3]) or not isinstance(value.get("evidence"), list):
            raise ValueError("LLM trả về thiếu trường gợi ý bắt buộc")
        risk_level = value["risk_level"].lower()
        if risk_level not in {"none", "low", "medium", "high"}:
            raise ValueError("risk_level không hợp lệ")
        allowed_sources = {"NVR metadata", "audio transcript", "không có audio"}
        clean_evidence = []
        for item in value["evidence"]:
            if not isinstance(item, dict) or item.get("source") not in allowed_sources or not isinstance(item.get("detail"), str):
                raise ValueError("evidence không hợp lệ")
            clean_evidence.append({"source": item["source"], "detail": item["detail"]})
        return {
            "summary": value["summary"],
            "risk_level": risk_level,
            "recommended_action": value["recommended_action"],
            "evidence": clean_evidence,
        }

    def _notify(self, event_id: int) -> None:
        if self._on_updated:
            self._on_updated(event_id)
