from __future__ import annotations

import shutil
import sqlite3

from fastapi import APIRouter, Depends

from ..config import Settings
from ..deps import get_db, get_settings

router = APIRouter(tags=["health"])


@router.get("/health")
def health(
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    db.execute("SELECT 1").fetchone()
    queued = db.execute("SELECT COUNT(*) AS n FROM jobs WHERE status='queued'").fetchone()["n"]
    leased = db.execute("SELECT COUNT(*) AS n FROM jobs WHERE status='leased'").fetchone()["n"]
    notes = db.execute("SELECT COUNT(*) AS n FROM notes").fetchone()["n"]
    audio_bytes = db.execute(
        "SELECT COALESCE(SUM(size_bytes), 0) AS n FROM recordings "
        "WHERE audio_path IS NOT NULL AND audio_deleted_at IS NULL"
    ).fetchone()["n"]
    free = shutil.disk_usage(settings.data_dir).free
    return {
        "ok": True,
        "version": settings.version,
        "db": "ok",
        "queue": {"queued": queued, "leased": leased},
        "notes": notes,
        "audio_bytes": audio_bytes,
        "disk_free_bytes": free,
    }
