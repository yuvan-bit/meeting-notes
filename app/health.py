from __future__ import annotations

import importlib.metadata
import shutil
import subprocess
import sys
from pathlib import Path

from . import config
from .summarizer import check_ollama
from .transcriber import gpu_info


def _version(package: str) -> str:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return "未安装"


def _line(name: str, ok: bool, detail: str) -> str:
    return f"- [{'OK' if ok else 'FAIL'}] **{name}**：{detail}"


def run_checks() -> str:
    lines = ["## 环境自检", ""]
    lines.append(_line("Python", sys.version_info >= (3, 10), sys.version.split()[0]))

    try:
        import torch

        gpu = gpu_info()
        if gpu.get("available"):
            detail = (
                f"torch {torch.__version__}，CUDA {torch.version.cuda}，"
                f"{gpu['name']}，空闲 {gpu['free_gb']} / {gpu['total_gb']} GB"
            )
            lines.append(_line("PyTorch / GPU", True, detail))
        else:
            lines.append(
                _line("PyTorch / GPU", True, f"torch {torch.__version__}，未检测到可用 CUDA")
            )
    except Exception as exc:
        lines.append(_line("PyTorch / GPU", False, str(exc)))

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        try:
            output = subprocess.run(
                ["ffmpeg", "-version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=10,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            ).stdout.decode("utf-8", errors="replace")
            first_line = output.splitlines()[0] if output else "已安装"
            lines.append(_line("ffmpeg", True, first_line))
        except Exception as exc:
            lines.append(_line("ffmpeg", False, str(exc)))
    else:
        lines.append(_line("ffmpeg", False, "未找到，请安装并加入 PATH"))

    for package in ("funasr", "modelscope", "gradio", "requests"):
        version = _version(package)
        lines.append(_line(package, version != "未安装", version))

    ok, models, message = check_ollama()
    if ok:
        lines.append(
            _line("Ollama", True, f"`{config.OLLAMA_URL}`，模型：{', '.join(models) or '无'}")
        )
        for required in (config.DEFAULT_LLM, config.FAST_LLM):
            found = required in models
            lines.append(_line(f"摘要模型 {required}", found, "已安装" if found else "未安装"))
    else:
        lines.append(_line("Ollama", False, message))

    usage = shutil.disk_usage(config.BASE_DIR)
    free_gb = usage.free / 1024**3
    lines.append(_line("磁盘", free_gb >= 10, f"剩余 {free_gb:.1f} GB"))

    lines.append("")
    lines.append(f"模型缓存目录：`{config.MODEL_DIR}`")
    lines.append(f"输出目录：`{config.OUTPUT_DIR}`")
    return "\n".join(lines)
