"""Canonical, safe paths for abnormal-video evidence.

`clip_filename` in the current SQLite database is retained for compatibility,
but from now on it stores a POSIX relative path below ``config.CLIPS_DIR``.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path, PurePosixPath
import re

import config


def camera_code(channel: int) -> str:
    if channel < 1:
        raise ValueError("Camera channel must be positive")
    return f"cam-{channel:03d}"


def build_clip_reference(channel: int, event_time: datetime, event_id: int) -> str:
    """Return the canonical, database-safe relative path for an event clip."""
    camera = camera_code(channel)
    filename = f"evt_{camera}_{event_time.strftime('%Y%m%dT%H%M%S')}_{event_id}.mp4"
    return PurePosixPath(
        "cameras", camera, event_time.strftime("%Y"), event_time.strftime("%m"), event_time.strftime("%d"), filename
    ).as_posix()


def resolve_clip_path(reference: str, fetch_remote: bool = True) -> Path:
    """Resolve a safe clip path, downloading it from remote storage on demand."""
    if not reference:
        raise ValueError("Clip reference is empty")
    normalized = reference.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid clip reference")

    # 1. Primary check: config.CLIPS_DIR
    try:
        root = Path(config.CLIPS_DIR).resolve()
        path = (root / Path(*relative.parts)).resolve()
        if path.is_file():
            return path
    except Exception:
        path = None

    # 2. Multi-root fallback: Check Z:\dataCameraAI, direct UNC path, and local storage
    candidates = [
        Path("Z:/dataCameraAI"),
        Path(r"\\192.168.100.3\Common\dataCameraAI"),
        (Path(__file__).resolve().parent / "storage" / "clips").resolve(),
    ]
    for cand in candidates:
        try:
            cand_path = (cand / Path(*relative.parts))
            if cand_path.is_file():
                return cand_path
        except Exception:
            pass

    local_path = path if path is not None else (Path(config.CLIPS_DIR) / Path(*relative.parts))
    if fetch_remote:
        try:
            from synology_storage import download_clip, enabled
            if enabled() and download_clip(relative.as_posix(), local_path):
                return local_path
        except Exception as exc:
            # Keep local capture and offline playback usable while the NAS is
            # temporarily unavailable. Callers will handle a missing file.
            print(f"[Synology Storage] Download skipped for {relative.as_posix()}: {exc}")
    return local_path


def mirror_clip(reference: str) -> bool:
    """Upload an existing local clip to the configured remote backend."""
    local_path = resolve_clip_path(reference, fetch_remote=False)
    if not local_path.is_file():
        return False
    try:
        from synology_storage import enabled, upload_clip
        return upload_clip(reference, local_path) if enabled() else False
    except Exception as exc:
        print(f"[Synology Storage] Upload failed for {reference}: {exc}")
        return False


def legacy_clip_details(filename: str):
    """Parse deployed legacy name ``clip_chN_YYYYMMDD_HHMMSS.mp4`` if possible."""
    match = re.fullmatch(r"clip_ch(?P<channel>\d+)_(?P<date>\d{8})_(?P<time>\d{6})\.mp4", filename, re.IGNORECASE)
    if not match:
        return None
    event_time = datetime.strptime(match.group("date") + match.group("time"), "%Y%m%d%H%M%S")
    return int(match.group("channel")), event_time
