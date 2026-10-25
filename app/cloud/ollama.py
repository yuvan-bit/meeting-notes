from __future__ import annotations

import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

import httpx

logger = logging.getLogger("cloud_agent")

OLLAMA_TAGS_URL = "http://127.0.0.1:11434/api/tags"
KEEPALIVE_TASK = "OllamaKeepAlive"
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _reachable(timeout: float = 2.0) -> bool:
    try:
        response = httpx.get(OLLAMA_TAGS_URL, timeout=timeout)
        return response.is_success
    except httpx.HTTPError:
        return False


def _launch_candidates():
    if os.name == "nt":
        local = os.environ.get("LOCALAPPDATA", "")
        program_files = os.environ.get("ProgramFiles", "")
        if local:
            yield Path(local) / "Programs" / "Ollama" / "ollama app.exe", []
            yield Path(local) / "Programs" / "Ollama" / "ollama.exe", ["serve"]
        if program_files:
            yield Path(program_files) / "Ollama" / "ollama app.exe", []
            yield Path(program_files) / "Ollama" / "ollama.exe", ["serve"]
    executable = shutil.which("ollama")
    if executable:
        yield Path(executable), ["serve"]


def _start_windows(path: Path, args: list[str]) -> bool:
    # GUI 版 Ollama 需要通过 ShellExecute 启动；直接 Popen 在当前会话中会被守护进程丢弃。
    quoted = str(path).replace("'", "''")
    command = f"Start-Process -FilePath '{quoted}'"
    if args:
        command += " -ArgumentList " + ",".join(f"'{arg}'" for arg in args)
    command += " -WindowStyle Hidden"
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", command],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("启动 Ollama 失败：%s", exc)
        return False


def _wait_ready(seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if _reachable(1.0):
            return True
        time.sleep(1.0)
    return False


def _run_keepalive_task() -> bool:
    if os.name != "nt":
        return False
    try:
        query = subprocess.run(
            ["schtasks", "/query", "/tn", KEEPALIVE_TASK],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        if query.returncode != 0:
            return False
        subprocess.run(
            ["schtasks", "/run", "/tn", KEEPALIVE_TASK],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=15,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
        return True
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("调用 Ollama 保活任务失败：%s", exc)
        return False


def ensure_ollama(wait_seconds: float = 20.0) -> bool:
    """确保本机 Ollama 正在监听；不在时尝试拉起并等待就绪。"""
    if _reachable():
        return True

    if _run_keepalive_task():
        if _wait_ready(wait_seconds):
            logger.info("已通过计划任务启动 Ollama")
            return True
        logger.warning("Ollama 保活任务运行后仍未就绪")

    for path, args in _launch_candidates():
        if not path.is_file():
            continue
        if os.name == "nt":
            started = _start_windows(path, args)
        else:
            try:
                subprocess.Popen(
                    [str(path), *args],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    start_new_session=True,
                    close_fds=True,
                )
                started = True
            except OSError as exc:
                logger.warning("启动 Ollama 失败：%s", exc)
                started = False
        if not started:
            continue
        logger.info("已启动 Ollama：%s", path.name)
        if _wait_ready(wait_seconds):
            logger.info("Ollama 已就绪")
            return True
        logger.warning("Ollama 启动后仍未就绪：%s", path.name)

    logger.warning("Ollama 未运行且无法自动拉起")
    return False
