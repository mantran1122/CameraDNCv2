"""Generate a read-only reconciliation report for SQLite, PostgreSQL and NAS.

This command never changes either database or clip store.  It identifies exact
legacy event IDs that differ and SQLite clip references that cannot be opened
from the configured clip root.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import config
import database
from clip_storage import resolve_clip_path


def main() -> Path:
    conninfo = os.getenv("CAMERAAI_POSTGRES_URL", "").strip()
    if not conninfo:
        raise SystemExit("Thiếu CAMERAAI_POSTGRES_URL. Đây là lệnh chỉ đọc, không có dữ liệu bị đổi.")
    try:
        import psycopg
    except ImportError as exc:
        raise SystemExit("Thiếu psycopg. Chạy: python -m pip install -r CameraAI/requirements.txt") from exc

    source = database.get_db_connection()
    sqlite_events = {
        row["id"]: {"timestamp": row["timestamp"], "channel": row["channel"], "event_code": row["event_code"], "clip_reference": row["clip_filename"]}
        for row in source.execute("SELECT id,timestamp,channel,event_code,clip_filename FROM events")
    }
    source.close()
    with psycopg.connect(conninfo, connect_timeout=5) as target:
        with target.cursor() as cursor:
            cursor.execute("SELECT legacy_event_id, occurred_at, camera_code, event_code FROM camera_events WHERE legacy_event_id IS NOT NULL")
            postgres_events = {
                row[0]: {"occurred_at": row[1].isoformat(), "camera_code": row[2], "event_code": row[3]}
                for row in cursor.fetchall()
            }

    sqlite_ids, postgres_ids = set(sqlite_events), set(postgres_events)
    postgres_only = sorted(postgres_ids - sqlite_ids)
    sqlite_only = sorted(sqlite_ids - postgres_ids)
    missing_clips = []
    for event_id, event in sqlite_events.items():
        reference = event["clip_reference"]
        if not reference:
            continue
        try:
            exists = resolve_clip_path(reference).is_file()
        except ValueError:
            exists = False
        if not exists:
            missing_clips.append({"legacy_event_id": event_id, **event})

    report = {
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "mode": "report_only",
        "clip_root": str(config.CLIPS_DIR),
        "summary": {"sqlite_events": len(sqlite_ids), "postgres_events": len(postgres_ids), "postgres_only_events": len(postgres_only), "sqlite_only_events": len(sqlite_only), "missing_clip_references": len(missing_clips)},
        "postgres_only_events": [{"legacy_event_id": event_id, **postgres_events[event_id]} for event_id in postgres_only],
        "sqlite_only_events": [{"legacy_event_id": event_id, **sqlite_events[event_id]} for event_id in sqlite_only],
        "missing_clip_references": missing_clips,
    }
    report_dir = Path(config.STORAGE_DIR) / "reconciliation"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"data-reconciliation-{datetime.now().strftime('%Y%m%dT%H%M%S')}.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False))
    print(f"Report: {report_path}")
    return report_path


if __name__ == "__main__":
    main()
