from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from app.asr_chunking import plan_boundaries, split_wav
from app.summarizer import resolve_speaker_names
from app.transcriber import Segment


def test_plan_boundaries_prefers_nearest_silence() -> None:
    silences = [(880.0, 900.0), (1790.0, 1810.0), (2700.0, 2720.0)]
    boundaries = plan_boundaries(
        3600.0, silences, target_s=900, min_chunk_s=300, max_chunk_s=1200
    )
    assert boundaries == [890.0, 1800.0, 2710.0]


def test_plan_boundaries_falls_back_without_silence() -> None:
    boundaries = plan_boundaries(
        3600.0, [], target_s=900, min_chunk_s=300, max_chunk_s=1200
    )
    assert boundaries == [900.0, 1800.0, 2700.0]


def test_plan_boundaries_avoids_short_tail() -> None:
    boundaries = plan_boundaries(
        1300.0, [], target_s=900, min_chunk_s=500, max_chunk_s=1200
    )
    assert boundaries == []


def test_plan_boundaries_ignores_silence_outside_window() -> None:
    silences = [(100.0, 120.0), (2500.0, 2520.0)]
    boundaries = plan_boundaries(
        2400.0, silences, target_s=900, min_chunk_s=300, max_chunk_s=1200
    )
    assert boundaries == [900.0, 1800.0]


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="需要 ffmpeg")
def test_split_wav_offsets_and_durations(tmp_path: Path) -> None:
    source = tmp_path / "source.wav"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=3",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(source),
        ],
        check=True,
    )
    chunks = split_wav(source, [1.0, 2.0], tmp_path / "chunks", 3.0)
    assert len(chunks) == 3
    assert [chunk.offset_ms for chunk in chunks] == [0, 1000, 2000]
    for chunk in chunks:
        assert chunk.path.is_file()
        assert chunk.path.stat().st_size > 0
    assert chunks[-1].duration_ms == 1000


def test_chunk_speakers_are_not_cross_mapped() -> None:
    segments = [
        Segment(0, 100, "发言人1", "甲"),
        Segment(200, 300, "第2段发言人1", "乙"),
    ]
    names = resolve_speaker_names(segments, {"1": "张三"})
    assert names["发言人1"] == "张三"
    assert names["第2段发言人1"] == "第2段发言人1"
