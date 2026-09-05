import hashlib
import json
import math
import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Callable, Dict, Iterator, List, Optional

import cv2
from PIL import Image


@dataclass
class VideoChunk:
    index: int
    start_seconds: float
    end_seconds: float
    path: Optional[Path]
    frames: List[Image.Image]


def seconds_to_hhmmss(seconds: float, mode: str = "round") -> str:
    if mode == "floor":
        seconds = int(math.floor(seconds))
    elif mode == "ceil":
        seconds = int(math.ceil(seconds))
    else:
        seconds = int(round(seconds))
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def hhmmss_to_seconds(value: str) -> int:
    if not value:
        return 0
    parts = [float(part) for part in str(value).split(":")]
    while len(parts) < 3:
        parts.insert(0, 0.0)
    hours, minutes, seconds = parts[-3:]
    return int(hours * 3600 + minutes * 60 + seconds)


def build_video_id(video_path: Path) -> str:
    video_path = video_path.resolve()
    stat = video_path.stat()
    key = f"{video_path}:{stat.st_size}:{stat.st_mtime_ns}"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
    safe_stem = re.sub(r"[^a-zA-Z0-9_.-]+", "_", video_path.stem).strip("._")
    return f"{safe_stem or 'video'}-{digest}"


def get_video_info(video_path: Path) -> Dict[str, float]:
    try:
        return _get_video_info_ffprobe(video_path)
    except Exception:
        return _get_video_info_cv2(video_path)


def _get_video_info_ffprobe(video_path: Path) -> Dict[str, float]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        raise RuntimeError("ffprobe is not available")

    cmd = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate,nb_frames:format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    process = subprocess.run(
        cmd,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    payload = json.loads(process.stdout)
    stream = (payload.get("streams") or [{}])[0]
    fmt = payload.get("format") or {}

    fps = _parse_fps(stream.get("avg_frame_rate")) or _parse_fps(stream.get("r_frame_rate"))
    duration = float(fmt.get("duration") or 0.0)
    frame_count = float(stream.get("nb_frames") or 0.0)
    if not frame_count and fps and duration:
        frame_count = fps * duration

    return {
        "fps": fps,
        "frame_count": frame_count,
        "duration_seconds": duration,
        "width": int(stream.get("width") or 0),
        "height": int(stream.get("height") or 0),
    }


def _parse_fps(value: str) -> float:
    if not value or value == "0/0":
        return 0.0
    if "/" in value:
        numerator, denominator = value.split("/", 1)
        denominator_value = float(denominator)
        if denominator_value == 0:
            return 0.0
        return float(numerator) / denominator_value
    return float(value)


def _get_video_info_cv2(video_path: Path) -> Dict[str, float]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 0
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration_seconds = frame_count / fps if fps > 0 else 0
    cap.release()

    return {
        "fps": fps,
        "frame_count": frame_count,
        "duration_seconds": duration_seconds,
        "width": width,
        "height": height,
    }


def prepare_video_chunks(
    video_path: Path,
    chunk_seconds: int = 10,
    chunks_root: Path = Path("outputs/chunks"),
    overwrite: bool = False,
    encoder: str = "auto",
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> List[Dict[str, object]]:
    if chunk_seconds <= 0:
        raise ValueError("chunk_seconds must be > 0")

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to cut video chunks, but it was not found in PATH")

    video_id = build_video_id(video_path)
    chunks_dir = chunks_root / video_id
    chunks_dir.mkdir(parents=True, exist_ok=True)

    info = get_video_info(video_path)
    duration = float(info["duration_seconds"])
    if duration <= 0:
        raise RuntimeError(f"Cannot determine video duration: {video_path}")

    chunk_count = int(math.ceil(duration / chunk_seconds))
    if progress_callback:
        progress_callback(0, chunk_count)
    manifest_path = chunks_dir / "chunks.json"
    rebuild_chunks = bool(overwrite)

    if not overwrite and manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        chunks = manifest.get("chunks", [])
        reusable = (
            manifest.get("chunk_seconds") == chunk_seconds
            and manifest.get("encoder") == encoder
            and manifest.get("source_size") == video_path.stat().st_size
            and manifest.get("source_mtime_ns") == video_path.stat().st_mtime_ns
            and _manifest_is_reusable(chunks, chunk_count)
        )
        if reusable:
            return chunks
        rebuild_chunks = True
    elif not overwrite and any(chunks_dir.glob("chunk_*.mp4")):
        rebuild_chunks = True

    chunks: List[Dict[str, object]] = []
    for index in range(chunk_count):
        start = index * chunk_seconds
        end = min(start + chunk_seconds, duration)
        chunk_path = chunks_dir / f"chunk_{index:04d}.mp4"

        if rebuild_chunks or not chunk_path.exists() or chunk_path.stat().st_size == 0:
            _cut_chunk_with_ffmpeg(
                ffmpeg=ffmpeg,
                video_path=video_path,
                chunk_path=chunk_path,
                start_seconds=start,
                duration_seconds=end - start,
                encoder=encoder,
            )

        chunks.append(
            {
                "index": index,
                "start_seconds": float(start),
                "end_seconds": float(end),
                "start": seconds_to_hhmmss(start, mode="floor"),
                "end": seconds_to_hhmmss(end, mode="ceil"),
                "path": str(chunk_path),
            }
        )
        if progress_callback:
            progress_callback(index + 1, chunk_count)

    for stale_path in chunks_dir.glob("chunk_*.mp4"):
        try:
            stale_index = int(stale_path.stem.rsplit("_", 1)[-1])
            if stale_index >= chunk_count:
                stale_path.unlink()
        except (OSError, ValueError):
            pass

    manifest = {
        "video_file": str(video_path),
        "video_id": video_id,
        "chunk_seconds": chunk_seconds,
        "encoder": encoder,
        "source_size": video_path.stat().st_size,
        "source_mtime_ns": video_path.stat().st_mtime_ns,
        "duration_seconds": duration,
        "chunks": chunks,
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return chunks


def build_direct_chunk_manifest(video_path: Path, chunk_seconds: int) -> List[Dict[str, object]]:
    """Describe analysis windows without creating intermediate video files."""
    if chunk_seconds <= 0:
        raise ValueError("chunk_seconds must be > 0")
    duration = float(get_video_info(video_path)["duration_seconds"])
    if duration <= 0:
        raise RuntimeError(f"Cannot determine video duration: {video_path}")
    chunks: List[Dict[str, object]] = []
    for index in range(int(math.ceil(duration / chunk_seconds))):
        start = index * chunk_seconds
        end = min(start + chunk_seconds, duration)
        chunks.append(
            {
                "index": index,
                "start_seconds": float(start),
                "end_seconds": float(end),
                "start": seconds_to_hhmmss(start, mode="floor"),
                "end": seconds_to_hhmmss(end, mode="ceil"),
                "path": "",
            }
        )
    return chunks


def _manifest_is_reusable(chunks: List[Dict[str, object]], expected_count: int) -> bool:
    if len(chunks) != expected_count:
        return False
    for chunk in chunks:
        path = Path(str(chunk.get("path", "")))
        if not path.exists() or path.stat().st_size == 0:
            return False
    return True


def _cut_chunk_with_ffmpeg(
    ffmpeg: str,
    video_path: Path,
    chunk_path: Path,
    start_seconds: float,
    duration_seconds: float,
    encoder: str = "auto",
) -> None:
    chunk_path.parent.mkdir(parents=True, exist_ok=True)
    selected_encoder = _resolve_encoder(encoder)
    cmd = _build_ffmpeg_chunk_command(
        ffmpeg=ffmpeg,
        video_path=video_path,
        chunk_path=chunk_path,
        start_seconds=start_seconds,
        duration_seconds=duration_seconds,
        encoder=selected_encoder,
    )
    process = _run_ffmpeg(cmd)

    if process.returncode != 0 and selected_encoder == "nvenc":
        cpu_cmd = _build_ffmpeg_chunk_command(
            ffmpeg=ffmpeg,
            video_path=video_path,
            chunk_path=chunk_path,
            start_seconds=start_seconds,
            duration_seconds=duration_seconds,
            encoder="cpu",
        )
        process = _run_ffmpeg(cpu_cmd)

    if process.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed while cutting {video_path} at {start_seconds:.3f}s: "
            f"{process.stderr.strip()}"
        )


def _build_ffmpeg_chunk_command(
    ffmpeg: str,
    video_path: Path,
    chunk_path: Path,
    start_seconds: float,
    duration_seconds: float,
    encoder: str,
) -> List[str]:
    base_cmd = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        f"{start_seconds:.3f}",
        "-i",
        str(video_path),
        "-t",
        f"{duration_seconds:.3f}",
        "-map",
        "0:v:0",
        "-an",
    ]

    if encoder == "copy":
        codec_args = ["-c:v", "copy"]
    elif encoder == "nvenc":
        codec_args = [
            "-c:v",
            "h264_nvenc",
            "-preset",
            "p2",
            "-tune",
            "hq",
            "-rc",
            "vbr",
            "-cq",
            "23",
            "-b:v",
            "0",
        ]
    else:
        codec_args = [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "24",
            "-threads",
            "12",
        ]

    return [
        *base_cmd,
        *codec_args,
        "-pix_fmt",
        "yuv420p",
        "-avoid_negative_ts",
        "make_zero",
        str(chunk_path),
    ]


def _run_ffmpeg(cmd: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _resolve_encoder(encoder: str) -> str:
    if encoder == "auto":
        return "nvenc" if _has_ffmpeg_encoder("h264_nvenc") else "cpu"
    if encoder == "nvenc" and not _has_ffmpeg_encoder("h264_nvenc"):
        return "cpu"
    return encoder


def _has_ffmpeg_encoder(name: str) -> bool:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        process = subprocess.run(
            [ffmpeg, "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return name in process.stdout
    except Exception:
        return False


def iter_video_chunks(
    video_path: Path,
    chunk_seconds: int = 10,
    sample_fps: float = 1.0,
    chunks_root: Path = Path("outputs/chunks"),
    overwrite: bool = False,
    encoder: str = "auto",
    direct_sampling: bool = False,
    max_image_side: Optional[int] = None,
) -> Iterator[VideoChunk]:
    if sample_fps <= 0:
        raise ValueError("sample_fps must be > 0")

    manifest = (
        build_direct_chunk_manifest(video_path, chunk_seconds)
        if direct_sampling
        else prepare_video_chunks(
            video_path=video_path,
            chunk_seconds=chunk_seconds,
            chunks_root=chunks_root,
            overwrite=overwrite,
            encoder=encoder,
        )
    )
    for item in manifest:
        start = float(item["start_seconds"])
        end = float(item["end_seconds"])
        chunk_path = Path(str(item["path"])) if item.get("path") else None
        frames = (
            sample_frames(video_path, start, end, sample_fps, max_image_side=max_image_side)
            if direct_sampling
            else sample_frames(chunk_path, 0.0, end - start, sample_fps, max_image_side=max_image_side)
        )
        yield VideoChunk(
            index=int(item["index"]),
            start_seconds=start,
            end_seconds=end,
            path=chunk_path,
            frames=frames,
        )


def sample_frames(
    video_path: Path,
    start_seconds: float,
    end_seconds: float,
    sample_fps: float = 1.0,
    max_image_side: Optional[int] = None,
) -> List[Image.Image]:
    if sample_fps <= 0:
        raise ValueError("sample_fps must be > 0")

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Cannot open video: {video_path}")

    frames: List[Image.Image] = []
    step = 1.0 / sample_fps
    t = max(0.0, start_seconds)

    while t < end_seconds:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if ok and frame is not None:
            frames.append(_frame_to_image(frame, max_image_side))
        t += step

    if not frames and end_seconds > start_seconds:
        cap.set(cv2.CAP_PROP_POS_MSEC, ((start_seconds + end_seconds) / 2.0) * 1000.0)
        ok, frame = cap.read()
        if ok and frame is not None:
            frames.append(_frame_to_image(frame, max_image_side))

    cap.release()
    return frames


def _frame_to_image(frame, max_image_side: Optional[int]) -> Image.Image:
    height, width = frame.shape[:2]
    if max_image_side and max_image_side > 0 and max(height, width) > max_image_side:
        scale = float(max_image_side) / float(max(height, width))
        frame = cv2.resize(
            frame,
            (max(1, int(round(width * scale))), max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    return Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
