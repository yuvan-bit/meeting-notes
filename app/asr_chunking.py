from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .audio import AudioError, probe_duration

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SILENCE_RE = re.compile(r"silence_(start|end):\s*([0-9.]+)")


@dataclass(frozen=True)
class AudioChunk:
    index: int
    path: Path
    offset_ms: int
    duration_ms: int


def detect_silences(
    path: Path,
    noise_db: int = -35,
    min_silence_s: float = 0.6,
) -> list[tuple[float, float]]:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-nostats",
        "-loglevel",
        "info",
        "-i",
        str(path),
        "-af",
        f"silencedetect=noise={noise_db}dB:d={min_silence_s}",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AudioError("找不到 ffmpeg，无法分析音频停顿。") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()[-1000:]
        raise AudioError(f"音频停顿分析失败：{detail}")

    duration = probe_duration(path)
    silences: list[tuple[float, float]] = []
    starts: set[float] = set()
    for line in proc.stderr.decode("utf-8", errors="replace").splitlines():
        match = SILENCE_RE.search(line)
        if not match:
            continue
        value = float(match.group(2))
        if match.group(1) == "start":
            starts.add(value)
        elif starts:
            for start in list(starts):
                if start <= value:
                    silences.append((start, value))
                    starts.discard(start)
                    break
    for start in starts:
        if start < duration:
            silences.append((start, duration))
    return sorted(silences)


def plan_boundaries(
    duration_s: float,
    silences: list[tuple[float, float]],
    target_s: float,
    min_chunk_s: float,
    max_chunk_s: float,
) -> list[float]:
    if duration_s <= 0:
        return []
    target = max(1.0, target_s)
    minimum = max(1.0, min_chunk_s)
    maximum = max(target, max_chunk_s)
    if duration_s <= maximum:
        return []

    boundaries: list[float] = []
    cursor = 0.0
    while duration_s - cursor > maximum:
        ideal = cursor + target
        lower = cursor + minimum
        upper = min(cursor + maximum, duration_s - minimum)
        if upper <= lower:
            break
        candidates = [
            (start + end) / 2
            for start, end in silences
            if lower <= (start + end) / 2 <= upper
        ]
        boundary = min(candidates, key=lambda value: abs(value - ideal)) if candidates else ideal
        if boundary - cursor < minimum:
            boundary = cursor + minimum
        if boundary >= duration_s - minimum:
            break
        boundaries.append(round(boundary, 3))
        cursor = boundary
    return boundaries


def split_wav(
    source: Path,
    boundaries: list[float],
    output_dir: Path,
    duration_s: float,
) -> list[AudioChunk]:
    if not boundaries:
        return [
            AudioChunk(
                index=0,
                path=source,
                offset_ms=0,
                duration_ms=int(round(duration_s * 1000)),
            )
        ]

    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / "chunk_%03d.wav"
    segment_times = ",".join(f"{value:.3f}" for value in boundaries)
    command = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(source),
        "-f",
        "segment",
        "-segment_times",
        segment_times,
        "-reset_timestamps",
        "1",
        "-c",
        "copy",
        str(pattern),
    ]
    try:
        proc = subprocess.run(
            command,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except FileNotFoundError as exc:
        raise AudioError("找不到 ffmpeg，无法切分音频。") from exc
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace").strip()[-1000:]
        raise AudioError(f"音频切分失败：{detail}")

    points = [0.0, *boundaries, duration_s]
    chunks: list[AudioChunk] = []
    for index in range(len(points) - 1):
        path = output_dir / f"chunk_{index:03d}.wav"
        if not path.is_file() or path.stat().st_size == 0:
            raise AudioError(f"音频切分不完整：缺少第 {index + 1} 段")
        chunks.append(
            AudioChunk(
                index=index,
                path=path,
                offset_ms=int(round(points[index] * 1000)),
                duration_ms=int(round((points[index + 1] - points[index]) * 1000)),
            )
        )
    return chunks
