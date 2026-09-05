"""Read-only health and reconciliation checks for SQLite, PostgreSQL and NAS."""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from typing import Any

import config
import database
from clip_storage import resolve_clip_path

_cache: dict[str, Any] = {"at": 0.0, "value": None}
_lock = threading.Lock()


def _sqlite_counts() -> dict[str, Any]:
    conn = database.get_db_connection()
    values = {
        "events": conn.execute("SELECT COUNT(*) FROM events").fetchone()[0],
        "clips": conn.execute("SELECT COUNT(*) FROM events WHERE clip_filename IS NOT NULL AND clip_filename != ''").fetchone()[0],
        "unique_clip_references": conn.execute("SELECT COUNT(DISTINCT clip_filename) FROM events WHERE clip_filename IS NOT NULL AND clip_filename != ''").fetchone()[0],
        "audio_analyses": conn.execute("SELECT COUNT(*) FROM audio_analyses").fetchone()[0],
        "video_analyses": conn.execute("SELECT COUNT(*) FROM video_analyses").fetchone()[0],
    }
    outbox = conn.execute("SELECT action, COUNT(*) AS total, SUM(CASE WHEN attempts > 0 THEN 1 ELSE 0 END) AS failed FROM postgres_sync_outbox GROUP BY action").fetchall()
    references = [row[0] for row in conn.execute("SELECT DISTINCT clip_filename FROM events WHERE clip_filename IS NOT NULL AND clip_filename != ''").fetchall()]
    conn.close()
    missing = 0
    for reference in references:
        try:
            if not resolve_clip_path(reference).is_file(): missing += 1
        except ValueError:
            missing += 1
    values["missing_clip_references"] = missing
    values["outbox"] = {row["action"]: {"pending": row["total"], "failed_attempts": row["failed"] or 0} for row in outbox}
    return values


def _nas_counts() -> dict[str, Any]:
    root = Path(config.CLIPS_DIR)
    if not root.exists():
        return {"state": "unavailable", "path": str(root), "files": 0, "size_bytes": 0}
    count = size = 0
    try:
        for path in root.rglob("*.mp4"):
            if path.is_file():
                count += 1; size += path.stat().st_size
        return {"state": "available", "path": str(root), "files": count, "size_bytes": size}
    except OSError as exc:
        return {"state": "error", "path": str(root), "files": count, "size_bytes": size, "error": str(exc)}


def _postgres_counts() -> dict[str, Any]:
    conninfo = os.getenv("CAMERAAI_POSTGRES_URL", "").strip()
    if not conninfo:
        return {"state": "not_configured"}
    try:
        import psycopg
        with psycopg.connect(conninfo, connect_timeout=5) as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT (SELECT COUNT(*) FROM camera_events), (SELECT COUNT(*) FROM video_assets), (SELECT COUNT(*) FROM audio_analyses), (SELECT COUNT(*) FROM video_analyses)")
                row = cursor.fetchone()
        return {"state": "available", "events": row[0], "clips": row[1], "audio_analyses": row[2], "video_analyses": row[3]}
    except Exception as exc:
        return {"state": "error", "error": str(exc)[:500]}


def _comparison(sqlite: dict[str, Any], postgres: dict[str, Any]) -> list[dict[str, Any]]:
    names = ("events", "clips", "audio_analyses", "video_analyses")
    if postgres.get("state") != "available":
        return [{"name": name, "sqlite": sqlite[name], "postgres": None, "difference": None, "state": postgres.get("state")} for name in names]
    return [{"name": name, "sqlite": sqlite[name], "postgres": postgres[name], "difference": postgres[name] - sqlite[name], "state": "match" if postgres[name] == sqlite[name] else "mismatch"} for name in names]


def get_data_health(force: bool = False) -> dict[str, Any]:
    with _lock:
        if not force and _cache["value"] is not None and time.monotonic() - _cache["at"] < 30:
            return _cache["value"]
        sqlite = _sqlite_counts()
        postgres = _postgres_counts()
        value = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "sqlite": sqlite, "postgres": postgres, "nas": _nas_counts(), "comparison": _comparison(sqlite, postgres)}
        _cache.update({"at": time.monotonic(), "value": value})
        return value
