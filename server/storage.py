from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from .config import Settings

AUDIO_SUFFIXES = {
    ".m4a",
    ".aac",
    ".mp3",
    ".wav",
    ".flac",
    ".ogg",
    ".opus",
    ".amr",
    ".wma",
    ".mp4",
    ".mkv",
    ".mov",
    ".webm",
}
RESULT_FILE_NAMES = {
    "minutes.md",
    "transcript.md",
    "transcript.txt",
    "transcript.srt",
    "transcript.json",
    "meta.json",
}


def audio_suffix(filename: str) -> str:
    suffix = Path(filename).suffix.lower()
    if suffix not in AUDIO_SUFFIXES:
        raise ValueError("不支持的音频格式")
    return suffix


def audio_rel_path(when: datetime, recording_id: str, suffix: str) -> Path:
    return Path(f"{when:%Y}") / f"{when:%m}" / f"{recording_id}{suffix}"


def audio_path(settings: Settings, rel_path: str | Path) -> Path:
    return settings.audio_dir / rel_path


def notes_rel_dir(when: datetime, job_id: str) -> Path:
    return Path(f"{when:%Y}") / f"{when:%m}" / job_id


def note_file_path(settings: Settings, dir_rel: str, name: str) -> Path:
    path = (settings.notes_dir / dir_rel / name).resolve()
    root = settings.notes_dir.resolve()
    if root not in path.parents:
        raise ValueError("非法文件路径")
    return path


def extract_section(markdown: str, names: tuple[str, ...]) -> str:
    lines = markdown.splitlines()
    wanted = {name.strip() for name in names}
    collecting = False
    buffer: list[str] = []
    for line in lines:
        heading = re.match(r"^#{1,4}\s+(.+?)\s*$", line)
        if heading:
            title = heading.group(1).strip()
            if collecting:
                break
            if title in wanted:
                collecting = True
                continue
        if collecting:
            buffer.append(line)
    return "\n".join(buffer).strip()


def extract_summary(minutes: str) -> str:
    for names in (
        ("一句话摘要", "一句话概括"),
        ("摘要", "会议摘要", "课程摘要"),
    ):
        value = extract_section(minutes, names)
        if value:
            return " ".join(value.split())[:300]
    return ""


def extract_topic(minutes: str, fallback: str) -> str:
    for line in minutes.splitlines():
        match = re.match(r"^#\s+(.+?)\s*$", line)
        if match:
            value = match.group(1).strip()
            if value and value not in {"会议纪要", "课程笔记"}:
                return value[:120]
    return fallback[:120]


def file_size(path: str | Path) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def remove_tree(path: str | Path) -> None:
    root = Path(path)
    if not root.exists():
        return
    for child in sorted(root.rglob("*"), reverse=True):
        try:
            if child.is_file() or child.is_symlink():
                child.unlink()
            elif child.is_dir():
                child.rmdir()
        except OSError:
            pass
    try:
        root.rmdir()
    except OSError:
        pass
