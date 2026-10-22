from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


class AudioError(RuntimeError):
    pass


def _run(cmd: list[str]) -> subprocess.CompletedProcess[bytes]:
    try:
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AudioError(f"找不到 {cmd[0]}，请确认已安装并加入 PATH。") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()[-2000:]
        raise AudioError(f"{Path(cmd[0]).name} 执行失败：{detail}")
    return proc


def probe_duration(path: Path) -> float:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    output = _run(cmd).stdout.decode("utf-8", errors="replace")
    try:
        return float(json.loads(output)["format"]["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise AudioError("无法读取音频时长，文件可能已损坏。") from exc


def convert_to_wav(src: Path, dst: Path) -> Path:
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-c:a",
        "pcm_s16le",
        str(dst),
    ]
    _run(cmd)
    if not dst.exists() or dst.stat().st_size == 0:
        raise AudioError("音频转换失败：输出文件为空。")
    return dst


def format_ts(ms: float, srt: bool = False) -> str:
    total_ms = max(0, int(round(ms)))
    total_s = total_ms // 1000
    hours, rem = divmod(total_s, 3600)
    minutes, seconds = divmod(rem, 60)
    if srt:
        millis = total_ms % 1000
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def safe_stem(name: str) -> str:
    stem = re.sub(r'[\\/:*?"<>|\s]+', "_", name).strip("._")
    return (stem[:60] or "meeting")
