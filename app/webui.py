from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path

import gradio as gr

from . import config
from .audio import format_ts
from .health import run_checks
from .library import (
    entry_file_paths,
    entry_label,
    entry_path,
    filter_entries,
    list_entries,
    read_text_file,
    rebuild_index,
)
from .pipeline import JobResult, run_pipeline

AUDIO_VIDEO_TYPES = [
    ".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma", ".amr",
    ".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".3gp",
]

DOWNLOAD_ORDER = [
    ("纪要 / 笔记", "minutes"),
    ("转写稿 MD", "transcript_md"),
    ("逐字稿 TXT", "transcript_txt"),
    ("字幕 SRT", "transcript_srt"),
    ("转写 JSON", "transcript_json"),
    ("任务信息", "job_json"),
]

CONTENT_TYPES = [
    ("自动识别", "auto"),
    ("会议", "meeting"),
    ("课程", "course"),
]

TEXT_SUFFIXES = {".md", ".txt", ".json", ".srt", ".csv", ".log"}


def _status_markdown(result: JobResult) -> str:
    lines = [
        "### 处理完成，已归档到资料库",
        "",
        f"- 分类：{result.content_type_label}",
        f"- 主题：{result.topic or '未命名'}",
        f"- 任务：`{result.job_id}`",
        f"- 音频时长：{format_ts(result.duration_s * 1000)}",
        f"- 转写设备：`{result.asr_device}`",
        f"- 摘要模型：`{result.summary_model}`（num_gpu={result.summary_num_gpu}，"
        f"分段 {result.summary_chunks}）",
        f"- 总耗时：{result.elapsed_s}s",
        f"- 资料库目录：`{result.output_dir}`",
    ]
    if result.warnings:
        lines.extend(["", "**注意**："])
        lines.extend(f"- {warning}" for warning in result.warnings)
    return "\n".join(lines)


def _entry_choices(entries: list[dict]) -> list[tuple[str, str]]:
    return [
        (entry_label(entry), str(entry.get("job_id", "")))
        for entry in entries
        if entry.get("job_id")
    ]


def _find_entry(job_id: str | None) -> dict | None:
    if not job_id:
        return None
    for entry in list_entries():
        if str(entry.get("job_id")) == str(job_id):
            return entry
    return None


def _library_overview(entries: list[dict]) -> str:
    meetings = sum(1 for item in entries if item.get("type") == "meeting")
    courses = sum(1 for item in entries if item.get("type") == "course")
    lines = [
        "### 资料库",
        "",
        f"共 {len(entries)} 条记录（会议 {meetings}｜课程 {courses}）。",
    ]
    if entries:
        lines.extend(["", "最近归档："])
        for entry in entries[:12]:
            lines.append(f"- {entry_label(entry)}")
        if len(entries) > 12:
            lines.append(f"- ……另有 {len(entries) - 12} 条，可用搜索缩小范围。")
    else:
        lines.extend(["", "暂无记录。完成一次转写后会自动按时间、类型和主题归档。"])
    return "\n".join(lines)


def refresh_library(type_filter: str, search: str):
    entries = filter_entries(rebuild_index(), type_filter or "全部", search or "")
    choices = _entry_choices(entries)
    return (
        gr.update(choices=choices, value=None),
        _library_overview(entries),
        "在下方选择一条记录查看纪要 / 笔记。",
        "",
        None,
    )


def show_library_entry(job_id: str | None):
    entry = _find_entry(job_id)
    if entry is None:
        return "请选择一条资料库记录。", "", None, ""
    root = entry_path(entry)
    files = entry.get("files") or {}
    minutes_text = read_text_file(root / files.get("minutes", "minutes.md"), 200_000)
    transcript_path = root / files.get("transcript_txt", "transcript.txt")
    transcript_text = (
        read_text_file(transcript_path, 400_000)
        if transcript_path.is_file()
        else "（没有逐字稿文件）"
    )
    detail = (
        f"**{entry_label(entry)}**\n\n"
        f"- 来源：{entry.get('source', '未知')}\n"
        f"- 时长：{format_ts(float(entry.get('duration_s') or 0) * 1000)}\n"
        f"- 说话人：{'、'.join((entry.get('speakers') or {}).values()) or '未识别'}\n"
        f"- 路径：`{root}`"
    )
    return minutes_text, transcript_text, entry_file_paths(entry), detail


def open_entry_folder(job_id: str | None) -> str:
    entry = _find_entry(job_id)
    if entry is None:
        return "请先选择一条记录。"
    target = entry_path(entry)
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(target))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            subprocess.Popen(["xdg-open", str(target)])
    except Exception as exc:
        return f"打开文件夹失败：{exc}\n\n路径：`{target}`"
    return f"已在资源管理器中打开：`{target}`"


def preview_explorer(selected) -> str:
    if not selected:
        return "在文件树中选择一个或多个文件，即可在这里预览。"
    if isinstance(selected, str):
        selected = [selected]
    blocks: list[str] = []
    for item in list(selected)[:5]:
        raw = Path(str(item))
        path = raw if raw.is_absolute() else config.LIBRARY_DIR / raw
        if not path.is_file():
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            content = read_text_file(path, 20_000)
            blocks.append(f"### {path.name}\n\n{content}")
        else:
            size_kb = path.stat().st_size / 1024
            blocks.append(f"### {path.name}\n\n非文本文件，{size_kb:.1f} KB。")
    return "\n\n---\n\n".join(blocks) or "没有可预览的文件。"


def process(
    file_path: str | None,
    hotwords: str,
    speaker_map: str,
    model: str,
    content_type: str,
    progress=gr.Progress(),
):
    if not file_path:
        yield "请先上传会议录音、课程录音或视频文件。", "", "", None
        return

    yield "开始处理，正在准备音频…", "", "", None
    try:
        def on_progress(fraction: float, message: str) -> None:
            progress(fraction, desc=message)

        result = run_pipeline(
            file_path,
            hotwords=hotwords or "",
            speaker_map_text=speaker_map or "",
            model=model or config.DEFAULT_LLM,
            content_type=content_type or "auto",
            progress=on_progress,
        )
        minutes = Path(result.files["minutes"]).read_text(encoding="utf-8")
        transcript = Path(result.files["transcript_txt"]).read_text(encoding="utf-8")
        downloads = [
            result.files[key] for _, key in DOWNLOAD_ORDER if key in result.files
        ]
        yield _status_markdown(result), minutes, transcript, downloads
    except Exception as exc:
        traceback.print_exc()
        yield f"### 处理失败\n\n```\n{exc}\n```", "", "", None


def build_demo() -> gr.Blocks:
    initial_entries = filter_entries(rebuild_index(), "全部", "")
    with gr.Blocks(title="本地会议与课程纪要工作台") as demo:
        gr.Markdown(
            "# 本地会议与课程纪要工作台\n"
            "音频、转写和纪要全部留在本机。FunASR 负责中文转写与说话人分离，"
            "Ollama 上的 Qwen3.5 负责生成会议纪要或课程笔记。\n\n"
            "- 处理完成后自动按 **时间 / 类型 / 主题** 归档到内置资料库，可直接在下方浏览。\n"
            "- 支持常见音频和视频文件；线上会议建议优先使用平台云录制导出后上传。\n"
            "- 8GB 显存下 ASR 与 9B 摘要模型串行使用；显存不足会自动降级到部分卸载或 CPU。"
        )

        with gr.Row():
            file_input = gr.File(
                label="会议 / 课程录音或视频",
                file_types=AUDIO_VIDEO_TYPES,
                file_count="single",
                type="filepath",
                scale=3,
            )
            with gr.Column(scale=1):
                type_input = gr.Dropdown(
                    label="内容类型",
                    choices=CONTENT_TYPES,
                    value="auto",
                    info="自动识别依据转写内容中的关键词，识别不准时可手动指定。",
                )
                model_input = gr.Dropdown(
                    label="摘要模型",
                    choices=[config.DEFAULT_LLM, config.FAST_LLM],
                    value=config.DEFAULT_LLM,
                    info="9B 质量更好；4B 更快，显存紧张时会自动降级。",
                )

        with gr.Row():
            hotwords_input = gr.Textbox(
                label="热词（可选）",
                placeholder="产品名 人名 项目代号 课程术语，用空格分隔",
                scale=1,
            )
            speakers_input = gr.Textbox(
                label="发言人映射（可选）",
                placeholder="0=张三,1=李四",
                scale=1,
            )

        with gr.Row():
            run_button = gr.Button("开始转写并生成纪要 / 笔记", variant="primary", scale=2)
            check_button = gr.Button("环境自检", scale=1)

        status_output = gr.Markdown("等待上传文件。")

        with gr.Tabs():
            with gr.Tab("纪要 / 笔记"):
                minutes_output = gr.Markdown()
            with gr.Tab("逐字稿"):
                transcript_output = gr.Textbox(
                    label="逐字稿（带时间戳和发言人）",
                    lines=22,
                    max_lines=32,
                )
            with gr.Tab("下载文件"):
                files_output = gr.File(label="输出文件", file_count="multiple")
            with gr.Tab("资料库"):
                with gr.Row():
                    type_filter = gr.Dropdown(
                        label="筛选类型",
                        choices=["全部", "会议", "课程"],
                        value="全部",
                        scale=1,
                    )
                    search_input = gr.Textbox(
                        label="搜索",
                        placeholder="主题、摘要、来源或标签",
                        scale=2,
                    )
                    refresh_button = gr.Button("刷新", scale=1)
                library_overview = gr.Markdown(_library_overview(initial_entries))
                library_select = gr.Dropdown(
                    label="选择记录",
                    choices=_entry_choices(initial_entries),
                    value=None,
                    filterable=True,
                )
                with gr.Row():
                    open_button = gr.Button("打开所在文件夹", size="sm")
                    library_status = gr.Markdown("选择一条记录可预览内容。")
                with gr.Tabs():
                    with gr.Tab("纪要 / 笔记"):
                        library_minutes = gr.Markdown()
                    with gr.Tab("逐字稿"):
                        library_transcript = gr.Textbox(lines=20, max_lines=32)
                    with gr.Tab("文件"):
                        library_files = gr.File(label="条目文件", file_count="multiple")
                with gr.Accordion("资料库文件树", open=False):
                    library_explorer = gr.FileExplorer(
                        root_dir=str(config.LIBRARY_DIR),
                        glob="**/*",
                        file_count="multiple",
                        label="data/library",
                        height=320,
                    )
                    explorer_preview = gr.Markdown()
            with gr.Tab("环境自检"):
                env_output = gr.Markdown()

        run_button.click(
            process,
            inputs=[
                file_input,
                hotwords_input,
                speakers_input,
                model_input,
                type_input,
            ],
            outputs=[status_output, minutes_output, transcript_output, files_output],
        ).then(
            refresh_library,
            inputs=[type_filter, search_input],
            outputs=[
                library_select,
                library_overview,
                library_minutes,
                library_transcript,
                library_files,
            ],
        )
        check_button.click(run_checks, inputs=None, outputs=env_output)

        refresh_button.click(
            refresh_library,
            inputs=[type_filter, search_input],
            outputs=[
                library_select,
                library_overview,
                library_minutes,
                library_transcript,
                library_files,
            ],
        )
        type_filter.change(
            refresh_library,
            inputs=[type_filter, search_input],
            outputs=[
                library_select,
                library_overview,
                library_minutes,
                library_transcript,
                library_files,
            ],
        )
        search_input.submit(
            refresh_library,
            inputs=[type_filter, search_input],
            outputs=[
                library_select,
                library_overview,
                library_minutes,
                library_transcript,
                library_files,
            ],
        )
        library_select.change(
            show_library_entry,
            inputs=library_select,
            outputs=[
                library_minutes,
                library_transcript,
                library_files,
                library_status,
            ],
        )
        open_button.click(
            open_entry_folder,
            inputs=library_select,
            outputs=library_status,
        )
        library_explorer.change(
            preview_explorer,
            inputs=library_explorer,
            outputs=explorer_preview,
        )

        gr.Markdown(
            "> 提示：说话人编号来自声纹聚类，跨会议不可比。"
            "重要结论、负责人、期限、公式和作业要求请人工复核。"
        )
    return demo


def main() -> None:
    demo = build_demo()
    demo.queue()
    requested = os.environ.get("MEETING_UI_PORT", "").strip()
    ports = (
        [int(requested)]
        if requested.isdigit()
        else list(range(7860, 7871))
    )
    last_error: Exception | None = None
    icon = config.BASE_DIR / "assets" / "app_icon.png"
    for port in ports:
        try:
            demo.launch(
                server_name="127.0.0.1",
                server_port=port,
                allowed_paths=[str(config.DATA_DIR)],
                show_error=True,
                inbrowser=False,
                footer_links=[],
                favicon_path=str(icon) if icon.is_file() else None,
            )
            return
        except OSError as exc:
            last_error = exc
            continue
    raise RuntimeError(f"无法启动 Web UI：{last_error}")


if __name__ == "__main__":
    main()
