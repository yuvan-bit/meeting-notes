from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from ..config import Settings
from ..deps import get_db, get_settings, require_device, require_phone
from ..schemas import RecordingCreate
from ..storage import audio_rel_path, audio_suffix, remove_tree
from ..utils import iso, new_id, parse_iso
from .common import get_recording, get_job, serialize_recording

router = APIRouter(tags=["recordings"])


@router.post("/recordings", status_code=201)
def create_recording(
    payload: RecordingCreate,
    device: dict = Depends(require_phone),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if payload.size_bytes > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="文件超过上传大小上限")

    if payload.client_upload_id:
        existing = db.execute(
            "SELECT * FROM recordings WHERE device_id=? AND client_upload_id=?",
            (device["id"], payload.client_upload_id),
        ).fetchone()
        if existing is not None:
            return {
                "recording_id": existing["id"],
                "chunk_size": existing["chunk_size"],
                "total_chunks": existing["total_chunks"],
                "status": existing["status"],
                "created": False,
            }

    try:
        suffix = audio_suffix(payload.filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    total_chunks = (payload.size_bytes + settings.chunk_size - 1) // settings.chunk_size
    if total_chunks > 10000:
        raise HTTPException(status_code=413, detail="分片数量过多")

    free = shutil.disk_usage(settings.data_dir).free
    if free < payload.size_bytes + 200 * 1024 * 1024:
        raise HTTPException(status_code=507, detail="服务器磁盘空间不足")

    recording_id = new_id("rec")
    with db:
        db.execute(
            "INSERT INTO recordings("
            "id, device_id, title, content_type, original_filename, client_upload_id, "
            "size_bytes, sha256, duration_s, status, chunk_size, total_chunks, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'uploading', ?, ?, ?)",
            (
                recording_id,
                device["id"],
                payload.title,
                payload.content_type,
                payload.filename,
                payload.client_upload_id,
                payload.size_bytes,
                payload.sha256,
                payload.duration_s,
                settings.chunk_size,
                total_chunks,
                iso(),
            ),
        )
    return {
        "recording_id": recording_id,
        "chunk_size": settings.chunk_size,
        "total_chunks": total_chunks,
        "status": "uploading",
        "created": True,
    }


@router.get("/recordings/{recording_id}/chunks")
def recording_chunks(
    recording_id: str,
    device: dict = Depends(require_phone),
    db: sqlite3.Connection = Depends(get_db),
):
    recording = get_recording(db, recording_id, device["id"])
    uploaded = [
        row["idx"]
        for row in db.execute(
            "SELECT idx FROM recording_chunks WHERE recording_id=? ORDER BY idx",
            (recording_id,),
        ).fetchall()
    ]
    missing = sorted(set(range(recording["total_chunks"])) - set(uploaded))
    return {
        "recording_id": recording_id,
        "status": recording["status"],
        "chunk_size": recording["chunk_size"],
        "total_chunks": recording["total_chunks"],
        "uploaded": uploaded,
        "missing": missing,
    }


@router.put("/recordings/{recording_id}/chunks/{idx}")
async def upload_chunk(
    recording_id: str,
    idx: int,
    request: Request,
    device: dict = Depends(require_phone),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    recording = get_recording(db, recording_id, device["id"])
    if recording["status"] != "uploading":
        raise HTTPException(status_code=409, detail="该录音已上传完成")
    if idx < 0 or idx >= recording["total_chunks"]:
        raise HTTPException(status_code=400, detail="分片序号越界")

    header_hash = (request.headers.get("x-chunk-sha256") or "").strip().lower()
    existing = db.execute(
        "SELECT * FROM recording_chunks WHERE recording_id=? AND idx=?",
        (recording_id, idx),
    ).fetchone()
    if existing is not None:
        if not header_hash or header_hash == existing["sha256"]:
            return {
                "ok": True,
                "duplicate": True,
                "idx": idx,
                "size_bytes": existing["size_bytes"],
                "sha256": existing["sha256"],
            }
        raise HTTPException(status_code=409, detail="该分片已存在且内容不同")

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared = int(content_length)
        except ValueError:
            raise HTTPException(status_code=400, detail="Content-Length 无效")
        if declared > settings.max_chunk_bytes or declared > recording["chunk_size"]:
            raise HTTPException(status_code=413, detail="分片过大")

    free = shutil.disk_usage(settings.tmp_dir).free
    if free < recording["chunk_size"] + 64 * 1024 * 1024:
        raise HTTPException(status_code=507, detail="服务器磁盘空间不足")

    chunk_dir = settings.tmp_dir / recording_id
    chunk_dir.mkdir(parents=True, exist_ok=True)
    temp_path = chunk_dir / f"{idx}.new"
    final_path = chunk_dir / f"{idx}.part"

    digest = hashlib.sha256()
    size = 0
    try:
        with temp_path.open("wb") as handle:
            async for part in request.stream():
                if not part:
                    continue
                size += len(part)
                if size > settings.max_chunk_bytes or size > recording["chunk_size"]:
                    raise HTTPException(status_code=413, detail="分片过大")
                digest.update(part)
                handle.write(part)
        if size == 0:
            raise HTTPException(status_code=400, detail="分片为空")
        actual_hash = digest.hexdigest()
        if header_hash and header_hash != actual_hash:
            raise HTTPException(status_code=400, detail="分片校验失败")
        os.replace(temp_path, final_path)
    except HTTPException:
        temp_path.unlink(missing_ok=True)
        raise
    except Exception as exc:
        temp_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="分片接收失败") from exc

    with db:
        db.execute(
            "INSERT OR REPLACE INTO recording_chunks("
            "recording_id, idx, size_bytes, sha256, path, created_at"
            ") VALUES (?, ?, ?, ?, ?, ?)",
            (
                recording_id,
                idx,
                size,
                actual_hash,
                f"{recording_id}/{idx}.part",
                iso(),
            ),
        )
    return {
        "ok": True,
        "duplicate": False,
        "idx": idx,
        "size_bytes": size,
        "sha256": actual_hash,
    }


@router.post("/recordings/{recording_id}/complete")
def complete_recording(
    recording_id: str,
    device: dict = Depends(require_phone),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    recording = get_recording(db, recording_id, device["id"])
    job = get_job(db, recording_id)
    if job is not None:
        note = db.execute("SELECT id FROM notes WHERE job_id=?", (job["id"],)).fetchone()
        return {
            "recording_id": recording_id,
            "job_id": job["id"],
            "status": job["status"],
            "note_id": note["id"] if note else None,
            "created": False,
        }
    if recording["status"] != "uploading":
        raise HTTPException(status_code=409, detail="录音状态不允许提交")

    chunks = db.execute(
        "SELECT * FROM recording_chunks WHERE recording_id=? ORDER BY idx",
        (recording_id,),
    ).fetchall()
    if len(chunks) != recording["total_chunks"]:
        raise HTTPException(
            status_code=400,
            detail=f"分片不完整：已有 {len(chunks)}/{recording['total_chunks']}",
        )

    total_size = sum(row["size_bytes"] for row in chunks)
    if total_size != recording["size_bytes"]:
        raise HTTPException(status_code=400, detail="分片总大小与声明不一致")

    free = shutil.disk_usage(settings.tmp_dir).free
    if free < recording["size_bytes"] + 64 * 1024 * 1024:
        raise HTTPException(status_code=507, detail="服务器磁盘空间不足")

    suffix = audio_suffix(recording["original_filename"])
    rel_path = audio_rel_path(parse_iso(recording["created_at"]), recording_id, suffix)
    final_path = settings.audio_dir / rel_path
    final_path.parent.mkdir(parents=True, exist_ok=True)
    assembling = settings.tmp_dir / f"{recording_id}.assembling"

    digest = hashlib.sha256()
    try:
        with assembling.open("wb") as out:
            for row in chunks:
                chunk_path = settings.tmp_dir / row["path"]
                if not chunk_path.is_file():
                    raise HTTPException(status_code=400, detail=f"缺少分片 {row['idx']}")
                with chunk_path.open("rb") as src:
                    while True:
                        block = src.read(1024 * 1024)
                        if not block:
                            break
                        digest.update(block)
                        out.write(block)
        if digest.hexdigest() != recording["sha256"]:
            raise HTTPException(status_code=400, detail="整文件校验失败，请重新上传")
        os.replace(assembling, final_path)
    except HTTPException:
        assembling.unlink(missing_ok=True)
        raise
    except OSError as exc:
        assembling.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail="合并音频失败") from exc

    job_id = new_id("job")
    now = iso()
    with db:
        db.execute(
            "UPDATE recordings SET status='uploaded', audio_path=?, uploaded_at=? WHERE id=?",
            (rel_path.as_posix(), now, recording_id),
        )
        db.execute(
            "INSERT INTO jobs(id, recording_id, status, attempts, created_at) "
            "VALUES (?, ?, 'queued', 0, ?)",
            (job_id, recording_id, now),
        )
        db.execute(
            "INSERT INTO events(id, job_id, type, message, created_at) "
            "VALUES (?, ?, 'queued', ?, ?)",
            (new_id("evt"), job_id, "音频上传完成", now),
        )
    remove_tree(settings.tmp_dir / recording_id)
    return {
        "recording_id": recording_id,
        "job_id": job_id,
        "status": "queued",
        "note_id": None,
        "created": True,
    }


@router.get("/recordings")
def list_recordings(
    device: dict = Depends(require_device),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    rows = db.execute(
        "SELECT r.*, j.id AS job_id, j.status AS job_status, j.attempts AS job_attempts, "
        "j.error AS job_error, j.finished_at AS job_finished_at, n.id AS note_id "
        "FROM recordings r "
        "LEFT JOIN jobs j ON j.recording_id=r.id "
        "LEFT JOIN notes n ON n.job_id=j.id "
        "ORDER BY r.created_at DESC LIMIT 100"
    ).fetchall()
    return {"items": [serialize_recording(row, settings) for row in rows]}


@router.get("/recordings/{recording_id}")
def get_recording_detail(
    recording_id: str,
    device: dict = Depends(require_device),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    row = db.execute(
        "SELECT r.*, j.id AS job_id, j.status AS job_status, j.attempts AS job_attempts, "
        "j.error AS job_error, j.finished_at AS job_finished_at, n.id AS note_id "
        "FROM recordings r "
        "LEFT JOIN jobs j ON j.recording_id=r.id "
        "LEFT JOIN notes n ON n.job_id=j.id "
        "WHERE r.id=?",
        (recording_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="录音不存在")
    return serialize_recording(row, settings)


@router.get("/recordings/{recording_id}/audio")
def download_audio(
    recording_id: str,
    device: dict = Depends(require_device),
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
