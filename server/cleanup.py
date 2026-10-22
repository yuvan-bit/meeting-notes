from __future__ import annotations

import shutil
import sqlite3
import time
from datetime import timedelta
from pathlib import Path

from .config import Settings
from .db import connect
from .storage import remove_tree
from .utils import iso, utcnow


def _delete_audio(
    conn: sqlite3.Connection,
    settings: Settings,
    row: sqlite3.Row,
    now_iso: str,
) -> int:
    path = settings.audio_dir / row["audio_path"]
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    with conn:
        conn.execute(
            "UPDATE recordings SET audio_deleted_at=? WHERE id=?",
            (now_iso, row["id"]),
        )
    return int(row["size_bytes"])


def cleanup(settings: Settings, conn: sqlite3.Connection | None = None) -> dict:
    own_connection = conn is None
    if conn is None:
        conn = connect(settings.db_path)
    now = utcnow()
    now_iso = iso(now)
    stats: dict = {
        "pairing_codes_deleted": 0,
        "stale_uploads_deleted": 0,
        "jobs_requeued": 0,
        "jobs_failed": 0,
        "temp_removed": 0,
        "audio_deleted": 0,
        "audio_freed_bytes": 0,
        "audio_bytes_remaining": 0,
        "warnings": [],
    }

    try:
        with conn:
            stats["pairing_codes_deleted"] = conn.execute(
                "DELETE FROM pairing_codes WHERE expires_at < ? "
                "OR (used_at IS NOT NULL AND used_at < ?)",
                (now_iso, iso(now - timedelta(days=7))),
            ).rowcount

        with conn:
            requeued = conn.execute(
                "UPDATE jobs SET status='queued', lease_owner=NULL, lease_expires_at=NULL "
                "WHERE status='leased' AND lease_expires_at < ? AND attempts < ?",
                (now_iso, settings.max_attempts),
            ).rowcount
            stats["jobs_requeued"] = requeued
            failed = conn.execute(
                "UPDATE jobs SET status='failed', lease_owner=NULL, lease_expires_at=NULL, "
                "finished_at=? WHERE status='leased' AND lease_expires_at < ? AND attempts >= ?",
                (now_iso, now_iso, settings.max_attempts),
            ).rowcount
            stats["jobs_failed"] = failed
            if failed:
                conn.execute(
                    "UPDATE recordings SET status='failed' WHERE id IN ("
                    "SELECT recording_id FROM jobs WHERE status='failed' AND finished_at=?)",
                    (now_iso,),
                )

        upload_cutoff = iso(now - timedelta(days=7))
        stale = conn.execute(
            "SELECT id FROM recordings WHERE status='uploading' AND created_at < ?",
            (upload_cutoff,),
        ).fetchall()
        for row in stale:
            remove_tree(settings.tmp_dir / row["id"])
            with conn:
                conn.execute("DELETE FROM recordings WHERE id=?", (row["id"],))
            stats["stale_uploads_deleted"] += 1

        temp_cutoff = time.time() - 48 * 3600
        for path in settings.tmp_dir.iterdir():
            try:
                if path.stat().st_mtime >= temp_cutoff:
                    continue
            except OSError:
                continue
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
            stats["temp_removed"] += 1

        rows = conn.execute(
            "SELECT r.id, r.audio_path, r.size_bytes, r.pinned, r.created_at, "
            "r.uploaded_at, r.status, j.status AS job_status "
            "FROM recordings r LEFT JOIN jobs j ON j.recording_id=r.id "
            "WHERE r.audio_path IS NOT NULL AND r.audio_deleted_at IS NULL "
            "ORDER BY r.created_at ASC"
        ).fetchall()
        total = sum(int(row["size_bytes"]) for row in rows)
        retention_cutoff = iso(now - timedelta(days=settings.audio_retention_days))
        deletable = [
            row
            for row in rows
            if not row["pinned"] and row["job_status"] in {"done", "failed"}
        ]

        deleted_ids: set[str] = set()
        for row in deletable:
            when = row["uploaded_at"] or row["created_at"]
            if when < retention_cutoff:
                total -= _delete_audio(conn, settings, row, now_iso)
                deleted_ids.add(row["id"])
                stats["audio_deleted"] += 1

        for row in deletable:
            if total <= settings.audio_max_bytes:
                break
            if row["id"] in deleted_ids:
                continue
            total -= _delete_audio(conn, settings, row, now_iso)
            deleted_ids.add(row["id"])
            stats["audio_deleted"] += 1

        stats["audio_freed_bytes"] = sum(
            int(row["size_bytes"]) for row in deletable if row["id"] in deleted_ids
        )
        stats["audio_bytes_remaining"] = max(total, 0)
        if total > settings.audio_max_bytes:
            stats["warnings"].append(
                "置顶或未完成任务占用了音频配额，暂时无法压到上限以下"
            )
        return stats
    finally:
        if own_connection:
            conn.close()
