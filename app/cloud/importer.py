from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from ..library import LIBRARY_DIR, entry_path, scan_entries
from .client import CloudClient, CloudError
from .store import load_agent

RESULT_NAMES = (
    "minutes.md",
    "transcript.md",
    "transcript.txt",
    "transcript.srt",
    "transcript.json",
)


class LocalImportError(RuntimeError):
    pass


def _load_entry(path: Path) -> dict:
    meta_path = path / "meta.json"
    if not meta_path.is_file():
        raise LocalImportError(f"目录中没有 meta.json：{path}")
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise LocalImportError(f"meta.json 无法读取：{exc}") from exc
    if not isinstance(data, dict):
        raise LocalImportError("meta.json 格式无效")
    try:
        data["path"] = path.resolve().relative_to(LIBRARY_DIR.resolve()).as_posix()
    except ValueError as exc:
        raise LocalImportError("只能同步资料库内的条目") from exc
    return data


def resolve_entry(ref: str) -> dict:
    value = (ref or "").strip()
    if not value:
        raise LocalImportError("缺少要同步的条目")
    candidate = Path(value)
    if candidate.is_dir():
        return _load_entry(candidate)
    for entry in scan_entries():
        if str(entry.get("job_id")) == value:
            return entry
    raise LocalImportError(f"找不到资料库条目：{value}")


def _utc_created(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        parsed = datetime.now()
    if parsed.tzinfo is None:
        parsed = parsed.astimezone()
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _result_paths(entry: dict) -> list[Path]:
    root = entry_path(entry)
    sources = entry.get("files") or {}
    names: list[str] = []
    for name in sources.values():
        if isinstance(name, str) and name in RESULT_NAMES and name not in names:
            names.append(name)
    for name in RESULT_NAMES:
        if (root / name).is_file() and name not in names:
            names.append(name)
    paths = [root / name for name in names if (root / name).is_file()]
    if not any(path.name == "minutes.md" for path in paths):
        raise LocalImportError("条目缺少 minutes.md，无法同步")
    return paths


def push_entry(entry: dict, client: CloudClient | None = None) -> dict:
    credentials = load_agent()
    if credentials is None:
        raise LocalImportError("本机尚未配对云代理，无法同步到手机")
    root = entry_path(entry)
    payload = {
        "local_id": str(entry.get("job_id") or root.name),
        "title": str(entry.get("topic") or root.name)[:200],
        "content_type": str(entry.get("type") or "meeting"),
        "topic": str(entry.get("topic") or root.name)[:200],
        "summary": " ".join(str(entry.get("summary") or "").split())[:500],
        "duration_s": float(entry.get("duration_s") or 0),
        "created_at": _utc_created(str(entry.get("created_at") or "")),
    }
    paths = _result_paths(entry)
    owned = client is None
    client = client or CloudClient(credentials.server_url, credentials.token)
    try:
        return client.import_note(payload, paths)
    except CloudError as exc:
        raise LocalImportError(str(exc)) from exc
    finally:
        if owned:
            client.close()
