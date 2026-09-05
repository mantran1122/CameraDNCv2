"""Test the live-service audio pipeline with a local video file.

The script extracts mono PCM WAV at 16 kHz, splits it into the same short
segments used by the camera client, and posts every segment to /transcribe.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import wave
from datetime import timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def extract_wav(video_path: Path, wav_path: Path) -> None:
    """Extract the first audio stream in the format expected by live_service."""
    command = [
        "ffmpeg", "-y", "-i", str(video_path), "-map", "0:a:0?", "-vn",
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav_path),
    ]
    completed = subprocess.run(command, text=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if completed.returncode:
        raise RuntimeError(f"FFmpeg could not extract audio:\n{completed.stderr.strip()}")
    if not wav_path.exists() or wav_path.stat().st_size <= 44:
        raise RuntimeError("Video has no usable audio stream.")


def post_wav(url: str, body: bytes, device_id: str, channel: str) -> dict:
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/octet-stream",
            "X-Cosmos-Device-Id": device_id,
            "X-Cosmos-Channel": channel,
            "X-Cosmos-Audio-Source": "local-video-test",
        },
    )
    try:
        with urlopen(request, timeout=180) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Service returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach live service at {url}: {exc.reason}") from exc


def format_offset(seconds: float) -> str:
    return str(timedelta(seconds=int(seconds))).zfill(8)


def transcribe_video(video_path: Path, service_url: str, chunk_seconds: float, device_id: str, channel: str) -> list[dict]:
    with tempfile.TemporaryDirectory(prefix="cosmos_video_test_") as temp_dir:
        wav_path = Path(temp_dir) / "input.wav"
        extract_wav(video_path, wav_path)
        results: list[dict] = []
        with wave.open(str(wav_path), "rb") as source:
            if source.getnchannels() != 1 or source.getframerate() != 16000 or source.getsampwidth() != 2:
                raise RuntimeError("Extracted WAV does not match mono PCM16 / 16 kHz.")
            frames_per_chunk = max(1, round(chunk_seconds * source.getframerate()))
            chunk_index = 0
            while frames := source.readframes(frames_per_chunk):
                chunk_path = Path(temp_dir) / f"chunk_{chunk_index:04d}.wav"
                with wave.open(str(chunk_path), "wb") as chunk:
                    chunk.setparams(source.getparams())
                    chunk.writeframes(frames)
                result = post_wav(service_url, chunk_path.read_bytes(), device_id, channel)
                result["video_offset_seconds"] = round(chunk_index * chunk_seconds, 3)
                results.append(result)
                text = result.get("text", "")
                reason = result.get("ignored_reason")
                print(f"[{format_offset(chunk_index * chunk_seconds)}] {text or f'<ignored: {reason}>'}")
                chunk_index += 1
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Send a local video's audio through Cosmos /transcribe.")
    parser.add_argument("video", type=Path, help="Path to MP4/MKV/AVI or another FFmpeg-supported video")
    parser.add_argument("--url", default="http://127.0.0.1:8770/transcribe", help="Live-service /transcribe URL")
    parser.add_argument("--chunk-seconds", type=float, default=10, help="Audio length per request (default: 10)")
    parser.add_argument("--device-id", default="local-video-test", help="Diagnostic device id sent to the service")
    parser.add_argument("--channel", default="test", help="Diagnostic channel sent to the service")
    parser.add_argument("--output", type=Path, help="Optional JSON file containing every service response")
    args = parser.parse_args()

    if not args.video.is_file():
        parser.error(f"Video not found: {args.video}")
    if args.chunk_seconds <= 0 or args.chunk_seconds > 600:
        parser.error("--chunk-seconds must be between 0 and 600.")
    try:
        results = transcribe_video(args.video, args.url, args.chunk_seconds, args.device_id, args.channel)
    except (OSError, RuntimeError, wave.Error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Saved detailed responses to: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
