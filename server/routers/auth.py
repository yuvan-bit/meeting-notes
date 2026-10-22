from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Request

from ..config import Settings
from ..deps import get_db, get_settings, require_device
from ..pairing import consume_pairing_code, create_device
from ..schemas import PairRequest
from ..utils import iso

router = APIRouter(tags=["auth"])


@router.post("/pair", status_code=201)
def pair(
    payload: PairRequest,
    request: Request,
    db: sqlite3.Connection = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    limiter = request.app.state.pair_limiter
    client_key = request.client.host if request.client else "unknown"
    if not limiter.allow(client_key):
        raise HTTPException(status_code=429, detail="尝试过于频繁，请稍后重试")

    code_row = consume_pairing_code(db, settings, payload.code, payload.role)
    if code_row is None:
        raise HTTPException(status_code=400, detail="配对码无效或已过期")

    device_id, token = create_device(db, payload.device_name, payload.role)
    limiter.clear(client_key)
    return {
        "device_id": device_id,
        "token": token,
        "role": payload.role,
        "server_time": iso(),
    }


@router.get("/me")
def me(device: dict = Depends(require_device)):
    return {
        "device_id": device["id"],
        "name": device["name"],
        "role": device["role"],
        "created_at": device["created_at"],
    }
