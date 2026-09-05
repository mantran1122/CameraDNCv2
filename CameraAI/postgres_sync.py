"""Reliable SQLite outbox -> PostgreSQL replication for newly written metadata."""
from __future__ import annotations

import json
import os
from typing import Any

import database
from migrate_sqlite_to_postgres import parse_json, parse_timestamp


def enabled() -> bool:
    return os.getenv("CAMERAAI_POSTGRES_DUAL_WRITE", "").strip().lower() in {"1", "true", "yes"} and bool(os.getenv("CAMERAAI_POSTGRES_URL", "").strip())


def _connect():
    import psycopg
    return psycopg.connect(os.environ["CAMERAAI_POSTGRES_URL"])


def _upsert_event(target, event_id: int, backend: str) -> None:
    from psycopg.types.json import Jsonb
    source = database.get_db_connection()
    event_row = source.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if not event_row:
        source.close()
        return
    event = dict(event_row)
    audio = source.execute("SELECT * FROM audio_analyses WHERE event_id = ?", (event_id,)).fetchone()
    video = source.execute("SELECT * FROM video_analyses WHERE event_id = ?", (event_id,)).fetchone()
    source.close()
    camera = f"cam-{int(event['channel']):03d}"
    with target.cursor() as cursor:
        cursor.execute("INSERT INTO cameras(code, channel, name) VALUES (%s,%s,%s) ON CONFLICT (code) DO UPDATE SET channel=EXCLUDED.channel", (camera, event["channel"], f"Camera {event['channel']:02d}"))
        cursor.execute("""INSERT INTO camera_events (legacy_event_id,camera_code,channel,occurred_at,event_code,event_type,description,severity,audio_level_db,raw_metadata)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            ON CONFLICT (legacy_event_id) DO UPDATE SET camera_code=EXCLUDED.camera_code,channel=EXCLUDED.channel,occurred_at=EXCLUDED.occurred_at,event_code=EXCLUDED.event_code,event_type=EXCLUDED.event_type,description=EXCLUDED.description,severity=EXCLUDED.severity,audio_level_db=EXCLUDED.audio_level_db,raw_metadata=EXCLUDED.raw_metadata RETURNING id""",
            (event["id"], camera, event["channel"], parse_timestamp(event["timestamp"]), event["event_code"], event["event_type"], event["description"], event["severity"], event["audio_level_db"], Jsonb(parse_json(event["metadata_json"], {}))))
        pg_event_id = cursor.fetchone()[0]
        if event["clip_filename"]:
            cursor.execute("""INSERT INTO video_assets(event_id,camera_code,relative_path,duration_seconds) VALUES (%s,%s,%s,%s)
                ON CONFLICT(event_id) DO UPDATE SET camera_code=EXCLUDED.camera_code,relative_path=EXCLUDED.relative_path,duration_seconds=EXCLUDED.duration_seconds RETURNING id""", (pg_event_id,camera,event["clip_filename"],event["clip_duration_sec"]))
            asset_id = cursor.fetchone()[0]
            cursor.execute("""INSERT INTO video_replicas(video_asset_id,storage_backend,object_key,state,verified_at) VALUES (%s,%s,%s,'available',now())
                ON CONFLICT(video_asset_id,storage_backend) DO UPDATE SET object_key=EXCLUDED.object_key,state='available',verified_at=now(),last_error=NULL""", (asset_id,backend,event["clip_filename"]))
        if audio:
            a=dict(audio)
            cursor.execute("""INSERT INTO audio_analyses(event_id,status,transcript,segments,speech_detected,audio_rms,active_speech_seconds,ignored_reason,audio_model,suggestion,error_message,created_at,analyzed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(event_id) DO UPDATE SET status=EXCLUDED.status,transcript=EXCLUDED.transcript,segments=EXCLUDED.segments,speech_detected=EXCLUDED.speech_detected,audio_rms=EXCLUDED.audio_rms,active_speech_seconds=EXCLUDED.active_speech_seconds,ignored_reason=EXCLUDED.ignored_reason,audio_model=EXCLUDED.audio_model,suggestion=EXCLUDED.suggestion,error_message=EXCLUDED.error_message,analyzed_at=EXCLUDED.analyzed_at""",
                (pg_event_id,a["status"],a["transcript"],Jsonb(parse_json(a["segments_json"],[])),bool(a["speech_detected"]) if a["speech_detected"] is not None else None,a["audio_rms"],a["active_speech_seconds"],a["ignored_reason"],a["audio_model"],Jsonb(parse_json(a["suggestion_json"],None)),a["error_message"],parse_timestamp(a["created_at"]),parse_timestamp(a["analyzed_at"])))
        if video:
            v=dict(video)
            cursor.execute("""INSERT INTO video_analyses(event_id,status,summary,risk_level,detected_events,frames,video_model,error_message,created_at,analyzed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(event_id) DO UPDATE SET status=EXCLUDED.status,summary=EXCLUDED.summary,risk_level=EXCLUDED.risk_level,detected_events=EXCLUDED.detected_events,frames=EXCLUDED.frames,video_model=EXCLUDED.video_model,error_message=EXCLUDED.error_message,analyzed_at=EXCLUDED.analyzed_at""",
                (pg_event_id,v["status"],v["summary"],v["risk_level"],Jsonb(parse_json(v["events_json"],[])),Jsonb(parse_json(v["frames_json"],[])),v["video_model"],v["error_message"],parse_timestamp(v["created_at"]),parse_timestamp(v["analyzed_at"])))


def sync_pending(limit: int = 100, storage_backend: str = "nas_primary") -> dict[str, int]:
    if not enabled(): return {"synced": 0, "failed": 0, "disabled": 1}
    source = database.get_db_connection()
    rows = [dict(row) for row in source.execute("SELECT event_id, action FROM postgres_sync_outbox ORDER BY queued_at LIMIT ?", (limit,))]
    source.close()
    result={"synced":0,"failed":0,"disabled":0}
    for row in rows:
        try:
            with _connect() as target:
                if row["action"] == "delete":
                    with target.cursor() as cursor: cursor.execute("DELETE FROM camera_events WHERE legacy_event_id = %s", (row["event_id"],))
                else: _upsert_event(target, row["event_id"], storage_backend)
            source=database.get_db_connection(); source.execute("DELETE FROM postgres_sync_outbox WHERE event_id=? AND action=?",(row["event_id"],row["action"])); source.commit(); source.close(); result["synced"]+=1
        except Exception as exc:
            source=database.get_db_connection(); source.execute("UPDATE postgres_sync_outbox SET attempts=attempts+1,last_error=?,queued_at=? WHERE event_id=? AND action=?",(str(exc)[:1000],database.datetime.now().astimezone().isoformat(timespec="seconds"),row["event_id"],row["action"])); source.commit(); source.close(); result["failed"]+=1
    return result
