from __future__ import annotations

import sqlite3
from datetime import timedelta

from .config import Settings
from .security import (
    hash_pairing_code,
    hash_token,
    new_pairing_code,
    new_token,
)
from .utils import iso, new_id, parse_iso, utcnow


def issue_pairing_code(
    conn: sqlite3.Connection,
    settings: Settings,
    role: str,
    ttl_seconds: int | None = None,
) -> tuple[str, str]:
    code = new_pairing_code()
    now = utcnow()
    expires_at = iso(now + timedelta(seconds=ttl_seconds or settings.pairing_ttl_seconds))
    with conn:
        conn.execute(
            "INSERT INTO pairing_codes(id, code_hash, role, expires_at, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                new_id("pair"),
                hash_pairing_code(code, settings.pairing_pepper),
                role,
                expires_at,
                iso(now),
            ),
        )
    return code, expires_at


def consume_pairing_code(
    conn: sqlite3.Connection,
    settings: Settings,
    code: str,
    role: str,
) -> sqlite3.Row | None:
    code_hash = hash_pairing_code(code, settings.pairing_pepper)
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT * FROM pairing_codes "
            "WHERE code_hash=? AND role=? AND used_at IS NULL "
            "ORDER BY created_at DESC LIMIT 1",
            (code_hash, role),
        ).fetchone()
        if row is None or parse_iso(row["expires_at"]) <= utcnow():
            conn.rollback()
            return None
        changed = conn.execute(
            "UPDATE pairing_codes SET used_at=? WHERE id=? AND used_at IS NULL",
            (iso(), row["id"]),
        )
        if changed.rowcount != 1:
            conn.rollback()
            return None
        conn.commit()
        return row
    except Exception:
        conn.rollback()
        raise


def create_device(
    conn: sqlite3.Connection,
    name: str,
    role: str,
) -> tuple[str, str]:
    device_id = new_id("dev")
    token = new_token()
    with conn:
        conn.execute(
            "INSERT INTO devices(id, name, role, token_hash, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (device_id, name, role, hash_token(token), iso()),
        )
    return device_id, token


def revoke_device(conn: sqlite3.Connection, device_id: str) -> bool:
    with conn:
        changed = conn.execute(
            "UPDATE devices SET revoked=1 WHERE id=? AND revoked=0",
            (device_id,),
        )
    return changed.rowcount == 1
