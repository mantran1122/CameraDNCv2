"""
Cosmos Live Service — FastAPI wrapper cho single-frame inference.

Chạy:
    python live_service.py [--model-id ...] [--gpu-memory-utilization 0.85] [--port 8765]

Server start ngay lập tức. Model load trong background thread.
GET /health trả {"status": "loading"} ngay khi server còn đang load model.
"""

import argparse
import difflib
import hashlib
import io
import json
import logging
import math
import os
import re
import signal
import tempfile
import threading
import time
import unicodedata
import wave
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import uvicorn
from fastapi import Body, FastAPI, Header, Request
from fastapi.responses import JSONResponse
from PIL import Image, ImageDraw

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Config điền trong main() trước khi uvicorn.run
_cfg: dict = {}

# Runtime state — đọc/ghi dưới _status_lock
_status_lock = threading.Lock()
_status = "loading"
_status_detail: str | None = None

# Model — chỉ ghi 1 lần trong _load_model()
_model = None
_processor = None
_sampling_params = None
_staff_uniform_detector = None
_audio_transcriber = None

# Đảm bảo không có 2 inference chạy cùng lúc
_inference_lock = threading.Lock()
_audio_inference_lock = threading.Lock()

# Last delivered analysis per camera. Consecutive identical results are
# suppressed so one unchanged scene does not create alert spam.
_last_live_result_fingerprints: dict[tuple[str, int | None], str] = {}
_last_audio_transcriptions: dict[tuple[str, str | None], tuple[str, float]] = {}


def _event_log_path(captured_at: datetime) -> Path:
    """Return the daily JSONL audit file for live detections, never frames."""
    configured = os.getenv("COSMOS_LIVE_EVENT_LOG_DIR", "").strip()
    base = Path(configured) if configured else Path(__file__).resolve().parent / "outputs" / "live_events"
    return base / "live_events_{}.jsonl".format(captured_at.strftime("%Y%m%d"))


def _parse_capture_time(value: str | None) -> datetime:
    if value:
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.astimezone()
        except ValueError:
            logger.warning("Invalid X-Cosmos-Captured-At header: %r", value)
    return datetime.now().astimezone()


def _should_record_event(risk_level: str) -> bool:
    levels = {"none": 0, "low": 1, "medium": 2, "high": 3}
    threshold = os.getenv("COSMOS_LIVE_EVENT_MIN_RISK", "low").strip().lower()
    return levels.get(risk_level.lower(), 0) >= levels.get(threshold, 1)


def _is_duplicate_live_result(result: dict, device_id: str, channel: int | None) -> bool:
    """Return True only when this camera's immediately previous result matches."""
    normalized = {
        "risk_level": str(result.get("risk_level", "none")).lower(),
        "summary": " ".join(str(result.get("summary", "")).split()),
        "events": sorted(
            (
                str(event.get("label", "")),
                int(event.get("count", 0)),
            )
            for event in result.get("events", [])
            if isinstance(event, dict)
        ),
    }
    fingerprint = json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))
    key = (device_id or "unknown", channel)
    duplicate = _last_live_result_fingerprints.get(key) == fingerprint
    _last_live_result_fingerprints[key] = fingerprint
    return duplicate


def _record_live_event(result: dict, captured_at: datetime, device_id: str, channel: int | None) -> dict | None:
    """Persist recorder/channel/time mapping for later playback; never frames."""
    risk_level = str(result.get("risk_level", "none")).lower()
    if not _should_record_event(risk_level) or channel is None or channel < 0:
        return None
    try:
        replay_seconds = max(1, int(os.getenv("COSMOS_LIVE_REPLAY_SECONDS", "30")))
    except ValueError:
        replay_seconds = 30
    event = {
        "event_time": captured_at.isoformat(timespec="seconds"),
        "device_id": device_id or "unknown",
        "channel": channel,
        "replay_start": (captured_at - timedelta(seconds=replay_seconds)).isoformat(timespec="seconds"),
        "replay_end": (captured_at + timedelta(seconds=replay_seconds)).isoformat(timespec="seconds"),
        "risk_level": risk_level,
        "summary": str(result.get("summary", ""))[:2000],
        "events": result.get("events", []),
    }
    try:
        path = _event_log_path(captured_at)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(event, ensure_ascii=False) + "\n")
    except OSError as exc:
        logger.error("Could not write live event metadata: %s", exc)
    return event

# JSON schema cho guided_json của vllm — bắt model xuất đúng cấu trúc
_LIVE_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "risk_level": {"type": "string", "enum": ["none", "low", "medium", "high"]},
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "count": {"type": "integer", "minimum": 0},
                },
                "required": ["label", "count"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["summary", "risk_level", "events"],
    "additionalProperties": False,
}

_LIVE_PROMPT = """\
You are a real-time surveillance camera analyst. You receive a single camera frame.

Analyze the frame and return ONLY valid JSON — no markdown, no explanation, no extra text.

JSON schema:
{
  "summary": "<Vietnamese description — concise, operational, what you see>",
  "risk_level": "<none|low|medium|high>",
  "events": [
    {"label": "<object type in Vietnamese>", "count": <integer estimate>}
  ]
}

risk_level:
- none: ordinary activity, including people working, waiting, sitting, standing, or walking normally; nothing needs attention
- low: a visible mild safety, security, or operational concern that is worth monitoring; never use low merely because people are present
- medium: clear phone usage, crowding, suspicious behavior, unattended objects
- high: fight, fall, intrusion, fire, smoke, theft, immediate safety threat

events: list every significant object type you see (nguoi, xe_may, o_to, xe_tai, ba_lo, tui_xach, ...).
Count is an estimate — VLM counts are approximate, not exact.
summary: Vietnamese, 2-4 concise sentences when the scene has multiple useful facts. Preserve relevant detail and location, but avoid decorative narration or unsupported interpretation.
This is one still frame. Do not claim movement, entry/exit, duration, intent, or change over time unless temporal evidence is explicitly supplied.

Return JSON only."""


def _set_status(status: str, detail: str | None = None) -> None:
    global _status, _status_detail
    with _status_lock:
        _status = status
        _status_detail = detail


def _get_status() -> tuple[str, str | None]:
    with _status_lock:
        return _status, _status_detail


def _load_model() -> None:
    global _model, _processor, _sampling_params

    model_id = _cfg["model_id"]
    gpu_util = _cfg["gpu_memory_utilization"]
    max_model_len = _cfg["max_model_len"]
    max_new_tokens = _cfg["max_new_tokens"]

    try:
        from transformers import AutoProcessor

        logger.info("Loading processor: %s", model_id)
        _processor = AutoProcessor.from_pretrained(model_id, trust_remote_code=True)

        try:
            from vllm import LLM, SamplingParams
        except ImportError as exc:
            raise RuntimeError(
                "vllm không tìm thấy. Cài: pip install vllm  (cần CUDA)."
            ) from exc

        logger.info(
            "Loading vLLM model: %s  gpu_util=%.2f  max_model_len=%d",
            model_id, gpu_util, max_model_len,
        )
        _model = LLM(
            model=model_id,
            trust_remote_code=True,
            dtype="auto",
            gpu_memory_utilization=float(gpu_util),
            max_model_len=max_model_len,
            limit_mm_per_prompt={"image": 1},
        )

        try:
            # vLLM 0.23+ renamed guided_json to structured_outputs.  Use the
            # current API so the model is constrained to the response schema.
            from vllm.sampling_params import StructuredOutputsParams

            _sampling_params = SamplingParams(
                temperature=0.0,
                max_tokens=max_new_tokens,
                structured_outputs=StructuredOutputsParams(json=_LIVE_SCHEMA),
            )
            logger.info("JSON structured output enabled.")
        except (ImportError, TypeError) as exc:
            # Keep compatibility with older vLLM releases, although those
            # releases cannot guarantee a parseable JSON response.
            logger.warning("JSON structured output unavailable: %s", exc)
            _sampling_params = SamplingParams(
                temperature=0.0, max_tokens=max_new_tokens
            )

        _set_status("ready")
        logger.info("Model ready.")

    except Exception as exc:
        _set_status("error", str(exc))
        logger.error("Model load failed: %s", exc)


def _load_live_prompt(profile_override: str | None = None) -> str:
    prompts_dir = Path(__file__).resolve().parent / "prompts"
    profile = (profile_override or os.getenv("COSMOS_LIVE_PROMPT_PROFILE", "admissions")).strip().lower()
    profile_path = prompts_dir / "profiles" / "{}.txt".format(profile)
    if profile_path.exists():
        return _LIVE_PROMPT + "\n\n" + profile_path.read_text(encoding="utf-8").strip()

    # Compatibility only for existing installations that have not yet moved
    # their admissions prompt into prompts/profiles/admissions.txt.
    if profile == "admissions":
        legacy_path = prompts_dir / "live_admissions_prompt.txt"
        if legacy_path.exists():
            logger.warning("Using legacy admissions prompt; migrate it to prompts/profiles/admissions.txt.")
            return legacy_path.read_text(encoding="utf-8").strip()
    logger.warning("Unknown live prompt profile %r; using generic prompt.", profile)
    return _LIVE_PROMPT


def _active_live_prompt_profile(profile_override: str | None = None) -> str:
    """Return the profile actually selected by the live service for diagnostics."""
    prompts_dir = Path(__file__).resolve().parent / "prompts"
    profile = (profile_override or os.getenv("COSMOS_LIVE_PROMPT_PROFILE", "admissions")).strip().lower()
    if profile == "admissions":
        return "admissions"
    if (prompts_dir / "profiles" / "{}.txt".format(profile)).exists():
        return profile
    return "generic"


def _get_staff_uniform_detector():
    """Load OpenCV/YOLO only after vLLM is ready to avoid startup library conflicts."""
    global _staff_uniform_detector
    if _staff_uniform_detector is None:
        from staff_uniform_detector import YellowUniformDetector

        _staff_uniform_detector = YellowUniformDetector()
    return _staff_uniform_detector


def _active_audio_model_id() -> str:
    """Return the configured ASR model without forcing it to load."""
    return os.getenv("COSMOS_AUDIO_MODEL", "vinai/PhoWhisper-small").strip() or "vinai/PhoWhisper-small"


def _audio_beam_size() -> int:
    """Use real beam search for speech decoding while keeping configuration bounded."""
    try:
        return min(10, max(1, int(os.getenv("COSMOS_AUDIO_BEAM_SIZE", "5"))))
    except ValueError:
        return 5


def _audio_min_rms() -> float:
    """Return a conservative floor so camera noise is not sent to Whisper."""
    try:
        # Values below this regularly classify low-level DVR hiss as speech.
        return min(0.1, max(0.004, float(os.getenv("COSMOS_AUDIO_MIN_RMS", "0.008"))))
    except ValueError:
        return 0.008


def _audio_requires_decoder_agreement() -> bool:
    """Fail closed when two deterministic decodes disagree on the spoken text."""
    return os.getenv("COSMOS_AUDIO_REQUIRE_DECODER_AGREEMENT", "false").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _audio_transcripts_agree(primary: str, verifier: str) -> bool:
    """Accept only substantially matching decodes; never rewrite either transcript."""
    primary_folded = _fold_text(primary)
    verifier_folded = _fold_text(verifier)
    if not primary_folded or not verifier_folded:
        return not primary_folded and not verifier_folded
    return difflib.SequenceMatcher(None, primary_folded, verifier_folded).ratio() >= 0.72


def _get_audio_transcriber():
    """Load Vietnamese-specialized Whisper lazily so image-only monitoring stays light."""
    global _audio_transcriber
    if _audio_transcriber is None:
        import numpy as np
        import torch
        from transformers import AutoModelForSpeechSeq2Seq, AutoProcessor, pipeline

        model_id = _active_audio_model_id()
        use_cuda = torch.cuda.is_available()
        dtype = torch.float16 if use_cuda else torch.float32
        if use_cuda:
            torch.backends.cudnn.benchmark = True
        model = AutoModelForSpeechSeq2Seq.from_pretrained(
            model_id,
            dtype=dtype,
            low_cpu_mem_usage=True,
            use_safetensors=False,
        )
        if use_cuda:
            model.to("cuda")
        model.eval()
        processor = AutoProcessor.from_pretrained(model_id)
        _audio_transcriber = pipeline(
            "automatic-speech-recognition",
            model=model,
            tokenizer=processor.tokenizer,
            feature_extractor=processor.feature_extractor,
            dtype=dtype,
            device=0 if use_cuda else -1,
            max_new_tokens=128,
        )
        # Warm up pipeline to eliminate first-request cold-start latency
        try:
            with torch.inference_mode():
                dummy_audio = np.zeros(16000, dtype=np.float32)
                _audio_transcriber(dummy_audio, generate_kwargs={"task": "transcribe", "num_beams": 1, "max_new_tokens": 8})
        except Exception:
            pass
    return _audio_transcriber


def _audio_chunk_seconds() -> int:
    """Return a safe duration that can never enter Whisper long-form mode."""
    try:
        return min(29, max(10, int(os.getenv("COSMOS_AUDIO_CHUNK_SECONDS", "25"))))
    except ValueError:
        return 25


def _transcribe_short_wav_chunks(wav_path: str, generate_kwargs: dict) -> dict:
    """Transcribe PCM WAV in chunks shorter than Whisper's 30-second limit."""
    chunk_seconds = _audio_chunk_seconds()
    transcriber = _get_audio_transcriber()
    texts = []
    chunks = []
    with wave.open(wav_path, "rb") as source:
        frame_rate = source.getframerate()
        frames_per_chunk = max(1, frame_rate * chunk_seconds)
        params = source.getparams()
        start_frame = 0
        while True:
            pcm = source.readframes(frames_per_chunk)
            if not pcm:
                break
            chunk_path = None
            try:
                with tempfile.NamedTemporaryFile(prefix="cosmos_audio_chunk_", suffix=".wav", delete=False) as output:
                    chunk_path = output.name
                with wave.open(chunk_path, "wb") as chunk_file:
                    chunk_file.setparams(params)
                    chunk_file.writeframes(pcm)
                result = transcriber(chunk_path, generate_kwargs=generate_kwargs)
                text = " ".join(str(result.get("text", "")).split())
                start_seconds = start_frame / frame_rate
                # Derive the actual end from byte geometry; the last chunk is
                # commonly shorter than the configured duration.
                bytes_per_frame = max(1, params.nchannels * params.sampwidth)
                chunk_frames = len(pcm) // bytes_per_frame
                end_seconds = (start_frame + chunk_frames) / frame_rate
                if text:
                    texts.append(text)
                    chunks.append({"timestamp": [round(start_seconds, 3), round(end_seconds, 3)], "text": text})
                start_frame += chunk_frames
            finally:
                if chunk_path:
                    Path(chunk_path).unlink(missing_ok=True)
    return {"text": " ".join(texts), "chunks": chunks}


def _pcm16_wav_samples(body: bytes):
    """Read normalized PCM16 samples from the WAV emitted by the camera client."""
    import numpy as np

    marker = body.find(b"data")
    offset = marker + 8 if marker >= 0 else 44
    pcm = body[offset:]
    if len(pcm) < 2:
        return np.empty(0, dtype=np.float32)
    if len(pcm) % 2:
        pcm = pcm[:-1]
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
    return samples / 32768.0


def _pcm16_wav_rms(body: bytes) -> float:
    """Estimate normalized RMS from the PCM16 WAV emitted by the camera client."""
    import numpy as np

    samples = _pcm16_wav_samples(body)
    return float(np.sqrt(np.mean(np.square(samples)))) if samples.size else 0.0


def _has_speech_activity(body: bytes, min_rms: float) -> tuple[bool, float, float]:
    """Multi-stage conservative energy VAD: speech must rise above the chunk's stationary noise floor."""
    import numpy as np

    samples = _pcm16_wav_samples(body)
    if samples.size == 0:
        return False, 0.0, 0.0
    samples = samples - np.mean(samples)
    rms = float(np.sqrt(np.mean(np.square(samples))))
    peak = float(np.max(np.abs(samples))) if samples.size else 0.0
    min_peak = float(os.getenv("COSMOS_AUDIO_MIN_PEAK", "0.064"))
    frame_size = 480  # 30 ms at 16 kHz
    frame_count = samples.size // frame_size
    if rms < min_rms or peak < min_peak or frame_count < 8:
        return False, rms, 0.0
    frames = samples[:frame_count * frame_size].reshape(frame_count, frame_size)
    frame_rms = np.sqrt(np.mean(np.square(frames), axis=1))
    noise_floor = max(float(np.percentile(frame_rms, 20)), 1e-6)
    active_threshold = max(min_rms, noise_floor * 1.60)
    active_mask = frame_rms >= active_threshold
    active_seconds = float(np.count_nonzero(active_mask) * 0.03)
    dynamic_ratio = float(np.percentile(frame_rms, 90) / noise_floor)

    min_active_seconds = float(os.getenv("COSMOS_AUDIO_MIN_ACTIVE_SECONDS", "0.36"))
    min_dynamic_ratio = float(os.getenv("COSMOS_AUDIO_MIN_DYNAMIC_RATIO", "1.44"))
    if active_seconds < min_active_seconds or dynamic_ratio < min_dynamic_ratio:
        return False, rms, active_seconds

    # Spectral speech-band check (300Hz - 3400Hz)
    fft = np.abs(np.fft.rfft(samples))
    freqs = np.fft.rfftfreq(len(samples), 1 / 16000)
    speech_band = np.sum(fft[(freqs >= 300) & (freqs <= 3400)])
    total_band = np.sum(fft) + 1e-6
    speech_ratio = speech_band / total_band
    if speech_ratio < 0.30:
        return False, rms, active_seconds

    return True, rms, active_seconds


def _is_repetitive_transcript(text: str) -> bool:
    """Reject common Whisper loops produced from silence and stationary noise."""
    tokens = re.findall(r"\w+", text.casefold(), flags=re.UNICODE)
    if len(tokens) < 6:
        return False
    if len(set(tokens)) / len(tokens) < 0.45:
        return True
    for period in range(1, min(7, len(tokens) // 3 + 1)):
        matches = sum(tokens[index] == tokens[index - period] for index in range(period, len(tokens)))
        if matches / (len(tokens) - period) >= 0.72:
            return True
    return False


def _fold_text(text: str) -> str:
    value = unicodedata.normalize("NFD", text.casefold())
    value = "".join(char for char in value if unicodedata.category(char) != "Mn")
    return " ".join(re.findall(r"\w+", value, flags=re.UNICODE))


def _is_known_audio_hallucination(text: str) -> bool:
    defaults = (
        "hay subscribe|subscribe cho kenh|dang ky kenh|khong bo lo nhung video|"
        "cam on cac ban da xem|cam on cac ban da don xem|hen gap lai cac ban trong nhung video tiep theo|"
        "nhieu doanh nghiep da|nhieu nguoi da dat|doan ke thoi gian|toi goi sap|toi phet co|"
        "tinh than tai dien|nang thong cao|nha hang dau co the|lalaschool|thanks for watching|subtitles by|ban quyen thuoc ve"
    )
    configured = os.getenv("COSMOS_AUDIO_HALLUCINATION_PHRASES", defaults)
    folded = _fold_text(text)
    return any(_fold_text(phrase) in folded for phrase in configured.split("|") if phrase.strip())


def _is_duplicate_audio_transcript(text: str, device_id: str, channel: str | None, now: float | None = None) -> bool:
    normalized = _fold_text(text)
    if not normalized:
        return False
    current_time = time.monotonic() if now is None else now
    key = (device_id or "unknown", channel)
    previous = _last_audio_transcriptions.get(key)
    _last_audio_transcriptions[key] = (normalized, current_time)
    return bool(previous and previous[0] == normalized and current_time - previous[1] <= 120)


def _vietnamese_detector_summary(staff_count: int, risk_level: str) -> str:
    """Describe uniform detection qualitatively, never as an exact headcount."""
    quantity = "nhiều" if staff_count > 1 else "một số"
    summary = "Phát hiện {} nhân viên mặc áo vàng tại khu vực tuyển sinh.".format(quantity)
    risk_text = {
        "low": " Hoạt động hỗ trợ tuyển sinh đang diễn ra; khu vực cần theo dõi thêm.",
        "medium": " Khu vực cần được kiểm tra do có dấu hiệu cần chú ý.",
        "high": " Có dấu hiệu rủi ro cao, cần kiểm tra ngay.",
    }.get(str(risk_level).lower(), " Hoạt động hỗ trợ tuyển sinh đang diễn ra bình thường.")
    return summary + risk_text


def _vietnamese_admissions_summary(risk_level: str) -> str:
    """Fallback for admissions frames where uniform presence is not confirmed."""
    risk_text = {
        "low": "Khu vực tuyển sinh có dấu hiệu cần theo dõi thêm.",
        "medium": "Khu vực tuyển sinh cần được kiểm tra do có dấu hiệu cần chú ý.",
        "high": "Khu vực tuyển sinh có dấu hiệu rủi ro cao, cần kiểm tra ngay.",
    }.get(str(risk_level).lower(), "Hoạt động tại khu vực tuyển sinh đang diễn ra bình thường.")
    return risk_text


def _build_prompt_text(
    images: list[Image.Image], detector_context: str = "", prompt_profile: str | None = None,
    sequence_context: str = "", force_vietnamese: bool = False,
) -> str:
    """Build one prompt for an ordered still image or an ordered frame sequence."""
    prompt = _load_live_prompt(prompt_profile)
    if sequence_context:
        prompt = prompt.replace(
            "You receive a single camera frame.",
            "You receive one contact sheet containing an ordered sequence of camera frames from one short recorded-video window.",
        ).replace(
            "This is one still frame. Do not claim movement, entry/exit, duration, intent, or change over time unless temporal evidence is explicitly supplied.",
            "Read the contact sheet from left to right, top to bottom. Compare the ordered frames. You may report a change, movement, fall, physical aggression, entry/exit, or an object left behind only when it is visibly supported by more than one frame. If evidence is unclear, say so rather than guessing.",
        )
        prompt += "\n\n" + sequence_context
    prompt += """

YÊU CẦU NGÔN NGỮ BẮT BUỘC:
- Mọi giá trị văn bản trong JSON phải viết hoàn toàn bằng tiếng Việt có dấu.
- Không trả lời bằng tiếng Anh, kể cả khi video có tiêu đề, phụ đề hoặc chữ tiếng Anh.
- Không kể lại nội dung phim; chỉ mô tả bằng chứng nhìn thấy phục vụ giám sát.
- Các khóa JSON giữ nguyên theo schema, nhưng summary và label sự kiện phải là tiếng Việt.
"""
    if force_vietnamese:
        prompt += "\nKết quả trước đã sai ngôn ngữ. Hãy phân tích lại và chỉ xuất tiếng Việt có dấu."
    messages = [
        {
            "role": "user",
            "content": [
                *[{"type": "image", "image": image} for image in images],
                {"type": "text", "text": prompt + detector_context},
            ],
        }
    ]
    if hasattr(_processor, "apply_chat_template"):
        try:
            return _processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        except Exception:
            pass
    return prompt + detector_context


def _extract_and_parse_json(output_text: str) -> dict:
    """Robustly parse JSON from model output, automatically repairing truncated JSON or extracting via regex."""
    if not output_text or not output_text.strip():
        return {
            "summary": "Không nhận được phản hồi từ mô hình",
            "risk_level": "none",
            "events": [],
        }

    parsed = None
    # 1. Direct JSON parse or substring parse
    start = output_text.find("{")
    end = output_text.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = output_text[start : end + 1]
        try:
            val = json.loads(candidate)
            if isinstance(val, dict):
                parsed = val
        except Exception:
            pass

    # 2. Repair truncated JSON (common when max_new_tokens is reached mid-sentence)
    if parsed is None and start != -1:
        candidate = output_text[start:].strip()
        quote_count = candidate.count('"') - candidate.count(r'\"')
        if quote_count % 2 != 0:
            candidate += '"'
        open_brackets = candidate.count('[') - candidate.count(']')
        if open_brackets > 0:
            candidate += ']' * open_brackets
        open_braces = candidate.count('{') - candidate.count('}')
        if open_braces > 0:
            candidate += '}' * open_braces
        try:
            val = json.loads(candidate)
            if isinstance(val, dict):
                parsed = val
        except Exception:
            pass

    # 3. Resilient regex field extraction as ultimate fallback
    if parsed is None:
        summary_match = re.search(r'"summary"\s*:\s*"([^"\\]*(?:\\.[^"\\]*)*)', output_text)
        risk_match = re.search(r'"risk_level"\s*:\s*"(none|low|medium|high)"', output_text, re.IGNORECASE)

        summary = summary_match.group(1).replace(r'\"', '"') if summary_match else ""
        if not summary:
            summary = re.sub(r'[{}\[\]"]', '', output_text).strip()
        risk_level = risk_match.group(1).lower() if risk_match else "none"

        parsed = {
            "summary": summary[:2000] if summary else "Giám sát camera trực tiếp bình thường",
            "risk_level": risk_level,
            "events": [],
        }

    # Ensure required standard schema keys are always present
    if "risk_level" not in parsed:
        risk_match = re.search(r'"risk_level"\s*:\s*"(none|low|medium|high)"', output_text, re.IGNORECASE)
        parsed["risk_level"] = risk_match.group(1).lower() if risk_match else "none"
    if "summary" not in parsed:
        parsed["summary"] = "Giám sát camera trực tiếp bình thường"
    if "events" not in parsed or not isinstance(parsed.get("events"), list):
        parsed["events"] = []

    return parsed


_VIETNAMESE_CHARS = set("ăâđêôơưáàảãạấầẩẫậắằẳẵặéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ")
_VIETNAMESE_COMMON_WORDS = {
    "có", "không", "người", "trong", "một", "những", "đang", "được", "và",
    "tại", "khu", "vực", "hình", "ảnh", "phát", "hiện", "cần", "kiểm", "tra",
}


def _result_is_vietnamese(result: dict) -> bool:
    text = str(result.get("summary", "")).casefold()
    words = {word.strip(".,:;!?()[]{}\"'") for word in text.split()}
    return bool(_VIETNAMESE_CHARS.intersection(text)) and len(words.intersection(_VIETNAMESE_COMMON_WORDS)) >= 2


def _vietnamese_result_fallback(result: dict) -> dict:
    """Never expose an English/free-form result when Vietnamese is mandatory."""
    risk = str(result.get("risk_level", "none")).lower()
    if risk not in {"none", "low", "medium", "high"}:
        risk = "none"
    risk_text = {
        "none": "chưa ghi nhận dấu hiệu rủi ro rõ ràng",
        "low": "ghi nhận dấu hiệu mức thấp cần theo dõi",
        "medium": "ghi nhận dấu hiệu mức trung bình cần kiểm tra",
        "high": "ghi nhận dấu hiệu mức cao cần kiểm tra ngay",
    }[risk]
    return {
        "summary": (
            f"Hệ thống đã phân tích hình ảnh và {risk_text}. "
            "Mô tả chi tiết của mô hình chưa đáp ứng yêu cầu tiếng Việt; cần kiểm tra clip gốc."
        ),
        "risk_level": risk,
        "events": [],
    }


def _run_inference(
    images: list[Image.Image], detector_context: str = "", prompt_profile: str | None = None,
    sequence_context: str = "", force_vietnamese: bool = False,
) -> str:
    """Chạy inference, trả về chuỗi text từ model."""
    prompt_text = _build_prompt_text(images, detector_context, prompt_profile, sequence_context, force_vietnamese)
    request = {
        "prompt": prompt_text,
        "multi_modal_data": {"image": images},
    }
    outputs = _model.generate([request], _sampling_params)
    output_text = outputs[0].outputs[0].text if outputs and outputs[0].outputs else ""
    return output_text.strip()


def _resize_for_live_inference(image: Image.Image) -> Image.Image:
    """Keep VLM visual tokens bounded for responsive live-camera inference."""
    max_side = _cfg["max_image_side"]
    if max(image.size) <= max_side:
        return image
    resized = image.copy()
    resized.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    logger.debug("Live frame resized from %s to %s", image.size, resized.size)
    return resized


def _make_sequence_contact_sheet(images: list[Image.Image], offsets: list[float]) -> Image.Image:
    """Combine ordered frames into one labelled image for single-image VLMs.

    Cosmos-Reason2 in the deployed vLLM build accepts one image per request.
    A compact contact sheet preserves temporal context without violating that
    model constraint.  Frames remain in chronological reading order.
    """
    if not images:
        raise ValueError("sequence contains no images")
    columns = max(1, math.ceil(math.sqrt(len(images))))
    rows = math.ceil(len(images) / columns)
    max_side = int(_cfg.get("max_image_side", 960))
    cell_width = max(120, max_side // columns)
    cell_height = max(90, int(cell_width * 0.62))
    label_height = 22
    sheet = Image.new("RGB", (columns * cell_width, rows * (cell_height + label_height)), "black")
    draw = ImageDraw.Draw(sheet)
    for index, image in enumerate(images):
        frame = image.copy()
        frame.thumbnail((cell_width, cell_height), Image.Resampling.LANCZOS)
        column, row = index % columns, index // columns
        x = column * cell_width + (cell_width - frame.width) // 2
        y = row * (cell_height + label_height) + (cell_height - frame.height) // 2
        sheet.paste(frame, (x, y))
        timestamp = offsets[index] if index < len(offsets) else None
        label = f"#{index + 1}" + (f"  {timestamp:.1f}s" if timestamp is not None else "")
        draw.text((column * cell_width + 5, row * (cell_height + label_height) + cell_height + 3), label, fill="white")
    return sheet


# ── FastAPI app ────────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(app: FastAPI):
    t = threading.Thread(target=_load_model, daemon=True, name="model-loader")
    t.start()
    yield


app = FastAPI(title="Cosmos Live Service", version="1.0", lifespan=_lifespan)


@app.get("/health")
async def health():
    status, detail = _get_status()
    if status == "error":
        return JSONResponse({
            "status": "error",
            "detail": detail,
            "live_prompt_profile": _active_live_prompt_profile(),
            "audio_model": _active_audio_model_id(),
        })
    return {
        "status": status,
        "live_prompt_profile": _active_live_prompt_profile(),
        "video_model": _cfg.get("model_id"),
        "max_model_len": _cfg.get("max_model_len"),
        "max_image_side": _cfg.get("max_image_side"),
        "audio_model": _active_audio_model_id(),
        "audio_beam_size": _audio_beam_size(),
        "audio_chunk_seconds": _audio_chunk_seconds(),
        "visual_output_language": "vi",
    }


@app.post("/shutdown")
def shutdown(request: Request):
    """Opt-in, loopback-only shutdown used by the local Windows camera app."""
    if not _cfg.get("allow_shutdown"):
        return JSONResponse({"status": "error", "detail": "shutdown disabled"}, status_code=403)
    client_host = request.client.host if request.client else ""
    if client_host not in {"127.0.0.1", "::1"}:
        return JSONResponse({"status": "error", "detail": "loopback only"}, status_code=403)

    logger.info("Local camera application requested Cosmos shutdown.")
    threading.Timer(0.25, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return {"status": "shutting_down"}


@app.post("/analyze")
def analyze(
    body: bytes = Body(..., media_type="application/octet-stream"),
    x_cosmos_device_id: str | None = Header(default=None),
    x_cosmos_channel: str | None = Header(default=None),
    x_cosmos_captured_at: str | None = Header(default=None),
    x_cosmos_analysis_source: str | None = Header(default=None),
    x_cosmos_prompt_profile: str | None = Header(default=None),
):
    """
    Nhận JPEG bytes, trả JSON phân tích.
    Endpoint là def thường (không async) để uvicorn đẩy vào threadpool —
    tránh block event loop suốt thời gian inference (~4s).
    """
    status, detail = _get_status()
    if status != "ready":
        return JSONResponse(
            {"status": "error", "detail": f"service not ready: {status}"},
            status_code=503,
        )

    # Drop frame nếu model đang bận với frame trước
    if not _inference_lock.acquire(blocking=False):
        return JSONResponse({"status": "error", "detail": "busy"}, status_code=429)

    try:
        t0 = time.perf_counter()

        try:
            source_image = Image.open(io.BytesIO(body)).convert("RGB")
            image = _resize_for_live_inference(source_image)
        except Exception as exc:
            return JSONResponse(
                {"status": "error", "detail": f"invalid image: {exc}"},
                status_code=400,
            )

        active_prompt_profile = _active_live_prompt_profile(x_cosmos_prompt_profile)
        uniform_detection = None
        detector_context = ""
        if active_prompt_profile == "admissions":
            try:
                # This detector is specific to the yellow/blue admissions uniform.
                # Never run it for generic, classroom, traffic, or other contexts.
                uniform_detection = _get_staff_uniform_detector().detect(source_image)
                if uniform_detection["yellow_uniform_staff"]:
                    detector_context = (
                        "\n\nDữ kiện thị giác cần phản ánh trong báo cáo: có dấu hiệu nhân viên "
                        "mặc đồng phục vàng-xanh trong khu vực. Không nêu số lượng người hoặc "
                        "nhân viên cụ thể; chỉ mô tả định tính. Mọi câu chữ phải viết hoàn toàn "
                        "bằng tiếng Việt.\n"
                    )
            except Exception as exc:
                logger.warning("Uniform detector unavailable: %s", exc)

        try:
            result_text = _run_inference([image], detector_context, active_prompt_profile)
        except Exception as exc:
            logger.error("Inference error: %s", exc)
            return JSONResponse(
                {"status": "error", "detail": str(exc)},
                status_code=500,
            )

        inference_ms = int((time.perf_counter() - t0) * 1000)

        result = _extract_and_parse_json(result_text)
        language_retried = False
        if not _result_is_vietnamese(result):
            language_retried = True
            logger.warning("Visual result was not Vietnamese; retrying once with a strict language instruction.")
            try:
                retry_text = _run_inference(
                    [image], detector_context, active_prompt_profile, force_vietnamese=True
                )
                retry_result = _extract_and_parse_json(retry_text)
                result = retry_result if _result_is_vietnamese(retry_result) else _vietnamese_result_fallback(result)
            except Exception as exc:
                logger.warning("Vietnamese visual retry failed: %s", exc)
                result = _vietnamese_result_fallback(result)
        if not isinstance(result, dict):
            result = {
                "summary": str(result),
                "risk_level": "none",
                "events": [],
            }

        if uniform_detection is not None and isinstance(result, dict):
            staff_count = uniform_detection["yellow_uniform_staff"]
            result["yellow_uniform_staff"] = staff_count
            result["people_detected"] = uniform_detection["people_detected"]
            result["events"] = [
                event for event in result.get("events", [])
                if event.get("label") != "nhan_vien_ao_vang"
            ]
            result["events"].insert(0, {"label": "nhan_vien_ao_vang", "count": staff_count})
            if staff_count and active_prompt_profile == "admissions":
                # Headcounts from a single frame are too unreliable to report.
                # Use only the qualitative detector status, avoiding a contradictory
                # or numeric sentence generated independently by the VLM.
                result["summary"] = _vietnamese_detector_summary(
                    staff_count,
                    result.get("risk_level", "none"),
                )

        if active_prompt_profile == "admissions" and isinstance(result, dict):
            has_uniform_staff = bool(
                uniform_detection and uniform_detection.get("yellow_uniform_staff")
            )
            if not has_uniform_staff:
                result["summary"] = _vietnamese_admissions_summary(
                    result.get("risk_level", "none"),
                )

        try:
            channel = int(x_cosmos_channel) if x_cosmos_channel is not None else None
        except ValueError:
            channel = None
        captured_at = _parse_capture_time(x_cosmos_captured_at)
        # Historical event-clip analysis must not alter live-frame duplicate
        # tracking or create a second replay event for the same NVR alert.
        is_event_clip = x_cosmos_analysis_source == "event_clip"
        duplicate = False if is_event_clip else _is_duplicate_live_result(result, x_cosmos_device_id or "", channel)
        replay = None if is_event_clip or duplicate else _record_live_event(result, captured_at, x_cosmos_device_id or "", channel)

        return {
            "status": "ok",
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "inference_ms": inference_ms,
            "result": result,
            "uniform_detection": uniform_detection,
            "replay": replay,
            "duplicate": duplicate,
            "analysis_source": x_cosmos_analysis_source or "live_frame",
            "language": "vi",
            "language_retried": language_retried,
        }

    finally:
        _inference_lock.release()


@app.post("/analyze-sequence")
def analyze_sequence(
    body: bytes = Body(..., media_type="application/zip"),
    x_cosmos_prompt_profile: str | None = Header(default=None),
    x_cosmos_window_start: str | None = Header(default=None),
    x_cosmos_window_end: str | None = Header(default=None),
    x_cosmos_frame_offsets: str | None = Header(default=None),
    x_cosmos_analysis_source: str | None = Header(default=None),
):
    """Analyze a bounded, ordered set of JPEG frames packaged as a ZIP archive.

    This endpoint is deliberately separate from `/analyze`: live-camera traffic
    remains low-latency single-frame inference, while playback/test clips can
    supply temporal evidence without treating an entire long recording as one
    huge VLM request.
    """
    status, _detail = _get_status()
    if status != "ready":
        return JSONResponse({"status": "error", "detail": f"service not ready: {status}"}, status_code=503)
    if not _inference_lock.acquire(blocking=False):
        return JSONResponse({"status": "error", "detail": "busy"}, status_code=429)

    try:
        try:
            max_frames = min(12, max(2, int(os.getenv("COSMOS_SEQUENCE_MAX_FRAMES", "12"))))
            max_bytes = max(1_000_000, int(os.getenv("COSMOS_SEQUENCE_MAX_BYTES", "50000000")))
            if len(body) > max_bytes:
                raise ValueError("sequence archive exceeds size limit")
            with zipfile.ZipFile(io.BytesIO(body)) as archive:
                members = sorted(
                    (item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith((".jpg", ".jpeg", ".png"))),
                    key=lambda item: item.filename,
                )
                if not 2 <= len(members) <= max_frames:
                    raise ValueError(f"sequence must contain 2 to {max_frames} image frames")
                if sum(item.file_size for item in members) > max_bytes:
                    raise ValueError("uncompressed sequence exceeds size limit")
                images = [_resize_for_live_inference(Image.open(io.BytesIO(archive.read(item))).convert("RGB")) for item in members]
        except Exception as exc:
            return JSONResponse({"status": "error", "detail": f"invalid frame sequence: {exc}"}, status_code=400)

        offsets = []
        try:
            parsed_offsets = json.loads(x_cosmos_frame_offsets or "[]")
            if isinstance(parsed_offsets, list):
                offsets = [round(float(value), 3) for value in parsed_offsets][:len(images)]
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
        offset_text = ", ".join(f"{value:.3f}s" for value in offsets) if offsets else "không có mốc thời gian chính xác"
        sequence_context = (
            "Đây là contact sheet gồm {} frame theo đúng thứ tự thời gian, thuộc cửa sổ video {}s–{}s. "
            "Mỗi ô có nhãn # và giây tương ứng: {}. Hãy đối chiếu toàn bộ chuỗi trước khi kết luận."
        ).format(len(images), x_cosmos_window_start or "?", x_cosmos_window_end or "?", offset_text)
        active_prompt_profile = _active_live_prompt_profile(x_cosmos_prompt_profile)
        contact_sheet = _make_sequence_contact_sheet(images, offsets)
        t0 = time.perf_counter()
        try:
            result_text = _run_inference([contact_sheet], prompt_profile=active_prompt_profile, sequence_context=sequence_context)
        except Exception as exc:
            logger.error("Sequence inference error: %s", exc)
            return JSONResponse({"status": "error", "detail": str(exc)}, status_code=500)
        result = _extract_and_parse_json(result_text)
        language_retried = False
        if not _result_is_vietnamese(result):
            language_retried = True
            logger.warning("Sequence result was not Vietnamese; retrying once with a strict language instruction.")
            try:
                retry_text = _run_inference(
                    [contact_sheet], prompt_profile=active_prompt_profile,
                    sequence_context=sequence_context, force_vietnamese=True,
                )
                retry_result = _extract_and_parse_json(retry_text)
                result = retry_result if _result_is_vietnamese(retry_result) else _vietnamese_result_fallback(result)
            except Exception as exc:
                logger.warning("Vietnamese sequence retry failed: %s", exc)
                result = _vietnamese_result_fallback(result)
        return {
            "status": "ok",
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "inference_ms": int((time.perf_counter() - t0) * 1000),
            "result": result,
            "frame_count": len(images),
            "frame_offsets_seconds": offsets,
            "window_start_seconds": x_cosmos_window_start,
            "window_end_seconds": x_cosmos_window_end,
            "analysis_source": x_cosmos_analysis_source or "video_sequence",
            "language": "vi",
            "language_retried": language_retried,
        }
    finally:
        _inference_lock.release()


@app.post("/transcribe")
def transcribe(
    body: bytes = Body(..., media_type="application/octet-stream"),
    x_cosmos_device_id: str | None = Header(default=None),
    x_cosmos_channel: str | None = Header(default=None),
    x_cosmos_captured_at: str | None = Header(default=None),
    x_cosmos_audio_source: str | None = Header(default=None),
    x_cosmos_audio_sha256: str | None = Header(default=None),
):
    """Transcribe one short WAV segment captured from an opted-in camera audio stream."""
    status, detail = _get_status()
    if status != "ready":
        return JSONResponse(
            {"status": "error", "detail": f"service not ready: {status}"},
            status_code=503,
        )
    if not body:
        return JSONResponse({"status": "error", "detail": "empty audio"}, status_code=400)
    if len(body) > 20 * 1024 * 1024:
        return JSONResponse({"status": "error", "detail": "audio exceeds 20 MB"}, status_code=413)
    audio_sha256 = hashlib.sha256(body).hexdigest()
    if x_cosmos_audio_sha256 and x_cosmos_audio_sha256.casefold() != audio_sha256:
        return JSONResponse({"status": "error", "detail": "audio sha256 mismatch"}, status_code=400)
    if not _audio_inference_lock.acquire(blocking=False):
        return JSONResponse({"status": "error", "detail": "audio busy"}, status_code=429)

    wav_path = None
    try:
        with tempfile.NamedTemporaryFile(prefix="cosmos_audio_", suffix=".wav", delete=False) as output:
            output.write(body)
            wav_path = output.name
        t0 = time.perf_counter()
        min_rms = _audio_min_rms()
        speech_activity, rms, active_seconds = _has_speech_activity(body, min_rms)
        if not speech_activity:
            return {
                "status": "ok",
                "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
                "device_id": x_cosmos_device_id or "unknown",
                "channel": x_cosmos_channel,
                "captured_at": _parse_capture_time(x_cosmos_captured_at).isoformat(timespec="seconds"),
                "transcription_ms": 0,
                "text": "",
                "speech_detected": False,
                "ignored_reason": "no_speech_activity",
                "audio_rms": round(rms, 6),
                "active_speech_seconds": round(active_seconds, 3),
                "audio_source": x_cosmos_audio_source or "unknown",
                "audio_sha256": audio_sha256,
                "audio_model": _active_audio_model_id(),
            }
        language = os.getenv("COSMOS_AUDIO_LANGUAGE", "vi").strip() or None
        generate_kwargs = {
            "task": "transcribe",
            "do_sample": False,
            "num_beams": _audio_beam_size(),
            # Do not let a weak/noisy chunk inherit words from a preceding
            # chunk. This notably reduces Whisper's silence hallucinations.
            "condition_on_prev_tokens": False,
        }
        if language and language != "auto":
            generate_kwargs["language"] = language
        import torch

        with torch.inference_mode():
            # Manually keep every model call below 30 seconds. This avoids the
            # Transformers long-form timestamp path and remains stable across
            # PhoWhisper/Transformers versions.
            result = _transcribe_short_wav_chunks(wav_path, generate_kwargs)
            text = " ".join(str(result.get("text", "")).split())
            repetitive = _is_repetitive_transcript(text)
            hallucination = _is_known_audio_hallucination(text)
            excessive_rate = False
            if text:
                words = re.findall(r"\w+", text.lower(), flags=re.UNICODE)
                if words and (len(words) / max(active_seconds, 0.2)) > 5.0:
                    excessive_rate = True
            decoder_disagreement = False
            if text and _audio_requires_decoder_agreement():
                # A beam-search sentence that the greedy decoder cannot reproduce
                # is commonly language-model completion from weak audio. Reject it
                # rather than replacing it with a guessed alternative.
                verifier_kwargs = dict(generate_kwargs)
                verifier_kwargs["num_beams"] = 1
                verifier = _transcribe_short_wav_chunks(wav_path, verifier_kwargs)
                verifier_text = " ".join(str(verifier.get("text", "")).split())
                decoder_disagreement = not _audio_transcripts_agree(text, verifier_text)
        duplicate = _is_duplicate_audio_transcript(text, x_cosmos_device_id or "unknown", x_cosmos_channel)
        ignored_reason = None
        if repetitive:
            ignored_reason = "repetitive_transcript"
        elif hallucination:
            ignored_reason = "known_hallucination"
        elif excessive_rate:
            ignored_reason = "hallucination_speech_rate"
        elif decoder_disagreement:
            ignored_reason = "decoder_disagreement"
        elif duplicate:
            ignored_reason = "duplicate_transcript"
        if ignored_reason:
            logger.info(
                "Suppressed audio transcription reason=%s device=%s channel=%s",
                ignored_reason, x_cosmos_device_id, x_cosmos_channel,
            )
            text = ""
        return {
            "status": "ok",
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "device_id": x_cosmos_device_id or "unknown",
            "channel": x_cosmos_channel,
            "captured_at": _parse_capture_time(x_cosmos_captured_at).isoformat(timespec="seconds"),
            "transcription_ms": int((time.perf_counter() - t0) * 1000),
            "text": text,
            "speech_detected": bool(text),
            "ignored_reason": ignored_reason,
            "audio_rms": round(rms, 6),
            "active_speech_seconds": round(active_seconds, 3),
            "audio_source": x_cosmos_audio_source or "unknown",
            "audio_sha256": audio_sha256,
            "audio_model": _active_audio_model_id(),
        }
    except Exception as exc:
        logger.exception("Audio transcription failed")
        return JSONResponse({"status": "error", "detail": str(exc)}, status_code=500)
    finally:
        if wav_path:
            try:
                Path(wav_path).unlink(missing_ok=True)
            except OSError:
                pass
        _audio_inference_lock.release()


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Cosmos Live Service")
    parser.add_argument(
        "--model-id",
        default="nvidia/Cosmos-Reason2-2B",
        help="HuggingFace model ID (default: nvidia/Cosmos-Reason2-2B)",
    )
    parser.add_argument(
        "--gpu-memory-utilization",
        type=float,
        default=0.55,
        metavar="FLOAT",
        help="Phần VRAM dành cho vllm, ví dụ 0.85 (default: 0.85 — benchmark để chốt)",
    )
    parser.add_argument(
        "--max-model-len",
        type=int,
        default=4096,
        help="Max context length (default: 4096 — đủ cho prompt và contact-sheet video)",
    )
    parser.add_argument(
        "--max-new-tokens",
        type=int,
        default=256,
        help="Max tokens model sinh ra (default: 256)",
    )
    parser.add_argument(
        "--max-image-side", type=int, default=960, metavar="PIXELS",
        help="Resize live frames so their longest side is at most this value (default: 960)",
    )
    parser.add_argument(
        "--allow-shutdown", action="store_true",
        help="Allow a loopback camera app to stop this service via POST /shutdown.",
    )
    parser.add_argument("--hf-token", default=None, metavar="TOKEN",
                        help="HuggingFace access token cho gated model (hf_xxx...)")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    if not 0 < args.gpu_memory_utilization <= 1:
        parser.error("--gpu-memory-utilization phải trong khoảng (0, 1]")

    if args.hf_token:
        try:
            from huggingface_hub import login as hf_login
            hf_login(token=args.hf_token, add_to_git_credential=False)
            logger.info("HuggingFace login OK.")
        except Exception as exc:
            logger.warning("HuggingFace login failed: %s", exc)

    _cfg.update(
        {
            "model_id": args.model_id,
            "gpu_memory_utilization": args.gpu_memory_utilization,
            "max_model_len": args.max_model_len,
            "max_new_tokens": args.max_new_tokens,
            "max_image_side": args.max_image_side,
            "allow_shutdown": args.allow_shutdown,
        }
    )

    logger.info(
        "Cosmos Live Service  host=%s  port=%d  model=%s  gpu_util=%.2f",
        args.host, args.port, args.model_id, args.gpu_memory_utilization,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
