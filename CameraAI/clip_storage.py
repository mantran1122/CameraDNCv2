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


def resolve_clip_path(reference: str) -> Path:
    """Resolve a database reference without allowing traversal outside clip root."""
    if not reference:
        raise ValueError("Clip reference is empty")
    normalized = reference.replace("\\", "/")
    relative = PurePosixPath(normalized)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Invalid clip reference")
    root = Path(config.CLIPS_DIR).resolve()
    path = (root / Path(*relative.parts)).resolve()
    if path != root and root not in path.parents:
        raise ValueError("Clip path is outside storage root")
    return path


def legacy_clip_details(filename: str):
    """Parse deployed legacy name ``clip_chN_YYYYMMDD_HHMMSS.mp4`` if possible."""
    match = re.fullmatch(r"clip_ch(?P<channel>\d+)_(?P<date>\d{8})_(?P<time>\d{6})\.mp4", filename, re.IGNORECASE)
    if not match:
        return None
    event_time = datetime.strptime(match.group("date") + match.group("time"), "%Y%m%d%H%M%S")
    return int(match.group("channel")), event_time
