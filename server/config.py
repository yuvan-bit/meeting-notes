from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from pathlib import Path


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是整数") from exc


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    db_path: Path
    audio_dir: Path
    notes_dir: Path
    tmp_dir: Path
    pairing_pepper: str
    chunk_size: int = 8 * 1024 * 1024
    max_chunk_bytes: int = 16 * 1024 * 1024
    max_upload_bytes: int = 2 * 1024**3
    audio_max_bytes: int = 5 * 1024**3
    audio_retention_days: int = 30
    lease_seconds: int = 900
    max_attempts: int = 3
    pairing_ttl_seconds: int = 600
    max_result_file_bytes: int = 20 * 1024 * 1024
    max_result_total_bytes: int = 100 * 1024 * 1024
    host: str = "127.0.0.1"
    port: int = 8787
    docs_enabled: bool = False
    version: str = "0.1.0"

    @property
    def app_dir(self) -> Path:
        return self.data_dir / "app"

    @classmethod
    def create(cls, data_dir: str | Path, **overrides) -> "Settings":
        root = Path(data_dir).expanduser().resolve()
        values = {
            "data_dir": root,
            "db_path": root / "meeting.db",
            "audio_dir": root / "audio",
            "notes_dir": root / "notes",
            "tmp_dir": root / "tmp",
            "pairing_pepper": "",
        }
        values.update(overrides)
        return cls(**values)

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.environ.get("MEETING_DATA_DIR", "/var/lib/meeting-notes"))
        data_dir.mkdir(parents=True, exist_ok=True)
        pepper_path = data_dir / ".pairing_pepper"
        pepper = os.environ.get("MEETING_PAIRING_PEPPER", "").strip()
        if not pepper:
            if pepper_path.is_file():
                pepper = pepper_path.read_text(encoding="utf-8").strip()
            else:
                pepper = secrets.token_hex(32)
                pepper_path.write_text(pepper, encoding="utf-8")
                try:
                    pepper_path.chmod(0o600)
                except OSError:
                    pass
        settings = cls.create(
            data_dir,
            pairing_pepper=pepper,
            chunk_size=_int_env("MEETING_CHUNK_MB", 8) * 1024 * 1024,
            max_chunk_bytes=_int_env("MEETING_MAX_CHUNK_MB", 16) * 1024 * 1024,
            max_upload_bytes=_int_env("MEETING_MAX_UPLOAD_MB", 2048) * 1024 * 1024,
            audio_max_bytes=_int_env("MEETING_AUDIO_MAX_MB", 5120) * 1024 * 1024,
            audio_retention_days=_int_env("MEETING_AUDIO_RETENTION_DAYS", 30),
            lease_seconds=_int_env("MEETING_LEASE_SECONDS", 900),
            max_attempts=_int_env("MEETING_MAX_ATTEMPTS", 3),
            host=os.environ.get("MEETING_HOST", "127.0.0.1"),
            port=_int_env("MEETING_PORT", 8787),
            docs_enabled=_bool_env("MEETING_DOCS", False),
            version=os.environ.get("MEETING_VERSION", "0.1.0"),
        )
        settings.ensure_dirs()
        return settings

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.audio_dir, self.notes_dir, self.tmp_dir, self.app_dir):
            path.mkdir(parents=True, exist_ok=True)
        try:
            self.data_dir.chmod(0o700)
        except OSError:
            pass
