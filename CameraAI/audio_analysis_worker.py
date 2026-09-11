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
from internal_audio_client import send_clean_audio_to_server
from qwen_vision_client import call_qwen_chat
from gemini_video_report import (
    generate_final_video_report,
    get_gemini_public_config,
    transcribe_and_analyze_audio_with_gemini,
)


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

        # When DeepFilterNet is enabled, extract at 48 kHz, filter noise, and downsample to 16 kHz
        if getattr(config, "USE_DEEPFILTER", True):
            raw_path = None
            try:
                handle_raw, raw_path = tempfile.mkstemp(prefix="camera_raw_48k_", suffix=".wav")
                os.close(handle_raw)
                result = subprocess.run(
                    [config.FFMPEG_PATH, "-y", "-i", str(clip_path), "-vn", "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "1", raw_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=30,
                )
                if result.returncode == 0 and os.path.exists(raw_path) and os.path.getsize(raw_path) > 0:
                    import sys
                    from pathlib import Path
                    cosmos_dir = str(Path(__file__).resolve().parent.parent / "cosmos_code_base")
                    if cosmos_dir not in sys.path:
                        sys.path.insert(0, cosmos_dir)
                    from audio_enhancer import enhance_audio_file
                    enhance_audio_file(raw_path, output_wav_path=wav_path, target_sr=16000)
                    return wav_path
            except Exception as df_err:
                print(f"[AUDIO] DeepFilterNet pre-filtering fallback: {df_err}")
            finally:
                if raw_path and os.path.exists(raw_path):
                    Path(raw_path).unlink(missing_ok=True)

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

        # 1. Primary Engine: Internal Audio AI Server (4x H200 infrastructure)
        # Máy trạm chỉ lọc nhiễu DeepFilterNet3, gửi clean WAV lên server phân tích
        server_analysis = None
        transcription = None
        server_error = None
        try:
            server_res = send_clean_audio_to_server(wav_path, event)
            if server_res and server_res.get("status") == "ok":
                server_analysis = server_res
                transcription = {
                    "transcript": server_res.get("transcript", ""),
                    "speech_detected": server_res.get("speech_detected", 0),
                    "audio_model": server_res.get("audio_model", config.INTERNAL_AUDIO_MODEL_NAME),
                    "ignored_reason": server_res.get("ignored_reason"),
                }
        except Exception as exc:
            server_error = str(exc)
            print(f"[AUDIO] alert={event_id} Internal Audio Server notice: {exc}")

        # 2. Secondary fallback: Gemini multimodal audio if configured and server returned error
        if not transcription:
            gemini_cfg = get_gemini_public_config()
            if gemini_cfg.get("configured"):
                gemini_audio = transcribe_and_analyze_audio_with_gemini(wav_path)
                if gemini_audio is not None:
                    transcription = {
                        "transcript": gemini_audio.get("transcript", ""),
                        "speech_detected": gemini_audio.get("speech_detected", 0),
                        "audio_model": gemini_audio.get("audio_model", "Gemini Audio"),
                        "ignored_reason": None,
                    }
                    server_analysis = gemini_audio

        if not transcription:
            error_msg = server_error or "Không thể phân tích âm thanh từ Server AI nội bộ."
            self._set_status(event_id, "stt_failed", error_message=error_msg)
            return

        if not transcription["transcript"].strip() and not transcription["speech_detected"]:
            self._set_status(event_id, "no_speech_detected", **transcription)
            return

        self._set_status(event_id, "analyzing", **transcription)
        suggestion, suggestion_error = self._create_suggestion(event, transcription, server_analysis=server_analysis)
        if suggestion_error:
            self._set_status(event_id, "transcribed", error_message=suggestion_error)
            return

        self._set_status(
            event_id,
            "completed",
            suggestion=suggestion,
            error_message=suggestion_error,
            analyzed_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        )

    def _create_suggestion(self, event: dict, transcription: dict, server_analysis: Optional[dict] = None) -> tuple[Optional[dict], Optional[str]]:
        """Create a strictly evidence-grounded suggestion after transcription.

        Prioritizes structured analysis from Internal Audio Server,
        then Gemini if configured, then OpenAI-compatible endpoint / Qwen 4x H200.
        """
        # 1. If server_analysis already has structured summary & risk_level from internal server
        if server_analysis and server_analysis.get("summary"):
            evidence_list = []
            if transcription.get("transcript"):
                evidence_list.append({"source": "audio transcript", "detail": transcription["transcript"]})
            for sound in server_analysis.get("detected_sounds", []):
                evidence_list.append({"source": "audio transcript", "detail": f"Âm thanh: {sound}"})
            if not evidence_list:
                evidence_list.append({"source": "NVR metadata", "detail": f"Sự kiện {event.get('event_code', 'Camera')}"})

            risk_level = str(server_analysis.get("risk_level", "none")).lower()
            if risk_level not in {"none", "low", "medium", "high"}:
                risk_level = "none"

            return {
                "summary": server_analysis["summary"],
                "risk_level": risk_level,
                "recommended_action": server_analysis.get("recommended_action") or "Đối chiếu clip gốc và theo dõi tiếp tục.",
                "evidence": evidence_list,
            }, None

        # 2. Gemini final-report layer if configured
        gemini_config = get_gemini_public_config()
        if gemini_config.get("configured"):
            video_analysis = database.get_video_analysis(int(event["id"])) if event.get("id") else None
            windows = video_analysis.get("frames", []) if video_analysis else []
            audio_evidence = dict(transcription)
            audio_evidence["status"] = "completed"
            report, _ = generate_final_video_report(event, windows, audio_evidence)
            if report:
                return report, None
            return None, "Gemini không tạo được kết luận. Kiểm tra API key, model và kết nối Internet."

        # 3. Optional OpenAI-compatible endpoint (e.g. AUDIO_SUGGESTION_API_URL)
        if config.AUDIO_SUGGESTION_API_URL:
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

        # 4. Use Qwen3.8-27B on Server 4x H200
        if config.QWEN_SERVER_URL and config.QWEN_API_KEY:
            try:
                evidence = {
                    "nvr_metadata": event.get("metadata", {}),
                    "event_code": event.get("event_code"),
                    "event_description": event.get("description"),
                    "audio_transcript": transcription.get("transcript") or "",
                    "speech_detected": bool(transcription.get("speech_detected")),
                    "ignored_reason": transcription.get("ignored_reason"),
                }
                prompt = (
                    "Bạn là trợ lý vận hành camera an ninh. Chỉ dùng evidence bên dưới; không suy đoán "
                    "hành vi như cãi vã, đập phá hoặc đánh nhau chỉ từ dB. Trả về đúng JSON:\n"
                    '{"summary": string, "risk_level": "none|low|medium|high", '
                    '"recommended_action": string, "evidence": [{"source": "NVR metadata|audio transcript|không có audio", "detail": string}]}\n'
                    "Nếu transcript rỗng, chỉ mô tả metadata NVR và dùng evidence nguồn 'không có audio' hoặc 'NVR metadata'.\n"
                    f"Evidence: {json.dumps(evidence, ensure_ascii=False)}"
                )
                messages = [
                    {"role": "system", "content": "Return valid JSON only. Do not wrap in markdown quotes."},
                    {"role": "user", "content": prompt},
                ]
                qwen_res = call_qwen_chat(messages, max_tokens=1024, temperature=0.1, timeout=30)
                content = qwen_res.get("content", "")
                start, end = content.find("{"), content.rfind("}")
                if start >= 0 and end > start:
                    parsed = json.loads(content[start:end+1])
                    return self._validate_suggestion(parsed), None
            except Exception as qwen_err:
                print(f"[AUDIO] Qwen suggestion synthesis notice: {qwen_err}")

        # 5. Safe rule-based default
        transcript = transcription.get("transcript", "").strip()
        return {
            "summary": f"Đã ghi nhận âm thanh: {transcript}" if transcript else "Âm thanh môi trường bình thường.",
            "risk_level": "low" if transcript else "none",
            "recommended_action": "Đối chiếu clip gốc khi cần xác minh.",
            "evidence": [{"source": "audio transcript" if transcript else "không có audio", "detail": transcript or "Không phát hiện tiếng động bất thường"}],
        }, None

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
