from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import config
from .audio import convert_to_wav, format_ts, probe_duration, safe_stem
from .asr_chunking import AudioChunk, detect_silences, plan_boundaries, split_wav
from .locks import processing_lock
from .library import (
    create_entry_dir,
    detect_content_type,
    extract_section,
    rebuild_index,
    type_label,
)
from .summarizer import (
    Summarizer,
    parse_speaker_map,
    resolve_speaker_names,
    transcript_lines,
)
from .transcriber import Segment, TranscriptionError

ProgressFn = Callable[[float, str], None]


class PipelineError(RuntimeError):
    pass


@dataclass
class JobResult:
    job_id: str
    input_name: str
    duration_s: float
    asr_device: str
    summary_model: str
    summary_num_gpu: int | None
    summary_chunks: int
    elapsed_s: float
    output_dir: str
    content_type: str = "meeting"
    content_type_label: str = "会议"
    asr_chunks: int = 1
    topic: str = ""
    summary: str = ""
    created_at: str = ""
    files: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _transcript_markdown(
    result: JobResult,
    segments: list[Segment],
    names: dict[str, str],
) -> str:
    lines = [
        f"# {result.content_type_label}转写稿",
        "",
        f"- 源文件：{result.input_name}",
        f"- 时长：{format_ts(result.duration_s * 1000)}",
        f"- 转写设备：{result.asr_device}",
        f"- 说话人：{'、'.join(dict.fromkeys(names.values()))}",
    ]
    if result.asr_chunks > 1:
        lines.append(
            f"- 分段：{result.asr_chunks} 段（长音频按停顿自动切分，发言人编号按段独立）"
        )
    lines.extend(
        [
            "",
            "> 发言人编号由声纹聚类自动生成，跨会议不具可比性；建议按会前报名字人工核对。",
            "",
            "## 逐字稿",
            "",
        ]
    )
    current_speaker = None
    buffer: list[str] = []
    start_ms = 0
    for segment in segments:
        display = names.get(segment.speaker, segment.speaker)
        if current_speaker is None:
            current_speaker = display
            start_ms = segment.start_ms
            buffer = [segment.text]
        elif display == current_speaker:
            buffer.append(segment.text)
        else:
            lines.append(f"**[{format_ts(start_ms)}] {current_speaker}**")
            lines.append("")
            lines.append("".join(buffer))
            lines.append("")
            current_speaker = display
            start_ms = segment.start_ms
            buffer = [segment.text]
    if current_speaker is not None:
        lines.append(f"**[{format_ts(start_ms)}] {current_speaker}**")
        lines.append("")
        lines.append("".join(buffer))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _transcript_srt(segments: list[Segment], names: dict[str, str]) -> str:
    blocks = []
    for index, segment in enumerate(segments, start=1):
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_ts(segment.start_ms, srt=True)} --> {format_ts(segment.end_ms, srt=True)}",
                    f"{names.get(segment.speaker, segment.speaker)}: {segment.text}",
                ]
            )
        )
    return "\n\n".join(blocks) + "\n"


def _transcribe_in_worker(
    wav_path: Path,
    hotwords: str,
    asr_device: str,
    work_dir: Path,
    report: ProgressFn,
    chunks: list[AudioChunk] | None = None,
) -> tuple[list[Segment], str, int]:
    # ASR 放在子进程里跑：进程退出后 CUDA 显存才会完整归还给 Ollama
    output_path = work_dir / "segments.json"
    log_path = work_dir / "asr.log"
    command = [
        sys.executable,
        "-m",
        "app.asr_worker",
        "--output",
        str(output_path),
        "--hotwords",
        hotwords,
        "--device",
        asr_device,
    ]
    if chunks:
        manifest_path = work_dir / "chunks.json"
        manifest_path.write_text(
            json.dumps(
                {
                    "chunks": [
                        {
                            "index": chunk.index,
                            "path": str(chunk.path),
                            "offset_ms": chunk.offset_ms,
                        }
                        for chunk in chunks
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        command.extend(["--manifest", str(manifest_path)])
    else:
        command.extend(["--input", str(wav_path)])

    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    with log_path.open("w", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            command,
            cwd=str(config.BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=log_file,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        assert process.stdout is not None
        for line in process.stdout:
            message = line.strip()
            if message:
                match = re.match(r"\[(\d+)/(\d+)\]", message)
                if match:
                    total = max(1, int(match.group(2)))
                    done = min(total, int(match.group(1)))
                    report(0.12 + 0.5 * (done - 1) / total, message)
                else:
                    report(0.12, message)
        returncode = process.wait()

    if returncode != 0 or not output_path.exists():
        detail = log_path.read_text(encoding="utf-8", errors="replace").strip()[-1500:]
        raise TranscriptionError(
            f"转写子进程失败（退出码 {returncode}）。\n{detail}"
        )
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    segments = [Segment(**item) for item in payload.get("segments", [])]
    if not segments:
        raise TranscriptionError("没有识别到任何语音内容。")
    chunk_count = int(payload.get("chunks") or 1)
    return segments, payload.get("device") or asr_device, chunk_count


def _prepare_chunks(
    wav_path: Path,
    duration_s: float,
    work_dir: Path,
    report: ProgressFn,
) -> list[AudioChunk] | None:
    report(0.1, "音频较长，正在按停顿位置规划分段…")
    silences = detect_silences(wav_path)
    boundaries = plan_boundaries(
        duration_s,
        silences,
        target_s=config.ASR_CHUNK_TARGET_S,
        min_chunk_s=config.ASR_CHUNK_MIN_S,
        max_chunk_s=config.ASR_CHUNK_MAX_S,
    )
    if not boundaries:
        return None
    chunks = split_wav(wav_path, boundaries, work_dir / "chunks", duration_s)
    report(0.11, f"已切分为 {len(chunks)} 段，将逐段转写…")
    return chunks


def _library_topic(minutes: str, content_type: str, fallback: str) -> str:
    keywords = ("课程主题", "课程名称", "课题") if content_type == "course" else ("会议主题", "议题")
    topic = extract_section(minutes, keywords) or extract_section(minutes, ("主题",))
    topic = (topic or fallback).strip()
    return topic[:120] or fallback


def run_pipeline(
    input_path: str | Path,
    hotwords: str = "",
    speaker_map_text: str = "",
    model: str = config.DEFAULT_LLM,
    asr_device: str = config.ASR_DEVICE,
    content_type: str = "auto",
    progress: ProgressFn | None = None,
    lock_wait: bool = True,
) -> JobResult:
    def report_wait() -> None:
        if progress:
            progress(0.01, "本机算力正被另一个任务占用，等待中…")

    with processing_lock(blocking=lock_wait, on_wait=report_wait):
        return _run_pipeline(
            input_path,
            hotwords=hotwords,
            speaker_map_text=speaker_map_text,
            model=model,
            asr_device=asr_device,
            content_type=content_type,
            progress=progress,
        )


def _run_pipeline(
    input_path: str | Path,
    hotwords: str = "",
    speaker_map_text: str = "",
    model: str = config.DEFAULT_LLM,
    asr_device: str = config.ASR_DEVICE,
    content_type: str = "auto",
    progress: ProgressFn | None = None,
) -> JobResult:
    def report(fraction: float, message: str) -> None:
        if progress:
            progress(max(0.0, min(1.0, fraction)), message)

    source = Path(input_path)
    if not source.is_file():
        raise PipelineError(f"找不到输入文件：{source}")

    requested_type = content_type if content_type in {"meeting", "course"} else "auto"
    started = time.time()
    job_id = f"{time.strftime('%Y%m%d_%H%M%S')}_{safe_stem(source.stem)}"
    work_dir = config.WORK_DIR / job_id
    suffix = 1
    while work_dir.exists():
        suffix += 1
        work_dir = config.WORK_DIR / f"{job_id}_{suffix}"
    job_id = work_dir.name
    work_dir.mkdir(parents=True, exist_ok=True)

    warnings: list[str] = []
    success = False
    wav_path = work_dir / "audio16k.wav"
    try:
        report(0.02, "读取音频信息…")
        duration_s = probe_duration(source)
        if duration_s > 7200:
            warnings.append(
                "音频超过 2 小时：说话人聚类在长音频上可能不稳定，建议按议程拆分后分别处理。"
            )

        report(0.06, "转换为 16kHz 单声道 WAV…")
        convert_to_wav(source, wav_path)

        report(0.12, "加载 FunASR 模型…")
        chunks: list[AudioChunk] | None = None
        if duration_s > config.ASR_CHUNK_THRESHOLD_S:
            chunks = _prepare_chunks(wav_path, duration_s, work_dir, report)
        try:
            segments, device, asr_chunks = _transcribe_in_worker(
                wav_path, hotwords, asr_device, work_dir, report, chunks
            )
        except TranscriptionError:
            retry_threshold = config.ASR_CHUNK_TARGET_S * 1.5
            if chunks is None and duration_s > retry_threshold:
                report(0.12, "整段转写未成功，改为分段重试…")
                chunks = _prepare_chunks(wav_path, duration_s, work_dir, report)
                if chunks is None:
                    raise
                segments, device, asr_chunks = _transcribe_in_worker(
                    wav_path, hotwords, asr_device, work_dir, report, chunks
                )
            else:
                raise
        if asr_chunks > 1:
            warnings.append(
                f"音频较长，已自动分为 {asr_chunks} 段转写；发言人编号按段独立，"
                "跨段同一说话人可能显示为不同编号。"
            )
        report(0.62, f"转写完成（{device}，{asr_chunks} 段）")

        mapping = parse_speaker_map(speaker_map_text)
        names = resolve_speaker_names(segments, mapping)

        resolved_type = requested_type
        if resolved_type == "auto":
            full_text = "\n".join(segment.text for segment in segments)
            resolved_type = detect_content_type(full_text)
        kind_label = type_label(resolved_type)

        result = JobResult(
            job_id=job_id,
            input_name=source.name,
            duration_s=round(duration_s, 2),
            asr_device=device,
            summary_model=model,
            summary_num_gpu=None,
            summary_chunks=1,
            elapsed_s=0.0,
            output_dir=str(work_dir),
            content_type=resolved_type,
            content_type_label=kind_label,
            asr_chunks=asr_chunks,
            warnings=warnings,
        )

        report(0.64, "写入转写稿…")
        transcript_md = work_dir / "transcript.md"
        transcript_txt = work_dir / "transcript.txt"
        transcript_srt = work_dir / "transcript.srt"
        transcript_json = work_dir / "transcript.json"

        _write(transcript_md, _transcript_markdown(result, segments, names))
        _write(
            transcript_txt,
            "\n".join(transcript_lines(segments, names)) + "\n",
        )
        _write(transcript_srt, _transcript_srt(segments, names))
        _write(
            transcript_json,
            json.dumps(
                {
                    "job_id": job_id,
                    "input": source.name,
                    "duration_s": result.duration_s,
                    "asr_device": device,
                    "content_type": resolved_type,
                    "speakers": names,
                    "segments": [segment.to_dict() for segment in segments],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )

        report(0.7, f"启动本地摘要模型（{kind_label}模式）…")
        summarizer = Summarizer(model, resolved_type)
        try:
            minutes, meta = summarizer.summarize(
                segments,
                names,
                progress=lambda fraction, message: report(
                    0.7 + 0.24 * fraction, message
                ),
            )
        finally:
            summarizer.unload()

        created_at = datetime.now().replace(microsecond=0)
        topic = _library_topic(minutes, resolved_type, source.stem)
        one_line = (
            extract_section(minutes, ("一句话摘要", "一句话概括"))
            or extract_section(minutes, ("摘要", "概括"))
        )[:240]

        report(0.95, "归档到资料库…")
        entry_dir = create_entry_dir(created_at, resolved_type, topic)
        for path in (transcript_md, transcript_txt, transcript_srt, transcript_json):
            shutil.move(str(path), str(entry_dir / path.name))

        minutes_path = entry_dir / "minutes.md"
        meta_path = entry_dir / "meta.json"
        kind_word = "笔记" if resolved_type == "course" else "纪要"
        review_hint = (
            "请对关键概念、公式和作业要求人工复核。"
            if resolved_type == "course"
            else "请对关键结论、负责人和期限人工复核。"
        )
        footer = (
            "\n\n---\n\n"
            f"> 本{kind_word}由本地模型自动生成（转写：FunASR SeACo-Paraformer-zh + cam++；"
            f"摘要：{meta.model}，num_gpu={meta.num_gpu}）。"
            f"{review_hint}\n"
        )
        _write(minutes_path, minutes.rstrip() + footer + "\n")

        result.summary_model = meta.model
        result.summary_num_gpu = meta.num_gpu
        result.summary_chunks = meta.chunks
        result.topic = topic
        result.summary = one_line
        result.created_at = created_at.isoformat(timespec="seconds")
        result.elapsed_s = round(time.time() - started, 1)
        result.output_dir = str(entry_dir)

        relative_files = {
            "minutes": minutes_path.name,
            "transcript_md": transcript_md.name,
            "transcript_txt": transcript_txt.name,
            "transcript_srt": transcript_srt.name,
            "transcript_json": transcript_json.name,
        }
        _write(
            meta_path,
            json.dumps(
                {
                    "job_id": job_id,
                    "created_at": result.created_at,
                    "type": resolved_type,
                    "type_label": kind_label,
                    "topic": topic,
                    "summary": one_line,
                    "source": source.name,
                    "duration_s": result.duration_s,
                    "segments": len(segments),
                    "asr_chunks": result.asr_chunks,
                    "asr_device": device,
                    "summary_model": meta.model,
                    "summary_num_gpu": meta.num_gpu,
                    "summary_chunks": meta.chunks,
                    "summary_elapsed_s": meta.elapsed_s,
                    "total_elapsed_s": result.elapsed_s,
                    "warnings": warnings,
                    "speakers": names,
                    "files": relative_files,
                    "tags": [kind_label],
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        rebuild_index()

        result.files = {
            "minutes": str(minutes_path),
            "transcript_md": str(entry_dir / transcript_md.name),
            "transcript_txt": str(entry_dir / transcript_txt.name),
            "transcript_srt": str(entry_dir / transcript_srt.name),
            "transcript_json": str(entry_dir / transcript_json.name),
            "job_json": str(meta_path),
        }
        success = True
        report(1.0, f"完成，已归档到资料库（{kind_label}）")
        return result
    finally:
        if success and os.environ.get("MEETING_KEEP_WAV") != "1":
            shutil.rmtree(work_dir, ignore_errors=True)


def result_to_dict(result: JobResult) -> dict:
    return asdict(result)
