from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from logging.handlers import RotatingFileHandler

from . import config
from .cloud.config import AGENT_LOCK, CLOUD_DIR
from .cloud.store import AgentCredentials, load_agent
from .locks import single_instance

LOG_FILE = CLOUD_DIR / "notify.log"
WAIT_SECONDS = min(300, max(10, int(os.environ.get("MEETING_NOTIFY_WAIT", "300"))))
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
DETACHED_PROCESS = getattr(subprocess, "DETACHED_PROCESS", 0)

logger = logging.getLogger("notify_listener")


def setup_logging() -> None:
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=512 * 1024,
        backupCount=2,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)


def _spawn_agent() -> bool:
    pythonw = config.BASE_DIR / ".venv" / "Scripts" / "pythonw.exe"
    executable = str(pythonw) if pythonw.is_file() else sys.executable
    flags = CREATE_NO_WINDOW
    if os.name == "nt":
        flags |= DETACHED_PROCESS
    try:
        subprocess.Popen(
            [executable, "-m", "app.cloud_agent", "run", "--once"],
            cwd=str(config.BASE_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        logger.info("已触发一次云代理")
        return True
    except OSError as exc:
        logger.warning("触发云代理失败：%s", exc)
        return False


_pending = False


def trigger_agent() -> bool:
    global _pending
    with single_instance(AGENT_LOCK) as acquired:
        if not acquired:
            _pending = True
            logger.info("云代理正在运行，本次通知排队等待")
            return False
    _pending = False
    return _spawn_agent()


def _pending_worker() -> None:
    global _pending
    while True:
        time.sleep(15)
        if not _pending:
            continue
        with single_instance(AGENT_LOCK) as acquired:
            if not acquired:
                continue
        _pending = False
        _spawn_agent()


def _wait_notification(
    credentials: AgentCredentials, since: int, wait: int
) -> dict:
    url = (
        f"{credentials.server_url.rstrip('/')}/api/v1/agent/notifications"
        f"?since={since}&wait={wait}"
    )
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {credentials.token}"},
    )
    with urllib.request.urlopen(request, timeout=wait + 20) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    setup_logging()
    logger.info("通知监听启动：长连接等待，不轮询任务队列")
    with single_instance(CLOUD_DIR / "notify.lock") as acquired:
        if not acquired:
            logger.info("已有通知监听在运行，本次退出")
            return 2
        import threading

        threading.Thread(target=_pending_worker, daemon=True, name="notify-pending").start()
        since = 0
        while True:
            credentials = load_agent()
            if credentials is None:
                logger.info("尚未配对云代理，30 秒后重试")
                time.sleep(30)
                continue
            try:
                payload = _wait_notification(credentials, since, WAIT_SECONDS)
                version = int(payload.get("version") or since)
                changed = bool(payload.get("changed"))
                since = version
                if changed:
                    logger.info("收到服务器新音频通知：version=%s", version)
                    trigger_agent()
            except (urllib.error.URLError, OSError, ValueError) as exc:
                logger.warning("等待服务器通知失败：%s", exc)
                time.sleep(10)
            except Exception:
                logger.exception("通知监听异常")
                time.sleep(10)


if __name__ == "__main__":
    raise SystemExit(main())
