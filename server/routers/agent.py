from __future__ import annotations

import json
import mimetypes
import shutil
import sqlite3
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile

from ..config import Settings
from ..deps import get_db, get_settings, require_pc
from ..schemas import FailRequest
from ..storage import (
    RESULT_FILE_NAMES,
    extract_summary,
    extract_topic,
    notes_rel_dir,
)
from ..utils import iso, new_id, parse_iso, utcnow
from .common import get_recording

router = APIRouter(prefix="/agent", tags=["agent"])


def _reap_expired(db: sqlite3.Connection, settings: Settings, now: str) -> None:
    db.execute(
        "UPDATE jobs SET status='queued', lease_owner=NULL, lease_expires_at=NULL "
        "WHERE status='leased' AND lease_expires_at < ? AND attempts < ?",
        (now, settings.max_attempts),
    )
    db.execute(
        "UPDATE jobs SET status='failed', lease_owner=NULL, lease_expires_at=NULL, "
        "finished_at=? WHERE status='leased' AND lease_expires_at < ? AND attempts >= ?",
        (now, now, settings.max_attempts),
    )
    db.execute(
        "UPDATE recordings SET status='failed' WHERE id IN ("
        "SELECT recording_id FROM jobs WHERE status='failed' AND finished_at=?)",
        (now,),
    )


@router.get("/jobs/next")
def next_job(
    device: dict = Depends(require_pc),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    now = iso()
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(
            "UPDATE jobs SET status='queued', lease_owner=NULL, lease_expires_at=NULL "
            "WHERE status='leased' AND lease_expires_at < ? AND attempts < ?",
            (now, settings.max_attempts),
        )
        db.execute(
            "UPDATE jobs SET status='failed', lease_owner=NULL, lease_expires_at=NULL, "
            "finished_at=? WHERE status='leased' AND lease_expires_at < ? AND attempts >= ?",
            (now, now, settings.max_attempts),
        )
        db.execute(
            "UPDATE recordings SET status='failed' WHERE id IN ("
            "SELECT recording_id FROM jobs WHERE status='failed' AND finished_at=?)",
            (now,),
        )
        row = db.execute(
            "SELECT j.id AS job_id, j.attempts AS job_attempts, j.created_at AS job_created_at, "
            "r.* FROM jobs j JOIN recordings r ON r.id=j.recording_id "
            "WHERE j.status='queued' AND j.attempts < ? "
            "ORDER BY j.created_at LIMIT 1",
            (settings.max_attempts,),
        ).fetchone()
        if row is None:
            db.commit()
            return Response(status_code=204)

        lease_expires = iso(utcnow() + timedelta(seconds=settings.lease_seconds))
        updated = db.execute(
            "UPDATE jobs SET status='leased', lease_owner=?, lease_expires_at=?, "
            "last_heartbeat_at=?, started_at=COALESCE(started_at, ?), attempts=attempts+1, error=NULL "
            "WHERE id=? AND status='queued' AND attempts < ?",
            (
                device["id"],
                lease_expires,
                now,
                now,
                row["job_id"],
                settings.max_attempts,
            ),
        )
        if updated.rowcount != 1:
            db.rollback()
            return Response(status_code=204)
        db.execute("UPDATE recordings SET status='processing' WHERE id=?", (row["id"],))
        db.execute(
            "INSERT INTO events(id, job_id, type, message, created_at) "
            "VALUES (?, ?, 'leased', ?, ?)",
            (new_id("evt"), row["job_id"], f"领取任务：{device['name']}", now),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    attempts = row["job_attempts"] + 1
    return {
        "job_id": row["job_id"],
        "recording_id": row["id"],
        "attempts": attempts,
        "lease_seconds": settings.lease_seconds,
        "lease_expires_at": lease_expires,
        "recording": {
            "title": row["title"],
            "content_type": row["content_type"],
            "original_filename": row["original_filename"],
            "size_bytes": row["size_bytes"],
            "sha256": row["sha256"],
            "duration_s": row["duration_s"],
            "audio_url": f"/api/v1/agent/recordings/{row['id']}/audio",
        },
    }


@router.get("/jobs/queued")
def queued_jobs(
    limit: int = Query(default=3, ge=1, le=10),
    device: dict = Depends(require_pc),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    now = iso()
    with db:
        _reap_expired(db, settings, now)
    rows = db.execute(
        "SELECT j.id AS job_id, j.attempts AS job_attempts, j.created_at AS job_created_at, "
        "r.* FROM jobs j JOIN recordings r ON r.id=j.recording_id "
        "WHERE j.status='queued' AND j.attempts < ? "
        "ORDER BY j.created_at LIMIT ?",
        (settings.max_attempts, limit),
    ).fetchall()
    return {
        "items": [
            {
                "job_id": row["job_id"],
                "recording_id": row["id"],
                "attempts": row["job_attempts"],
                "created_at": row["job_created_at"],
                "recording": {
                    "title": row["title"],
                    "content_type": row["content_type"],
                    "original_filename": row["original_filename"],
                    "size_bytes": row["size_bytes"],
                    "sha256": row["sha256"],
                    "duration_s": row["duration_s"],
                    "audio_url": f"/api/v1/agent/recordings/{row['id']}/audio",
                },
            }
            for row in rows
        ]
    }


@router.post("/jobs/{job_id}/heartbeat")
def heartbeat(
    job_id: str,
    device: dict = Depends(require_pc),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    now = iso()
    expires = iso(utcnow() + timedelta(seconds=settings.lease_seconds))
    with db:
        changed = db.execute(
            "UPDATE jobs SET lease_expires_at=?, last_heartbeat_at=? "
            "WHERE id=? AND status='leased' AND lease_owner=? AND lease_expires_at > ?",
            (expires, now, job_id, device["id"], now),
        )
    if changed.rowcount != 1:
        raise HTTPException(status_code=409, detail="任务租约已失效")
    return {"job_id": job_id, "lease_expires_at": expires}


@router.get("/recordings/{recording_id}/audio")
def agent_download_audio(
    recording_id: str,
    device: dict = Depends(require_pc),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    row = db.execute("SELECT * FROM recordings WHERE id=?", (recording_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="录音不存在")
    if not row["audio_path"] or row["audio_deleted_at"]:
        raise HTTPException(status_code=410, detail="音频已按保留策略清理")
    path = settings.audio_dir / row["audio_path"]
    if not path.is_file():
        raise HTTPException(status_code=410, detail="音频文件不存在")
    filename = Path(row["original_filename"]).name or f"{recording_id}.m4a"
    media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    return FileResponse(path, filename=filename, media_type=media_type)


@router.post("/jobs/{job_id}/result")
async def upload_result(
    job_id: str,
    request: Request,
    device: dict = Depends(require_pc),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    recording = db.execute(
        "SELECT * FROM recordings WHERE id=?", (job["recording_id"],)
    ).fetchone()

    if job["status"] == "done":
        note = db.execute("SELECT * FROM notes WHERE job_id=?", (job_id,)).fetchone()
        if note is not None:
            return {
                "job_id": job_id,
                "note_id": note["id"],
                "recording_id": job["recording_id"],
                "status": "done",
                "duplicate": True,
            }

    leased_by_device = (
        job["status"] == "leased" and job["lease_owner"] == device["id"]
    )
    queued = job["status"] == "queued" and job["lease_owner"] is None
    if not (leased_by_device or queued):
        raise HTTPException(status_code=409, detail="任务租约不属于当前设备")
    if (
        leased_by_device
        and job["lease_expires_at"]
        and parse_iso(job["lease_expires_at"]) <= utcnow()
    ):
        raise HTTPException(status_code=409, detail="任务租约已过期")

    form = await request.form()
    uploads = form.getlist("files")
    if not uploads:
        raise HTTPException(status_code=400, detail="没有结果文件")

    temp_dir = settings.tmp_dir / new_id("result")
    temp_dir.mkdir(parents=True, exist_ok=False)
    total = 0
    seen: set[str] = set()
    try:
        for item in uploads:
            if not isinstance(item, UploadFile):
                raise HTTPException(status_code=400, detail="结果字段必须是文件")
            name = Path(item.filename or "").name
            if name not in RESULT_FILE_NAMES:
                raise HTTPException(status_code=400, detail=f"不允许的结果文件：{name}")
            if name in seen:
                raise HTTPException(status_code=400, detail=f"重复的结果文件：{name}")
            seen.add(name)
            target = temp_dir / name
            size = 0
            with target.open("wb") as handle:
                while True:
                    block = await item.read(1024 * 1024)
                    if not block:
                        break
                    size += len(block)
                    total += len(block)
                    if size > settings.max_result_file_bytes:
                        raise HTTPException(status_code=413, detail=f"{name} 超过单文件上限")
                    if total > settings.max_result_total_bytes:
                        raise HTTPException(status_code=413, detail="结果文件总大小超限")
                    handle.write(block)
            await item.close()
            if size == 0:
                raise HTTPException(status_code=400, detail=f"{name} 为空")

        minutes_path = temp_dir / "minutes.md"
        if not minutes_path.is_file():
            raise HTTPException(status_code=400, detail="缺少 minutes.md")

        meta = {}
        meta_path = temp_dir / "meta.json"
        if meta_path.is_file():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise HTTPException(status_code=400, detail="meta.json 不是有效 JSON") from exc
            if not isinstance(meta, dict):
                raise HTTPException(status_code=400, detail="meta.json 必须是对象")

        minutes = minutes_path.read_text(encoding="utf-8")
        content_type = meta.get("content_type") or meta.get("type") or recording["content_type"]
        if content_type not in {"meeting", "course"}:
            content_type = "meeting"
        topic = str(meta.get("topic") or "").strip() or extract_topic(
            minutes, recording["title"]
        )
        summary = str(meta.get("summary") or "").strip() or extract_summary(minutes)

        now = utcnow()
        rel_dir = notes_rel_dir(now, job_id)
        final_dir = settings.notes_dir / rel_dir
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        if final_dir.exists():
            shutil.rmtree(final_dir, ignore_errors=True)
        shutil.move(str(temp_dir), str(final_dir))

        files = []
        for path in sorted(final_dir.iterdir()):
            if path.is_file() and path.name in RESULT_FILE_NAMES:
                files.append({"name": path.name, "size_bytes": path.stat().st_size})

        note_id = new_id("note")
        with db:
            db.execute(
                "UPDATE jobs SET status='done', finished_at=?, lease_owner=NULL, "
                "lease_expires_at=NULL, error=NULL WHERE id=?",
                (iso(now), job_id),
            )
            db.execute(
                "UPDATE recordings SET status='done' WHERE id=?",
                (job["recording_id"],),
            )
            db.execute(
                "INSERT INTO notes(id, job_id, content_type, topic, summary, dir_rel, "
                "files_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET content_type=excluded.content_type, "
                "topic=excluded.topic, summary=excluded.summary, dir_rel=excluded.dir_rel, "
                "files_json=excluded.files_json, updated_at=excluded.updated_at",
                (
                    note_id,
                    job_id,
                    content_type,
                    topic,
                    summary[:500],
                    rel_dir.as_posix(),
                    json.dumps(files, ensure_ascii=False),
                    iso(now),
                    iso(now),
                ),
            )
            db.execute(
                "INSERT INTO events(id, job_id, type, message, created_at) "
                "VALUES (?, ?, 'done', ?, ?)",
                (new_id("evt"), job_id, "笔记回传完成", iso(now)),
            )
        return {
            "job_id": job_id,
            "note_id": note_id,
            "recording_id": job["recording_id"],
            "status": "done",
            "duplicate": False,
        }
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)


@router.post("/jobs/{job_id}/fail")
def fail_job(
    job_id: str,
    payload: FailRequest,
    device: dict = Depends(require_pc),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    job = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if job is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    if job["status"] == "done":
        return {"job_id": job_id, "status": "done"}
    if job["status"] != "leased" or job["lease_owner"] != device["id"]:
        raise HTTPException(status_code=409, detail="任务租约不属于当前设备")
    if job["lease_expires_at"] and parse_iso(job["lease_expires_at"]) <= utcnow():
        raise HTTPException(status_code=409, detail="任务租约已过期")

    now = iso()
    failed = job["attempts"] >= settings.max_attempts
    with db:
        if failed:
            db.execute(
                "UPDATE jobs SET status='failed', lease_owner=NULL, lease_expires_at=NULL, "
                "error=?, finished_at=? WHERE id=?",
                (payload.error[:2000], now, job_id),
            )
            db.execute(
                "UPDATE recordings SET status='failed' WHERE id=?",
                (job["recording_id"],),
            )
        else:
            db.execute(
                "UPDATE jobs SET status='queued', lease_owner=NULL, lease_expires_at=NULL, "
                "error=? WHERE id=?",
                (payload.error[:2000], job_id),
            )
            db.execute(
                "UPDATE recordings SET status='uploaded' WHERE id=?",
                (job["recording_id"],),
            )
        db.execute(
            "INSERT INTO events(id, job_id, type, message, created_at) "
            "VALUES (?, ?, 'failed', ?, ?)",
            (new_id("evt"), job_id, payload.error[:2000], now),
        )
    return {
        "job_id": job_id,
        "status": "failed" if failed else "queued",
    }
