import sqlite3
import json
from datetime import datetime, date, timedelta
from typing import List, Dict, Any, Optional
from config import STORAGE_DIR

DB_PATH = STORAGE_DIR / "camera_metadata.db"


def get_database_overview(sample_limit: int = 20) -> Dict[str, Any]:
    """Return a read-only, admin-safe view of the SQLite database.

    This deliberately exposes no arbitrary SQL execution endpoint.  Table names
    are obtained from SQLite itself and quoted before use.
    """
    safe_limit = max(1, min(int(sample_limit), 100))
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )
    table_names = [row["name"] for row in cursor.fetchall()]

    tables = []
    for table_name in table_names:
        quoted_name = '"' + table_name.replace('"', '""') + '"'
        cursor.execute(f"PRAGMA table_info({quoted_name})")
        columns = [
            {
                "name": row["name"],
                "type": row["type"],
                "required": bool(row["notnull"]),
                "primary_key": bool(row["pk"]),
            }
            for row in cursor.fetchall()
        ]
        cursor.execute(f"SELECT COUNT(*) AS total FROM {quoted_name}")
        row_count = cursor.fetchone()["total"]
        cursor.execute(f"SELECT * FROM {quoted_name} ORDER BY rowid DESC LIMIT ?", (safe_limit,))
        rows = [dict(row) for row in cursor.fetchall()]
        tables.append({"name": table_name, "row_count": row_count, "columns": columns, "rows": rows})

    conn.close()
    return {
        "engine": "SQLite",
        "database_file": DB_PATH.name,
        "database_size_bytes": DB_PATH.stat().st_size if DB_PATH.exists() else 0,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "sample_limit": safe_limit,
        "tables": tables,
    }

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Table for raw and processed events
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        event_code TEXT NOT NULL,
        event_type TEXT NOT NULL, -- 'audio_anomaly', 'video_anomaly', 'normal_metadata'
        channel INTEGER NOT NULL,
        timestamp TEXT NOT NULL,
        description TEXT NOT NULL,
        severity TEXT NOT NULL, -- 'high', 'medium', 'info'
        audio_level_db REAL,
        metadata_json TEXT,
        clip_filename TEXT,
        clip_duration_sec INTEGER DEFAULT 10
    );
    """)

    # Table for aggregated daily summary
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS daily_summaries (
        date_str TEXT PRIMARY KEY,
        total_events INTEGER DEFAULT 0,
        anomaly_video_count INTEGER DEFAULT 0,
        anomaly_audio_count INTEGER DEFAULT 0,
        total_human_count INTEGER DEFAULT 0,
        total_vehicle_count INTEGER DEFAULT 0,
        peak_hour INTEGER DEFAULT 12,
        summary_text TEXT
    );
    """)

    # Derived audio results are kept separate from immutable NVR event metadata.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS audio_analyses (
        event_id INTEGER PRIMARY KEY,
        status TEXT NOT NULL,
        wav_path TEXT,
        transcript TEXT,
        segments_json TEXT,
        speech_detected INTEGER,
        audio_rms REAL,
        active_speech_seconds REAL,
        ignored_reason TEXT,
        audio_model TEXT,
        suggestion_json TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL,
        analyzed_at TEXT,
        FOREIGN KEY(event_id) REFERENCES events(id)
    );
    """)

    # Manual, derived video analysis is separate from immutable NVR metadata.
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS video_analyses (
        event_id INTEGER PRIMARY KEY,
        status TEXT NOT NULL,
        summary TEXT,
        risk_level TEXT,
        events_json TEXT,
        frames_json TEXT,
        video_model TEXT,
        error_message TEXT,
        created_at TEXT NOT NULL,
        analyzed_at TEXT,
        FOREIGN KEY(event_id) REFERENCES events(id)
    );
    """)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS postgres_sync_outbox (
        event_id INTEGER NOT NULL,
        action TEXT NOT NULL DEFAULT 'upsert',
        queued_at TEXT NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0,
        last_error TEXT,
        PRIMARY KEY (event_id, action)
    );
    """)

    # Repair legacy rows that were marked completed even though neither STT nor
    # an AI conclusion was produced.
    cursor.execute("""
        UPDATE audio_analyses
        SET status = 'no_speech_detected', ignored_reason = COALESCE(ignored_reason, 'empty_transcript')
        WHERE status = 'completed'
          AND (transcript IS NULL OR TRIM(transcript) = '')
          AND (suggestion_json IS NULL OR TRIM(suggestion_json) = '')
    """)
    
    conn.commit()
    conn.close()

def queue_postgres_sync(event_id: int, action: str = "upsert") -> None:
    conn = get_db_connection()
    conn.execute("INSERT INTO postgres_sync_outbox(event_id,action,queued_at,attempts,last_error) VALUES(?,?,?,?,NULL) ON CONFLICT(event_id,action) DO UPDATE SET queued_at=excluded.queued_at", (event_id, action, datetime.now().astimezone().isoformat(timespec="seconds"), 0))
    conn.commit(); conn.close()

def sync_postgres_outbox(limit: int = 100) -> Dict[str, int]:
    try:
        from postgres_sync import sync_pending
        return sync_pending(limit=limit)
    except Exception as exc:
        print(f"[PostgreSQL Sync] {exc}")
        return {"synced": 0, "failed": 1, "disabled": 0}

def _queue_and_sync(event_id: int, action: str = "upsert") -> None:
    queue_postgres_sync(event_id, action)
    sync_postgres_outbox(limit=25)

def save_event(
    event_code: str,
    event_type: str,
    channel: int,
    timestamp: str,
    description: str,
    severity: str = "medium",
    audio_level_db: Optional[float] = None,
    metadata_dict: Optional[Dict[str, Any]] = None,
    clip_filename: Optional[str] = None,
    clip_duration_sec: int = 10
) -> int:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    meta_json = json.dumps(metadata_dict or {}, ensure_ascii=False)
    cursor.execute("""
        INSERT INTO events (
            event_code, event_type, channel, timestamp, description, severity, audio_level_db, metadata_json, clip_filename, clip_duration_sec
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (event_code, event_type, channel, timestamp, description, severity, audio_level_db, meta_json, clip_filename, clip_duration_sec))
    
    event_id = cursor.lastrowid
    conn.commit()
    conn.close()
    _queue_and_sync(event_id)
    return event_id

def get_events(
    event_type: Optional[str] = None,
    channel: Optional[int] = None,
    limit: int = 50,
    only_anomalies: bool = False
) -> List[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = "SELECT * FROM events WHERE 1=1"
    params = []
    
    if only_anomalies:
        query += " AND event_type IN ('audio_anomaly', 'video_anomaly')"
    elif event_type:
        query += " AND event_type = ?"
        params.append(event_type)
        
    if channel:
        query += " AND channel = ?"
        params.append(channel)
        
    query += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for r in rows:
        item = dict(r)
        if item["metadata_json"]:
            try:
                item["metadata"] = json.loads(item["metadata_json"])
            except Exception:
                item["metadata"] = {}
        else:
            item["metadata"] = {}
        del item["metadata_json"]
        result.append(item)
    return result

def get_event_by_id(event_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM events WHERE id = ?", (event_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None
    item = dict(row)
    if item["metadata_json"]:
        try:
            item["metadata"] = json.loads(item["metadata_json"])
        except Exception:
            item["metadata"] = {}
    del item["metadata_json"]
    return item

def update_event_clip(event_id: int, clip_filename: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE events SET clip_filename = ? WHERE id = ?", (clip_filename, event_id))
    conn.commit()
    conn.close()
    _queue_and_sync(event_id)


def replace_event_clip_reference(event_id: int, old_reference: str, new_reference: str) -> bool:
    """Atomically change a legacy clip reference after its copied file is verified."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE events SET clip_filename = ? WHERE id = ? AND clip_filename = ?",
        (new_reference, event_id, old_reference),
    )
    updated = cursor.rowcount == 1
    conn.commit()
    conn.close()
    if updated:
        _queue_and_sync(event_id)
    return updated


def delete_expired_events(retention_days: int) -> List[str]:
    """Delete expired metadata and return the associated clip filenames."""
    cutoff = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, clip_filename FROM events WHERE timestamp < ?", (cutoff,))
    expired = cursor.fetchall()
    event_ids = [row["id"] for row in expired]
    filenames = [row["clip_filename"] for row in expired if row["clip_filename"]]
    if event_ids:
        placeholders = ",".join("?" for _ in event_ids)
        cursor.execute(f"DELETE FROM audio_analyses WHERE event_id IN ({placeholders})", event_ids)
        cursor.execute(f"DELETE FROM video_analyses WHERE event_id IN ({placeholders})", event_ids)
        cursor.execute(f"DELETE FROM events WHERE id IN ({placeholders})", event_ids)
    conn.commit()
    conn.close()
    for event_id in event_ids:
        _queue_and_sync(event_id, action="delete")
    return filenames


def create_audio_analysis(event_id: int, status: str = "not_analyzed") -> bool:
    """Create the single pending audio-analysis record for an event.

    Repeated calls are safe: an existing result is never overwritten.
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR IGNORE INTO audio_analyses (event_id, status, created_at)
        VALUES (?, ?, ?)
        """,
        (event_id, status, datetime.now().astimezone().isoformat(timespec="seconds")),
    )
    created = cursor.rowcount == 1
    conn.commit()
    conn.close()
    if created:
        _queue_and_sync(event_id)
    return created


def update_audio_analysis(event_id: int, **values: Any) -> bool:
    """Update permitted derived-audio fields for an existing event analysis."""
    if "segments" in values:
        values["segments_json"] = json.dumps(values.pop("segments"), ensure_ascii=False)
    if "suggestion" in values:
        values["suggestion_json"] = json.dumps(values.pop("suggestion"), ensure_ascii=False)

    allowed_fields = {
        "status", "wav_path", "transcript", "segments_json", "speech_detected",
        "audio_rms", "active_speech_seconds", "ignored_reason", "audio_model",
        "suggestion_json", "error_message", "analyzed_at",
    }
    unexpected_fields = set(values) - allowed_fields
    if unexpected_fields:
        raise ValueError(f"Unsupported audio analysis fields: {sorted(unexpected_fields)}")
    if not values:
        return False

    assignments = ", ".join(f"{field} = ?" for field in values)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE audio_analyses SET {assignments} WHERE event_id = ?",
        [*values.values(), event_id],
    )
    updated = cursor.rowcount == 1
    conn.commit()
    conn.close()
    if updated:
        _queue_and_sync(event_id)
    return updated


def get_audio_analysis(event_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM audio_analyses WHERE event_id = ?", (event_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None

    item = dict(row)
    for database_key, api_key in (("segments_json", "segments"), ("suggestion_json", "suggestion")):
        raw_value = item.pop(database_key)
        if raw_value is None:
            item[api_key] = None
            continue
        try:
            item[api_key] = json.loads(raw_value)
        except json.JSONDecodeError:
            item[api_key] = None
    return item


def get_unanalyzed_audio_event_ids(limit: int = 50) -> List[int]:
    """Return stored audio alarms that have a replay clip but no analysis yet."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT e.id
        FROM events e
        LEFT JOIN audio_analyses a ON a.event_id = e.id
        WHERE e.event_type = 'audio_anomaly'
          AND e.clip_filename IS NOT NULL
          AND e.clip_filename != ''
          AND a.event_id IS NULL
        ORDER BY e.id ASC
        LIMIT ?
        """,
        (limit,),
    )
    ids = [row[0] for row in cursor.fetchall()]
    conn.close()
    return ids


def create_video_analysis(event_id: int, status: str = "not_analyzed") -> bool:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        """
        INSERT OR IGNORE INTO video_analyses (event_id, status, created_at)
        VALUES (?, ?, ?)
        """,
        (event_id, status, datetime.now().astimezone().isoformat(timespec="seconds")),
    )
    created = cursor.rowcount == 1
    conn.commit()
    conn.close()
    if created:
        _queue_and_sync(event_id)
    return created


def update_video_analysis(event_id: int, **values: Any) -> bool:
    if "events" in values:
        values["events_json"] = json.dumps(values.pop("events"), ensure_ascii=False)
    if "frames" in values:
        values["frames_json"] = json.dumps(values.pop("frames"), ensure_ascii=False)

    allowed_fields = {
        "status", "summary", "risk_level", "events_json", "frames_json",
        "video_model", "error_message", "analyzed_at",
    }
    unexpected_fields = set(values) - allowed_fields
    if unexpected_fields:
        raise ValueError(f"Unsupported video analysis fields: {sorted(unexpected_fields)}")
    if not values:
        return False

    assignments = ", ".join(f"{field} = ?" for field in values)
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        f"UPDATE video_analyses SET {assignments} WHERE event_id = ?",
        [*values.values(), event_id],
    )
    updated = cursor.rowcount == 1
    conn.commit()
    conn.close()
    if updated:
        _queue_and_sync(event_id)
    return updated


def get_video_analysis(event_id: int) -> Optional[Dict[str, Any]]:
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM video_analyses WHERE event_id = ?", (event_id,))
    row = cursor.fetchone()
    conn.close()
    if not row:
        return None

    item = dict(row)
    for database_key, api_key in (("events_json", "events"), ("frames_json", "frames")):
        raw_value = item.pop(database_key)
        if raw_value is None:
            item[api_key] = []
            continue
        try:
            item[api_key] = json.loads(raw_value)
        except json.JSONDecodeError:
            item[api_key] = []
    return item

# Initialize DB on module import
init_db()
