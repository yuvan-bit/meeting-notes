from __future__ import annotations

import json
import mimetypes
import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from ..config import Settings
from ..deps import get_db, get_settings, require_device
from ..schemas import PinRequest
from ..storage import RESULT_FILE_NAMES, note_file_path
from ..utils import json_loads

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
