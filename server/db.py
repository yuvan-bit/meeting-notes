from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('phone', 'pc')),
    token_hash TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    revoked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS pairing_codes (
    id TEXT PRIMARY KEY,
    code_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('phone', 'pc')),
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pairing_codes_hash ON pairing_codes(code_hash);

CREATE TABLE IF NOT EXISTS recordings (
    id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL,
    title TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT 'auto',
    original_filename TEXT NOT NULL,
    client_upload_id TEXT,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    duration_s REAL,
    status TEXT NOT NULL DEFAULT 'uploading',
    audio_path TEXT,
    chunk_size INTEGER NOT NULL,
    total_chunks INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    uploaded_at TEXT,
    pinned INTEGER NOT NULL DEFAULT 0,
    audio_deleted_at TEXT,
    FOREIGN KEY (device_id) REFERENCES devices(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_recordings_client_upload
    ON recordings(device_id, client_upload_id);
CREATE INDEX IF NOT EXISTS idx_recordings_created ON recordings(created_at);
CREATE INDEX IF NOT EXISTS idx_recordings_status ON recordings(status);

CREATE TABLE IF NOT EXISTS recording_chunks (
    recording_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,
    path TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (recording_id, idx),
    FOREIGN KEY (recording_id) REFERENCES recordings(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    recording_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_expires_at TEXT,
    last_heartbeat_at TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT,
    FOREIGN KEY (recording_id) REFERENCES recordings(id)
);
CREATE INDEX IF NOT EXISTS idx_jobs_status_created ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_jobs_lease ON jobs(status, lease_expires_at);

CREATE TABLE IF NOT EXISTS notes (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE,
    content_type TEXT NOT NULL,
    topic TEXT NOT NULL,
    summary TEXT,
    dir_rel TEXT NOT NULL,
    files_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
CREATE INDEX IF NOT EXISTS idx_notes_created ON notes(created_at);

CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    job_id TEXT,
    type TEXT NOT NULL,
    message TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_job ON events(job_id, created_at);
"""


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=30000")
    return conn


def init_db(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.execute("PRAGMA user_version=1")
        conn.commit()
    finally:
        conn.close()
