from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def iso(value: datetime | None = None) -> str:
    return (value or utcnow()).isoformat().replace("+00:00", "Z")


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str | Path, block: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        while True:
            chunk = handle.read(block)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def json_loads(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def human_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(size) < 1024 or unit == "TB":
            return f"{size:.1f}{unit}"
        size /= 1024
    return f"{value}B"
