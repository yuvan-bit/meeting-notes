from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .. import config

CLOUD_DIR = config.DATA_DIR / "cloud"
INBOX_DIR = CLOUD_DIR / "inbox"
OUTBOX_DIR = CLOUD_DIR / "outbox"
ORPHAN_DIR = CLOUD_DIR / "orphaned"
AGENT_FILE = CLOUD_DIR / "agent.json"
AGENT_LOCK = CLOUD_DIR / "agent.lock"
LOG_FILE = CLOUD_DIR / "agent.log"

for _dir in (CLOUD_DIR, INBOX_DIR, OUTBOX_DIR, ORPHAN_DIR):
    _dir.mkdir(parents=True, exist_ok=True)


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_optional_float(name: str, default: float | None = None) -> float | None:
    value = os.environ.get(name)
    if value is None:
        return default
    value = value.strip()
    if not value or value.lower() in {"off", "none", "false"}:
        return None
    try:
        return float(value)
    except ValueError:
        return default


@dataclass(frozen=True)
class AgentSettings:
    server_url: str = ""
    poll_seconds: int = 60
    idle_seconds: int = 600
    require_ac: bool = True
    cpu_max_percent: float | None = 25.0
    gpu_max_util: float | None = 30.0
    heartbeat_seconds: int = 240
    model: str = config.DEFAULT_LLM
    asr_device: str = config.ASR_DEVICE

    @classmethod
    def from_env(cls, server_url: str = "") -> "AgentSettings":
        return cls(
            server_url=server_url or os.environ.get("MEETING_CLOUD_URL", "").strip(),
            poll_seconds=max(10, int(os.environ.get("MEETING_AGENT_POLL_SECONDS", "60"))),
            idle_seconds=max(0, int(os.environ.get("MEETING_IDLE_SECONDS", "600"))),
            require_ac=_env_bool("MEETING_AGENT_REQUIRE_AC", True),
            cpu_max_percent=_env_optional_float("MEETING_AGENT_CPU_MAX", 25.0),
            gpu_max_util=_env_optional_float("MEETING_AGENT_GPU_MAX_UTIL", 30.0),
            heartbeat_seconds=max(30, int(os.environ.get("MEETING_AGENT_HEARTBEAT_SECONDS", "240"))),
            model=os.environ.get("MEETING_LLM", config.DEFAULT_LLM),
            asr_device=os.environ.get("MEETING_ASR_DEVICE", config.ASR_DEVICE),
        )


def resolve_server_url(explicit: str = "") -> str:
    url = (explicit or os.environ.get("MEETING_CLOUD_URL", "")).strip()
    if url:
        return url.rstrip("/")
    from .store import load_agent

    saved = load_agent()
    return saved.server_url if saved else ""


def mask_token(token: str) -> str:
    if not token:
        return "(未配对)"
    if len(token) <= 10:
        return token[:2] + "…"
    return f"{token[:6]}…{token[-4:]}"
