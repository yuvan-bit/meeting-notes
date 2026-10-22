from __future__ import annotations

import sqlite3

from fastapi import HTTPException

from ..config import Settings


def get_recording(
    db: sqlite3.Connection,
    recording_id: str,
    device_id: str | None = None,
) -> sqlite3.Row:
    if device_id is None:
        row = db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
    else:
        row = db.execute(
            "SELECT * FROM recordings WHERE id=? AND device_id=?",
            (recording_id, device_id),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="录音不存在")
    return row


def get_job(db: sqlite3.Connection, recording_id: str) -> sqlite3.Row | None:
    return db.execute(
        "SELECT * FROM jobs WHERE recording_id=?",
        (recording_id,),
    ).fetchone()


def serialize_recording(row: sqlite3.Row, settings: Settings) -> dict:
    audio_path = row["audio_path"]
    audio_available = False
    if audio_path and not row["audio_deleted_at"]:
        audio_available = (settings.audio_dir / audio_path).is_file()

    keys = set(row.keys())
    job = None
    if "job_id" in keys and row["job_id"]:
        job = {
            "id": row["job_id"],
            "status": row["job_status"],
            "attempts": row["job_attempts"],
            "error": row["job_error"],
            "finished_at": row["job_finished_at"],
        }
    return {
        "id": row["id"],
        "title": row["title"],
        "content_type": row["content_type"],
        "status": row["status"],
        "size_bytes": row["size_bytes"],
        "duration_s": row["duration_s"],
        "created_at": row["created_at"],
        "uploaded_at": row["uploaded_at"],
        "pinned": bool(row["pinned"]),
        "audio_available": audio_available,
        "note_id": row["note_id"] if "note_id" in keys else None,
        "job": job,
    }
