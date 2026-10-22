from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

from .config import AGENT_FILE


class StoreError(RuntimeError):
    pass


@dataclass
class AgentCredentials:
    server_url: str
    device_id: str
    device_name: str
    role: str
    token: str
    paired_at: str

    @classmethod
    def from_dict(cls, data: dict) -> "AgentCredentials":
        try:
            return cls(
                server_url=str(data["server_url"]).rstrip("/"),
                device_id=str(data["device_id"]),
                device_name=str(data["device_name"]),
                role=str(data.get("role", "pc")),
                token=str(data["token"]),
                paired_at=str(data.get("paired_at", "")),
            )
        except (KeyError, TypeError) as exc:
            raise StoreError("本机配对信息不完整，请重新配对") from exc


def load_agent(path: Path = AGENT_FILE) -> AgentCredentials | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise StoreError(f"无法读取配对信息：{exc}") from exc
    if not isinstance(data, dict):
        raise StoreError("配对信息格式错误，请重新配对")
    return AgentCredentials.from_dict(data)


def save_agent(credentials: AgentCredentials, path: Path = AGENT_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = json.dumps(asdict(credentials), ensure_ascii=False, indent=2)
    tmp.write_text(payload, encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:
        pass
    os.replace(tmp, path)


def clear_agent(path: Path = AGENT_FILE) -> bool:
    if path.exists():
        path.unlink()
        return True
    return False


def build_credentials(
    server_url: str,
    device_id: str,
    device_name: str,
    role: str,
    token: str,
) -> AgentCredentials:
    return AgentCredentials(
        server_url=server_url.rstrip("/"),
        device_id=device_id,
        device_name=device_name,
        role=role,
        token=token,
        paired_at=datetime.now().replace(microsecond=0).isoformat(),
    )
