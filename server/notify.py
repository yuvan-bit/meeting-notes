from __future__ import annotations

import threading
import time

_condition = threading.Condition()
_version = time.time_ns()


def current_version() -> int:
    with _condition:
        return _version


def bump() -> int:
    global _version
    with _condition:
        _version = max(time.time_ns(), _version + 1)
        _condition.notify_all()
        return _version


def wait_for_change(since: int, timeout: float) -> int:
    deadline = time.monotonic() + max(0.0, timeout)
    with _condition:
        while _version <= since:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            _condition.wait(remaining)
        return _version
