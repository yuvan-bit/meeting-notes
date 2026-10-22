from __future__ import annotations

import os
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from . import config

LOCK_PATH = config.WORK_DIR / ".processing.lock"


class ProcessingBusy(RuntimeError):
    pass


if os.name == "nt":
    import msvcrt

    def _try_lock(handle) -> bool:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(handle) -> None:
        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass

else:
    import fcntl

    def _try_lock(handle) -> bool:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(handle) -> None:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


def _open_lock_file(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = open(path, "a+b")
    if handle.seek(0, os.SEEK_END) == 0:
        handle.write(b"\n")
        handle.flush()
    return handle


def _write_owner(handle) -> None:
    payload = f"{os.getpid()} {time.strftime('%Y-%m-%d %H:%M:%S')}".encode("utf-8")
    handle.seek(0)
    handle.write(payload.ljust(64)[:64])
    handle.flush()


@contextmanager
def processing_lock(
    blocking: bool = True,
    on_wait: Callable[[], None] | None = None,
    poll_interval: float = 1.0,
) -> Iterator[None]:
    handle = _open_lock_file(LOCK_PATH)
    waited = False
    try:
        while not _try_lock(handle):
            if not blocking:
                raise ProcessingBusy("本机已有转写任务在运行")
            if not waited:
                waited = True
                if on_wait is not None:
                    on_wait()
            time.sleep(poll_interval)
            if on_wait is not None:
                on_wait()
        try:
            _write_owner(handle)
            yield
        finally:
            _unlock(handle)
    finally:
        handle.close()


def is_processing() -> bool:
    try:
        with processing_lock(blocking=False):
            return False
    except ProcessingBusy:
        return True


@contextmanager
def single_instance(path: Path) -> Iterator[bool]:
    handle = _open_lock_file(path)
    acquired = _try_lock(handle)
    try:
        yield acquired
    finally:
        if acquired:
            _unlock(handle)
        handle.close()
