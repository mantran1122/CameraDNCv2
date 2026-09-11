"""Internal Audio AI Client for CameraAI V2.

Sends clean, edge-denoised WAV audio (16 kHz Mono PCM from DeepFilterNet3)
to the Internal AI Server (NVIDIA H200 infrastructure) for Vietnamese speech-to-text
and acoustic anomaly detection.
"""

import json
import logging
import math
import os
import subprocess
import tempfile
import time
import wave
from array import array
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

import config

logger = logging.getLogger("internal_audio_client")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")


def send_clean_audio_to_server(
    wav_path: str,
    event: Optional[Dict[str, Any]] = None,
    timeout: int = 35,
) -> Dict[str, Any]:
    """
    Send a clean WAV file (16 kHz) to the internal audio AI server.
    
    Returns structured analysis:
    {
        "transcript": str,
        "speech_detected": int,
        "detected_sounds": List[str],
        "risk_level": "none" | "low" | "medium" | "high",
        "summary": str,
        "audio_model": str,
        "status": "ok" | "empty" | "error",
        "latency_ms": int,
        "ignored_reason": Optional[str]
    }
    """
    path_obj = Path(wav_path)
    if not path_obj.is_file() or path_obj.stat().st_size == 0:
        raise ValueError(f"File audio không tồn tại hoặc rỗng: {wav_path}")

    start_time = time.time()
    event_info = event or {}
    channel = str(event_info.get("channel", "unknown"))
    event_code = str(event_info.get("event_code", "unknown"))
    timestamp = str(event_info.get("timestamp", ""))

    headers = {
        "Authorization": f"Bearer {config.INTERNAL_AUDIO_SERVER_API_KEY}",
        "User-Agent": config.QWEN_USER_AGENT,
    }

    server_url = config.INTERNAL_AUDIO_SERVER_URL.rstrip("/")
    # Check possible endpoints: dedicated /analyze or /transcriptions or direct url
    if server_url.endswith("/transcribe") or server_url.endswith("/analyze") or server_url.endswith("/transcriptions"):
        endpoint = server_url
    else:
        # Default to /analyze endpoint on audio server
        endpoint = f"{server_url}/analyze"

    logger.info(f"[InternalAudioClient] Sending clean audio ({path_obj.stat().st_size / 1024:.1f} KB) to {endpoint} (ch={channel}, code={event_code})")

    file_bytes = path_obj.read_bytes()
    files = {
        "file": (path_obj.name, file_bytes, "audio/wav")
    }
    data = {
        "channel": channel,
        "event_code": event_code,
        "timestamp": timestamp,
        "model": config.INTERNAL_AUDIO_MODEL_NAME,
    }

    try:
        resp = requests.post(endpoint, headers=headers, files=files, data=data, timeout=timeout)
        latency_ms = int((time.time() - start_time) * 1000)

        if resp.status_code == 200:
            result = resp.json()
            return _normalize_audio_response(result, latency_ms)
        elif resp.status_code == 404 or resp.status_code == 500:
            # Try fallback endpoint if /analyze gave 404/500: e.g. /v1/audio/transcriptions
            fallback_endpoint = f"{server_url.rsplit('/', 1)[0]}/transcribe" if "/audio" in server_url else f"{server_url}/transcribe"
            if fallback_endpoint != endpoint:
                logger.info(f"[InternalAudioClient] Primary endpoint returned {resp.status_code}, trying fallback: {fallback_endpoint}")
                resp_fb = requests.post(fallback_endpoint, headers=headers, files={"file": (path_obj.name, file_bytes, "audio/wav")}, data=data, timeout=timeout)
                if resp_fb.status_code == 200:
                    latency_ms = int((time.time() - start_time) * 1000)
                    return _normalize_audio_response(resp_fb.json(), latency_ms)

        # If server returned an error status, raise or log detailed info
        logger.warning(f"[InternalAudioClient] Server returned status {resp.status_code}: {resp.text[:300]}")
        raise RuntimeError(f"Server Audio AI trả về mã lỗi HTTP {resp.status_code}: {resp.text[:200]}")

    except requests.RequestException as exc:
        latency_ms = int((time.time() - start_time) * 1000)
        logger.error(f"[InternalAudioClient] Lỗi kết nối Server Audio AI: {exc}")
        raise RuntimeError(f"Lỗi kết nối Server Audio AI ({endpoint}): {exc}")


def _normalize_audio_response(data: Dict[str, Any], latency_ms: int) -> Dict[str, Any]:
    """Ensure standard keys and types in audio analysis response."""
    transcript = str(data.get("transcript") or data.get("text") or "").strip()
    speech_detected = int(bool(data.get("speech_detected") or transcript))
    
    raw_sounds = data.get("detected_sounds", [])
    if isinstance(raw_sounds, list):
        detected_sounds = [str(s).strip() for s in raw_sounds if str(s).strip()]
    else:
        detected_sounds = []

    risk_level = str(data.get("risk_level", "none")).lower()
    if risk_level not in {"none", "low", "medium", "high"}:
        risk_level = "none"

    summary = str(data.get("summary") or "").strip()
    if not summary:
        if transcript:
            summary = f"Phát hiện giọng nói: \"{transcript[:100]}\""
        elif detected_sounds:
            summary = f"Phát hiện âm thanh môi trường: {', '.join(detected_sounds[:3])}"
        else:
            summary = "Âm thanh môi trường bình thường, không có bất thường rõ rệt."

    audio_model = str(data.get("audio_model") or config.INTERNAL_AUDIO_MODEL_NAME)
    ignored_reason = data.get("ignored_reason")

    return {
        "status": "ok",
        "transcript": transcript,
        "speech_detected": speech_detected,
        "detected_sounds": detected_sounds,
        "risk_level": risk_level,
        "summary": summary,
        "audio_model": audio_model,
        "latency_ms": latency_ms,
        "ignored_reason": ignored_reason,
    }


def extract_and_analyze_clip_audio(
    clip_path: Path | str,
    event: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Trích xuất audio từ clip, lọc nhiễu qua DeepFilterNet3 tại máy trạm,
    sau đó gửi sang AI Audio pipeline để bóc băng tiếng Việt và nhận diện âm thanh.
    """
    clip_obj = Path(clip_path)
    if not clip_obj.is_file():
        return {
            "has_audio": False,
            "status": "video_missing",
            "transcript": "",
            "speech_detected": 0,
            "detected_sounds": [],
            "risk_level": "none",
            "summary": "Không tìm thấy file video.",
            "audio_model": "None"
        }

    # 1. Kiểm tra audio stream qua ffprobe
    has_audio_track = False
    try:
        probe = subprocess.run(
            [config.FFPROBE_PATH, "-v", "error", "-select_streams", "a", "-show_entries", "stream=index", "-of", "csv=p=0", str(clip_obj)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=10,
        )
        has_audio_track = bool(probe.stdout.strip())
    except Exception as exc:
        logger.warning(f"[AudioExtract] ffprobe error: {exc}")

    if not has_audio_track:
        return {
            "has_audio": False,
            "status": "no_audio_track",
            "transcript": "",
            "speech_detected": 0,
            "detected_sounds": [],
            "risk_level": "none",
            "summary": "Clip video không có track âm thanh.",
            "audio_model": "None",
            "audio_rms": None
        }

    raw_path = None
    clean_path = None
    try:
        handle_clean, clean_path = tempfile.mkstemp(prefix="chat_clean_", suffix=".wav")
        os.close(handle_clean)

        # 2. Edge Denoising bằng DeepFilterNet3
        if getattr(config, "USE_DEEPFILTER", True):
            handle_raw, raw_path = tempfile.mkstemp(prefix="chat_raw48k_", suffix=".wav")
            os.close(handle_raw)
            res = subprocess.run(
                [config.FFMPEG_PATH, "-y", "-i", str(clip_obj), "-vn", "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "1", raw_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=25,
            )
            if res.returncode == 0 and os.path.exists(raw_path) and os.path.getsize(raw_path) > 0:
                try:
                    import sys
                    cosmos_dir = str(Path(__file__).resolve().parent.parent / "cosmos_code_base")
                    if cosmos_dir not in sys.path:
                        sys.path.insert(0, cosmos_dir)
                    from audio_enhancer import enhance_audio_file
                    enhance_audio_file(raw_path, output_wav_path=clean_path, target_sr=16000)
                except Exception as df_err:
                    logger.warning(f"[AudioExtract] DeepFilterNet fallback: {df_err}")
                    subprocess.run(
                        [config.FFMPEG_PATH, "-y", "-i", str(clip_obj), "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", clean_path],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=25,
                    )
            else:
                subprocess.run(
                    [config.FFMPEG_PATH, "-y", "-i", str(clip_obj), "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", clean_path],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=25,
                )
        else:
            subprocess.run(
                [config.FFMPEG_PATH, "-y", "-i", str(clip_obj), "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", clean_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=25,
            )

        # 3. Đo cường độ âm thanh RMS dBFS
        audio_rms = -100.0
        try:
            with wave.open(clean_path, "rb") as wf:
                samples = array("h")
                samples.frombytes(wf.readframes(wf.getnframes()))
                if samples:
                    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
                    audio_rms = 20 * math.log10(max(rms / 32768.0, 1e-6))
        except Exception as rms_err:
            logger.warning(f"[AudioExtract] RMS error: {rms_err}")

        if audio_rms < -50.0:
            return {
                "has_audio": True,
                "status": "audio_too_quiet",
                "transcript": "",
                "speech_detected": 0,
                "detected_sounds": [],
                "risk_level": "none",
                "summary": f"Âm thanh môi trường rất nhỏ ({audio_rms:.1f} dBFS, dưới ngưỡng nhận diện).",
                "audio_rms": round(audio_rms, 1),
                "audio_model": "Edge Denoise"
            }

        # 4. Gửi sang AI Server nội bộ hoặc Fallback
        audio_result = None
        try:
            audio_result = send_clean_audio_to_server(clean_path, event=event)
        except Exception as srv_err:
            logger.info(f"[AudioExtract] Internal audio server notice ({srv_err}), attempting fallback...")
            try:
                from gemini_video_report import transcribe_and_analyze_audio_with_gemini
                audio_result = transcribe_and_analyze_audio_with_gemini(clean_path)
            except Exception as fb_err:
                logger.warning(f"[AudioExtract] Gemini fallback notice: {fb_err}")

        # Fallback local Faster-Whisper nếu server/gemini chưa trả kết quả
        if not audio_result:
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel("small", device="cpu", compute_type="int8")
                segments, info = model.transcribe(clean_path, language="vi")
                text = " ".join(seg.text for seg in segments).strip()
                audio_result = {
                    "transcript": text,
                    "speech_detected": int(bool(text)),
                    "detected_sounds": ["tiếng người nói"] if text else [],
                    "risk_level": "none",
                    "summary": f"Phát hiện giọng nói: \"{text[:100]}\"" if text else "Âm thanh môi trường bình thường.",
                    "audio_model": "Faster-Whisper (Edge)"
                }
            except Exception as fw_err:
                logger.warning(f"[AudioExtract] Local whisper fallback notice: {fw_err}")

        if not audio_result:
            audio_result = {
                "transcript": "",
                "speech_detected": 0,
                "detected_sounds": [],
                "risk_level": "none",
                "summary": "Không thể phân tích nội dung âm thanh.",
                "audio_model": "None"
            }

        audio_result["has_audio"] = True
        audio_result["status"] = "completed"
        audio_result["audio_rms"] = round(audio_rms, 1)
        return audio_result

    finally:
        if raw_path and os.path.exists(raw_path):
            try:
                os.remove(raw_path)
            except Exception:
                pass
        if clean_path and os.path.exists(clean_path):
            try:
                os.remove(clean_path)
            except Exception:
                pass


