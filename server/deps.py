from __future__ import annotations

import sqlite3
from typing import Iterator

from fastapi import Depends, HTTPException, Request

from .config import Settings
from .db import connect
from .security import extract_bearer, hash_token
from .utils import iso, parse_iso, utcnow


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    settings: Settings = request.app.state.settings
    conn = connect(settings.db_path)
    try:
        yield conn
    finally:
        conn.close()


def get_current_device(
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
) -> dict:
    token = extract_bearer(request.headers.get("authorization"))
    if not token:
        raise HTTPException(
            status_code=401,
            detail="缺少认证令牌",
            headers={"WWW-Authenticate": "Bearer"},
        )
    row = db.execute(
        "SELECT id, name, role, created_at, last_seen_at, revoked "
        "FROM devices WHERE token_hash=?",
        (hash_token(token),),
    ).fetchone()
    if row is None or row["revoked"]:
        raise HTTPException(
            status_code=401,
            detail="认证令牌无效",
            headers={"WWW-Authenticate": "Bearer"},
        )
    device = dict(row)
    last_seen = device.get("last_seen_at")
    if not last_seen or (utcnow() - parse_iso(last_seen)).total_seconds() > 60:
        with db:
            db.execute(
                "UPDATE devices SET last_seen_at=? WHERE id=?",
                (iso(), device["id"]),
            )
    return device


def require_phone(device: dict = Depends(get_current_device)) -> dict:
    if device["role"] != "phone":
        raise HTTPException(status_code=403, detail="需要手机端权限")
    return device


def require_pc(device: dict = Depends(get_current_device)) -> dict:
    if device["role"] != "pc":
        raise HTTPException(status_code=403, detail="需要电脑端权限")
    return device


def require_device(device: dict = Depends(get_current_device)) -> dict:
    return device
