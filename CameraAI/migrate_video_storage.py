"""Safely copy legacy flat clips into the canonical camera/date hierarchy.

Default mode is a dry run.  ``--apply`` copies (never moves) verified files and
only then updates the SQLite reference.  Original files remain untouched for
rollback and must be removed only after a separate retention decision.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime
from pathlib import Path

import config
import database
from clip_storage import build_clip_reference, legacy_clip_details, resolve_clip_path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def legacy_clip_rows():
    conn = database.get_db_connection()
    rows = conn.execute("SELECT id, channel, timestamp, clip_filename FROM events WHERE clip_filename IS NOT NULL AND clip_filename != ''").fetchall()
    conn.close()
    return {str(row["clip_filename"]): dict(row) for row in rows}


def migrate(apply: bool) -> tuple[Path, dict]:
    source_root = Path(config.CLIPS_DIR)
    event_by_reference = legacy_clip_rows()
    report_dir = Path(config.STORAGE_DIR) / "migrations"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"clip-migration-{datetime.now().strftime('%Y%m%dT%H%M%S')}.jsonl"
    summary = {"scanned": 0, "ready": 0, "copied": 0, "unlinked": 0, "errors": 0, "dry_run": not apply}

    # Legacy layout was flat.  Do not scan hierarchy folders or generated data.
    candidates = sorted(path for path in source_root.glob("*.mp4") if path.is_file())
    with report_path.open("w", encoding="utf-8") as report:
        for source in candidates:
            summary["scanned"] += 1
            legacy = legacy_clip_details(source.name)
            event = event_by_reference.get(source.name)
            item = {"source": source.name, "size_bytes": source.stat().st_size}
            if not legacy or not event:
                item.update({"status": "needs_review", "reason": "Tên file hoặc bản ghi event không khớp; không tự di chuyển."})
                summary["unlinked"] += 1
                report.write(json.dumps(item, ensure_ascii=False) + "\n")
                continue

            parsed_channel, parsed_time = legacy
            if parsed_channel != event["channel"]:
                item.update({"status": "needs_review", "reason": "Channel trong tên file khác event; không tự di chuyển."})
                summary["unlinked"] += 1
                report.write(json.dumps(item, ensure_ascii=False) + "\n")
                continue

            target_reference = build_clip_reference(event["channel"], parsed_time, event["id"])
            target = resolve_clip_path(target_reference)
            item.update({"event_id": event["id"], "target": target_reference, "status": "ready"})
            summary["ready"] += 1
            if apply:
                try:
                    source_hash = sha256(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    if target.exists() and sha256(target) != source_hash:
                        raise RuntimeError("Tệp đích đã tồn tại nhưng checksum khác")
                    if not target.exists():
                        shutil.copy2(source, target)
                    if sha256(target) != source_hash:
                        raise RuntimeError("Checksum sau copy không khớp")
                    if not database.replace_event_clip_reference(event["id"], source.name, target_reference):
                        raise RuntimeError("Bản ghi database đã thay đổi trong lúc di chuyển")
                    item.update({"status": "copied", "sha256": source_hash})
                    summary["copied"] += 1
                except (OSError, RuntimeError) as exc:
                    item.update({"status": "error", "error": str(exc)})
                    summary["errors"] += 1
            report.write(json.dumps(item, ensure_ascii=False) + "\n")
    return report_path, summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Copy legacy clips into the canonical hierarchy safely.")
    parser.add_argument("--apply", action="store_true", help="Copy verified files and update DB references. Never deletes sources.")
    arguments = parser.parse_args()
    report, result = migrate(apply=arguments.apply)
    print(json.dumps(result, ensure_ascii=False))
    print(f"Manifest: {report}")
