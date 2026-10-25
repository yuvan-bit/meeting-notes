from __future__ import annotations

import hashlib
import json
import mimetypes
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from starlette.datastructures import UploadFile as StarletteUploadFile

from ..config import Settings
from ..deps import get_db, get_settings, require_device, require_pc
from ..schemas import PinRequest
from ..storage import RESULT_FILE_NAMES, note_file_path, notes_rel_dir
from ..utils import iso, json_loads, new_id, parse_iso, utcnow

router = APIRouter(tags=["notes"])


def _like_term(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _serialize_note(row: sqlite3.Row, settings: Settings) -> dict:
    audio_available = False
    if row["audio_path"] and not row["audio_deleted_at"]:
        audio_available = (settings.audio_dir / row["audio_path"]).is_file()
    files = json_loads(row["files_json"], [])
    if not isinstance(files, list):
        files = []
    return {
        "job_id": row["job_id"],
        "note_id": row["id"],
        "recording_id": row["recording_id"],
        "title": row["title"],
        "content_type": row["content_type"],
        "topic": row["topic"],
        "summary": row["summary"] or "",
        "created_at": row["created_at"],
        "duration_s": row["duration_s"],
        "pinned": bool(row["pinned"]),
        "audio_available": audio_available,
        "files": files,
    }


@router.get("/notes")
def list_notes(
    content_type: str = Query(default="", max_length=20),
    q: str = Query(default="", max_length=100),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    device: dict = Depends(require_device),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    where: list[str] = []
    params: list[object] = []
    if content_type in {"meeting", "course"}:
        where.append("n.content_type=?")
        params.append(content_type)
    term = q.strip()
    if term:
        like = _like_term(term)
        where.append(
            "(n.topic LIKE ? ESCAPE '\\' OR n.summary LIKE ? ESCAPE '\\' "
            "OR r.title LIKE ? ESCAPE '\\')"
        )
        params.extend([like, like, like])
    clause = (" WHERE " + " AND ".join(where)) if where else ""

    base = (
        "FROM notes n JOIN jobs j ON j.id=n.job_id "
        "JOIN recordings r ON r.id=j.recording_id"
    )
    total = db.execute(f"SELECT COUNT(*) AS count {base}{clause}", params).fetchone()["count"]
    rows = db.execute(
        "SELECT n.*, r.title, r.duration_s, r.audio_path, r.audio_deleted_at, "
        f"r.pinned, r.id AS recording_id, j.id AS job_id {base}{clause} "
        "ORDER BY n.created_at DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return {
        "items": [_serialize_note(row, settings) for row in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/notes/{job_id}")
def note_detail(
    job_id: str,
    device: dict = Depends(require_device),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    row = db.execute(
        "SELECT n.*, r.title, r.duration_s, r.audio_path, r.audio_deleted_at, "
        "r.pinned, r.id AS recording_id, j.id AS job_id "
        "FROM notes n JOIN jobs j ON j.id=n.job_id "
        "JOIN recordings r ON r.id=j.recording_id WHERE n.job_id=?",
        (job_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="笔记不存在")

    note_dir = settings.notes_dir / row["dir_rel"]
    minutes_path = note_dir / "minutes.md"
    minutes = minutes_path.read_text(encoding="utf-8") if minutes_path.is_file() else ""

    meta: dict = {}
    meta_path = note_dir / "meta.json"
    if meta_path.is_file():
        try:
            loaded = json.loads(meta_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                meta = loaded
        except (OSError, ValueError):
            meta = {}

    files = json_loads(row["files_json"], [])
    if not isinstance(files, list):
        files = []
    file_items = []
    for item in files:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "")
        if name not in RESULT_FILE_NAMES:
            continue
        path = note_dir / name
        if not path.is_file():
            continue
        file_items.append(
            {
                "name": name,
                "size_bytes": path.stat().st_size,
                "url": f"/api/v1/notes/{job_id}/files/{name}",
            }
        )

    detail = _serialize_note(row, settings)
    detail["minutes_markdown"] = minutes
    detail["meta"] = meta
    detail["files"] = file_items
    return detail


@router.get("/notes/{job_id}/files/{name}")
def download_note_file(
    job_id: str,
    name: str,
    device: dict = Depends(require_device),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if name not in RESULT_FILE_NAMES:
        raise HTTPException(status_code=404, detail="文件不存在")
    row = db.execute("SELECT dir_rel FROM notes WHERE job_id=?", (job_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    path = note_file_path(settings, row["dir_rel"], name)
    if not path.is_file():
        raise HTTPException(status_code=404, detail="文件不存在")
    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return FileResponse(path, filename=name, media_type=media_type)


@router.post("/notes/{job_id}/pin")
def pin_note(
    job_id: str,
    payload: PinRequest,
    device: dict = Depends(require_device),
    db: sqlite3.Connection = Depends(get_db),
):
    row = db.execute(
        "SELECT r.id FROM notes n JOIN jobs j ON j.id=n.job_id "
        "JOIN recordings r ON r.id=j.recording_id WHERE n.job_id=?",
        (job_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="笔记不存在")
    with db:
        db.execute("UPDATE recordings SET pinned=? WHERE id=?", (1 if payload.pinned else 0, row["id"]))
    return {"job_id": job_id, "pinned": payload.pinned}


def _import_created_at(value: str) -> datetime:
    try:
        parsed = parse_iso(value)
    except (TypeError, ValueError):
        return utcnow()
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    parsed = parsed.astimezone(timezone.utc).replace(microsecond=0)
    now = utcnow()
    if parsed > now:
        return now
    if parsed.year < 2000:
        return now
    return parsed


@router.post("/notes/import", status_code=201)
async def import_local_note(
    request: Request,
    device: dict = Depends(require_pc),
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    form = await request.form()
    local_id = str(form.get("local_id") or "").strip()
    if not local_id or len(local_id) > 180:
        raise HTTPException(status_code=400, detail="缺少有效的本地记录标识")
    key = hashlib.sha256(f"{device['id']}:{local_id}".encode("utf-8")).hexdigest()[:32]
    recording_id = f"rec_local_{key}"
    job_id = f"job_local_{key}"
    note_id = f"note_local_{key}"

    title = " ".join(str(form.get("title") or "").split())[:200]
    if not title:
        title = "本地导入纪要"
    topic = " ".join(str(form.get("topic") or "").split())[:200] or title
    summary = str(form.get("summary") or "").strip()[:500]
    content_type = str(form.get("content_type") or "meeting")
    if content_type not in {"meeting", "course"}:
        content_type = "meeting"
    try:
        duration_s = max(0.0, float(form.get("duration_s") or 0))
    except (TypeError, ValueError):
        duration_s = 0.0
    created = _import_created_at(str(form.get("created_at") or ""))

    uploads = form.getlist("files")
    if not uploads:
        raise HTTPException(status_code=400, detail="没有结果文件")

    temp_dir = settings.tmp_dir / new_id("import")
    temp_dir.mkdir(parents=True, exist_ok=False)
    total = 0
    seen: set[str] = set()
    try:
        for item in uploads:
            if not isinstance(item, StarletteUploadFile):
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

        if not (temp_dir / "minutes.md").is_file():
            raise HTTPException(status_code=400, detail="缺少 minutes.md")

        existing = db.execute("SELECT * FROM notes WHERE job_id=?", (job_id,)).fetchone()
        duplicate = existing is not None
        final_dir = settings.notes_dir / notes_rel_dir(created, job_id)
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        old_dir = settings.notes_dir / existing["dir_rel"] if existing else None
        if final_dir.exists():
            shutil.rmtree(final_dir, ignore_errors=True)
        shutil.move(str(temp_dir), str(final_dir))
        if old_dir is not None and old_dir != final_dir and old_dir.is_dir():
            shutil.rmtree(old_dir, ignore_errors=True)

        files = []
        for path in sorted(final_dir.iterdir()):
            if path.is_file() and path.name in RESULT_FILE_NAMES:
                files.append({"name": path.name, "size_bytes": path.stat().st_size})

        now = utcnow()
        local_filename = f"{Path(local_id).name[:60] or 'local'}.local"
        digest = hashlib.sha256(local_id.encode("utf-8")).hexdigest()
        with db:
            db.execute(
                "INSERT INTO recordings(id, device_id, title, content_type, original_filename, "
                "client_upload_id, size_bytes, sha256, duration_s, status, audio_path, chunk_size, "
                "total_chunks, created_at, uploaded_at, pinned, audio_deleted_at) "
                "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, 'done', NULL, 0, 0, ?, ?, 0, ?) "
                "ON CONFLICT(id) DO UPDATE SET title=excluded.title, "
                "content_type=excluded.content_type, duration_s=excluded.duration_s, "
                "uploaded_at=excluded.uploaded_at",
                (
                    recording_id,
                    device["id"],
                    title,
                    content_type,
                    local_filename,
                    local_id[:80],
                    digest,
                    duration_s,
                    iso(created),
                    iso(now),
                    iso(now),
                ),
            )
            db.execute(
                "INSERT INTO jobs(id, recording_id, status, attempts, created_at, started_at, finished_at) "
                "VALUES (?, ?, 'done', 0, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET status='done', finished_at=excluded.finished_at, error=NULL",
                (job_id, recording_id, iso(created), iso(created), iso(now)),
            )
            db.execute(
                "INSERT INTO notes(id, job_id, content_type, topic, summary, dir_rel, files_json, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(job_id) DO UPDATE SET content_type=excluded.content_type, "
                "topic=excluded.topic, summary=excluded.summary, dir_rel=excluded.dir_rel, "
                "files_json=excluded.files_json, updated_at=excluded.updated_at",
                (
                    note_id,
                    job_id,
                    content_type,
                    topic,
                    summary,
                    notes_rel_dir(created, job_id).as_posix(),
                    json.dumps(files, ensure_ascii=False),
                    iso(created),
                    iso(now),
                ),
            )
            if not duplicate:
                db.execute(
                    "INSERT INTO events(id, job_id, type, message, created_at) "
                    "VALUES (?, ?, 'imported', '本地纪要已同步', ?)",
                    (new_id("evt"), job_id, iso(now)),
                )
        return {
            "job_id": job_id,
            "note_id": note_id,
            "recording_id": recording_id,
            "status": "done",
            "duplicate": duplicate,
            "files": files,
        }
    finally:
        if temp_dir.exists():
            shutil.rmtree(temp_dir, ignore_errors=True)
