"""Import CameraAI metadata from SQLite into PostgreSQL without touching clips.

Default mode is an inventory-only dry run.  ``--apply`` is idempotent: it
upserts by the original SQLite event ID, so a retry does not duplicate events.
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import database

TIMEZONE_VN = timezone(timedelta(hours=7))
SCHEMA_PATH = Path(__file__).with_name("postgres_schema.sql")


def parse_timestamp(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value).replace(tzinfo=TIMEZONE_VN)
    except ValueError:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=TIMEZONE_VN)


def parse_json(value: str | None, fallback):
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def sqlite_inventory() -> dict:
    conn = database.get_db_connection()
    counts = {}
    for table in ("events", "audio_analyses", "video_analyses"):
        counts[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    counts["events_with_clip"] = conn.execute(
        "SELECT COUNT(*) FROM events WHERE clip_filename IS NOT NULL AND clip_filename != ''"
    ).fetchone()[0]
    counts["channels"] = conn.execute("SELECT COUNT(DISTINCT channel) FROM events").fetchone()[0]
    conn.close()
    return counts


def connect(database_url: str):
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("Thiếu psycopg. Chạy: pip install -r CameraAI/requirements.txt") from exc
    return psycopg.connect(database_url)


def apply(database_url: str, storage_backend: str) -> dict:
    from psycopg.types.json import Jsonb

    source = database.get_db_connection()
    events = [dict(row) for row in source.execute("SELECT * FROM events ORDER BY id")]
    audio_by_event = {row["event_id"]: dict(row) for row in source.execute("SELECT * FROM audio_analyses")}
    video_by_event = {row["event_id"]: dict(row) for row in source.execute("SELECT * FROM video_analyses")}
    source.close()

    with connect(database_url) as target:
        with target.cursor() as cursor:
            cursor.execute(SCHEMA_PATH.read_text(encoding="utf-8"))
            cursor.execute(
                "INSERT INTO storage_policies(name, primary_backend, retention_days) VALUES ('default', %s, 90) ON CONFLICT (name) DO NOTHING",
                (storage_backend,),
            )
            for event in events:
                camera_code = f"cam-{int(event['channel']):03d}"
                cursor.execute(
                    "INSERT INTO cameras(code, channel, name) VALUES (%s, %s, %s) ON CONFLICT (code) DO UPDATE SET channel = EXCLUDED.channel",
                    (camera_code, event["channel"], f"Camera {event['channel']:02d}"),
                )
                cursor.execute(
                    """
                    INSERT INTO camera_events (legacy_event_id, camera_code, channel, occurred_at, event_code, event_type, description, severity, audio_level_db, raw_metadata)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (legacy_event_id) DO UPDATE SET
                        camera_code = EXCLUDED.camera_code, channel = EXCLUDED.channel, occurred_at = EXCLUDED.occurred_at,
                        event_code = EXCLUDED.event_code, event_type = EXCLUDED.event_type, description = EXCLUDED.description,
                        severity = EXCLUDED.severity, audio_level_db = EXCLUDED.audio_level_db, raw_metadata = EXCLUDED.raw_metadata
                    RETURNING id
                    """,
                    (event["id"], camera_code, event["channel"], parse_timestamp(event["timestamp"]), event["event_code"], event["event_type"], event["description"], event["severity"], event["audio_level_db"], Jsonb(parse_json(event["metadata_json"], {}))),
                )
                target_event_id = cursor.fetchone()[0]
                if event["clip_filename"]:
                    cursor.execute(
                        """
                        INSERT INTO video_assets (event_id, camera_code, relative_path, duration_seconds)
                        VALUES (%s, %s, %s, %s)
                        ON CONFLICT (event_id) DO UPDATE SET camera_code = EXCLUDED.camera_code, relative_path = EXCLUDED.relative_path, duration_seconds = EXCLUDED.duration_seconds
                        RETURNING id
                        """,
                        (target_event_id, camera_code, event["clip_filename"], event["clip_duration_sec"]),
                    )
                    asset_id = cursor.fetchone()[0]
                    cursor.execute(
                        """
                        INSERT INTO video_replicas (video_asset_id, storage_backend, object_key, state, verified_at)
                        VALUES (%s, %s, %s, 'available', now())
                        ON CONFLICT (video_asset_id, storage_backend) DO UPDATE SET object_key = EXCLUDED.object_key, state = 'available', verified_at = now(), last_error = NULL
                        """,
                        (asset_id, storage_backend, event["clip_filename"]),
                    )
                audio = audio_by_event.get(event["id"])
                if audio:
                    cursor.execute(
                        """INSERT INTO audio_analyses (event_id, status, transcript, segments, speech_detected, audio_rms, active_speech_seconds, ignored_reason, audio_model, suggestion, error_message, created_at, analyzed_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (event_id) DO UPDATE SET status=EXCLUDED.status, transcript=EXCLUDED.transcript, segments=EXCLUDED.segments, speech_detected=EXCLUDED.speech_detected, audio_rms=EXCLUDED.audio_rms, active_speech_seconds=EXCLUDED.active_speech_seconds, ignored_reason=EXCLUDED.ignored_reason, audio_model=EXCLUDED.audio_model, suggestion=EXCLUDED.suggestion, error_message=EXCLUDED.error_message, analyzed_at=EXCLUDED.analyzed_at""",
                        (target_event_id, audio["status"], audio["transcript"], Jsonb(parse_json(audio["segments_json"], [])), bool(audio["speech_detected"]) if audio["speech_detected"] is not None else None, audio["audio_rms"], audio["active_speech_seconds"], audio["ignored_reason"], audio["audio_model"], Jsonb(parse_json(audio["suggestion_json"], None)), audio["error_message"], parse_timestamp(audio["created_at"]), parse_timestamp(audio["analyzed_at"])),
                    )
                video = video_by_event.get(event["id"])
                if video:
                    cursor.execute(
                        """INSERT INTO video_analyses (event_id, status, summary, risk_level, detected_events, frames, video_model, error_message, created_at, analyzed_at)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (event_id) DO UPDATE SET status=EXCLUDED.status, summary=EXCLUDED.summary, risk_level=EXCLUDED.risk_level, detected_events=EXCLUDED.detected_events, frames=EXCLUDED.frames, video_model=EXCLUDED.video_model, error_message=EXCLUDED.error_message, analyzed_at=EXCLUDED.analyzed_at""",
                        (target_event_id, video["status"], video["summary"], video["risk_level"], Jsonb(parse_json(video["events_json"], [])), Jsonb(parse_json(video["frames_json"], [])), video["video_model"], video["error_message"], parse_timestamp(video["created_at"]), parse_timestamp(video["analyzed_at"])),
                    )
            cursor.execute("INSERT INTO audit_logs(actor, action, resource_type, details) VALUES ('sqlite-migration', 'upsert', 'camera_metadata', %s)", (Jsonb({"events": len(events), "storage_backend": storage_backend}),))
    return {**sqlite_inventory(), "mode": "applied", "storage_backend": storage_backend}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Migrate CameraAI metadata from SQLite to PostgreSQL safely.")
    parser.add_argument("--apply", action="store_true", help="Create schema and upsert SQLite metadata into PostgreSQL.")
    parser.add_argument("--storage-backend", default="nas_primary", help="Replica backend name recorded for migrated clips.")
    args = parser.parse_args()
    database_url = os.getenv("CAMERAAI_POSTGRES_URL", "").strip()
    inventory = sqlite_inventory()
    if not args.apply:
        print(json.dumps({**inventory, "mode": "dry_run", "next": "Set CAMERAAI_POSTGRES_URL then rerun with --apply."}, ensure_ascii=False))
    elif not database_url:
        raise SystemExit("Thiếu CAMERAAI_POSTGRES_URL. Không có dữ liệu nào bị thay đổi.")
    else:
        print(json.dumps(apply(database_url, args.storage_backend), ensure_ascii=False))
