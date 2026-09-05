-- PostgreSQL metadata store for CameraAI. Video bytes stay on NAS/object storage.
-- Apply through migrate_sqlite_to_postgres.py; this file is idempotent.

CREATE TABLE IF NOT EXISTS cameras (
    code TEXT PRIMARY KEY,
    channel INTEGER NOT NULL UNIQUE CHECK (channel > 0),
    name TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS storage_policies (
    name TEXT PRIMARY KEY,
    primary_backend TEXT NOT NULL,
    retention_days INTEGER NOT NULL CHECK (retention_days > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS camera_events (
    id BIGSERIAL PRIMARY KEY,
    legacy_event_id BIGINT UNIQUE,
    camera_code TEXT NOT NULL REFERENCES cameras(code),
    channel INTEGER NOT NULL CHECK (channel > 0),
    occurred_at TIMESTAMPTZ NOT NULL,
    event_code TEXT NOT NULL,
    event_type TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL,
    audio_level_db DOUBLE PRECISION,
    raw_metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT event_camera_channel_matches CHECK (camera_code = 'cam-' || lpad(channel::text, 3, '0'))
);
CREATE INDEX IF NOT EXISTS ix_camera_events_camera_time ON camera_events (camera_code, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_camera_events_type_time ON camera_events (event_type, occurred_at DESC);

CREATE TABLE IF NOT EXISTS video_assets (
    id BIGSERIAL PRIMARY KEY,
    event_id BIGINT NOT NULL UNIQUE REFERENCES camera_events(id) ON DELETE CASCADE,
    camera_code TEXT NOT NULL REFERENCES cameras(code),
    -- Legacy SQLite can legitimately link the same captured clip to more than
    -- one event.  Asset ownership is unique per event, not per path.
    relative_path TEXT NOT NULL,
    duration_seconds INTEGER,
    state TEXT NOT NULL DEFAULT 'available',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK (relative_path !~ '(^/|\\\\|(^|/)\.\.(/|$))')
);
CREATE INDEX IF NOT EXISTS ix_video_assets_camera_path ON video_assets (camera_code, relative_path);

-- Compatibility for a schema initialized by an earlier migration build.
ALTER TABLE video_assets DROP CONSTRAINT IF EXISTS video_assets_relative_path_key;

CREATE TABLE IF NOT EXISTS video_replicas (
    id BIGSERIAL PRIMARY KEY,
    video_asset_id BIGINT NOT NULL REFERENCES video_assets(id) ON DELETE CASCADE,
    storage_backend TEXT NOT NULL,
    object_key TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'available',
    verified_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (video_asset_id, storage_backend)
);

CREATE TABLE IF NOT EXISTS audio_analyses (
    event_id BIGINT PRIMARY KEY REFERENCES camera_events(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    transcript TEXT,
    segments JSONB,
    speech_detected BOOLEAN,
    audio_rms DOUBLE PRECISION,
    active_speech_seconds DOUBLE PRECISION,
    ignored_reason TEXT,
    audio_model TEXT,
    suggestion JSONB,
    error_message TEXT,
    created_at TIMESTAMPTZ,
    analyzed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS video_analyses (
    event_id BIGINT PRIMARY KEY REFERENCES camera_events(id) ON DELETE CASCADE,
    status TEXT NOT NULL,
    summary TEXT,
    risk_level TEXT,
    detected_events JSONB,
    frames JSONB,
    video_model TEXT,
    error_message TEXT,
    created_at TIMESTAMPTZ,
    analyzed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id BIGSERIAL PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
