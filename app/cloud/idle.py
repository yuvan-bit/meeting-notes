from __future__ import annotations

import ctypes
import os
import subprocess
import time
from dataclasses import dataclass, field

from ..locks import is_processing
from .config import AgentSettings

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


@dataclass
class IdleStatus:
    idle_seconds: float | None = None
    cpu_percent: float | None = None
    gpu_percent: float | None = None
    on_ac: bool | None = None
    processing: bool = False
    reasons: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return not self.reasons


if os.name == "nt":
    from ctypes import wintypes

    class _LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    class _SYSTEM_POWER_STATUS(ctypes.Structure):
        _fields_ = [
            ("ACLineStatus", wintypes.BYTE),
            ("BatteryFlag", wintypes.BYTE),
            ("BatteryLifePercent", wintypes.BYTE),
            ("Reserved1", wintypes.BYTE),
            ("BatteryLifeTime", wintypes.DWORD),
            ("BatteryFullLifeTime", wintypes.DWORD),
        ]

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    def _filetime_value(value: _FILETIME) -> int:
        return (value.dwHighDateTime << 32) | value.dwLowDateTime

    def _windows_idle_seconds() -> float | None:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        tick = ctypes.windll.kernel32.GetTickCount64() & 0xFFFFFFFF
        return ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0

    def _windows_cpu_percent(sample_seconds: float = 0.5) -> float | None:
        idle = _FILETIME()
        kernel = _FILETIME()
        user = _FILETIME()
        if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return None
        idle0 = _filetime_value(idle)
        total0 = _filetime_value(kernel) + _filetime_value(user)
        time.sleep(sample_seconds)
        if not ctypes.windll.kernel32.GetSystemTimes(
            ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)
        ):
            return None
        idle_delta = _filetime_value(idle) - idle0
        total_delta = _filetime_value(kernel) + _filetime_value(user) - total0
        if total_delta <= 0:
            return None
        return max(0.0, min(100.0, 100.0 * (total_delta - idle_delta) / total_delta))

    def _windows_on_ac() -> bool | None:
        status = _SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            return None
        if status.ACLineStatus == 0:
            return False
        if status.ACLineStatus == 1:
            return True
        return None

else:

    def _windows_idle_seconds() -> float | None:
        return None

    def _windows_cpu_percent(sample_seconds: float = 0.5) -> float | None:
        return None

    def _windows_on_ac() -> bool | None:
        return None


def _gpu_percent() -> float | None:
    try:
        proc = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu",
                "--format=csv,noheader,nounits",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    values = []
    for line in proc.stdout.splitlines():
        try:
            values.append(float(line.strip()))
        except ValueError:
            continue
    return max(values) if values else None


def evaluate_idle(settings: AgentSettings, force: bool = False) -> IdleStatus:
    status = IdleStatus(
        idle_seconds=_windows_idle_seconds(),
        cpu_percent=_windows_cpu_percent(),
        gpu_percent=_gpu_percent() if settings.gpu_max_util is not None else None,
        on_ac=_windows_on_ac(),
        processing=is_processing(),
    )
    if force:
        status.reasons.clear()
        return status

    if status.processing:
        status.reasons.append("本机正在处理其他转写任务")
    if status.idle_seconds is None:
        if os.environ.get("MEETING_AGENT_ASSUME_IDLE") == "1":
            status.idle_seconds = float(settings.idle_seconds)
        else:
            status.reasons.append("当前系统无法检测空闲时长")
    elif status.idle_seconds < settings.idle_seconds:
        status.reasons.append(
            f"用户仍在操作（已空闲 {int(status.idle_seconds)} 秒，"
            f"需 {settings.idle_seconds} 秒）"
        )
    if settings.require_ac and status.on_ac is False:
        status.reasons.append("设备正在使用电池")
    if (
        settings.cpu_max_percent is not None
        and status.cpu_percent is not None
        and status.cpu_percent > settings.cpu_max_percent
    ):
        status.reasons.append(f"CPU 占用 {status.cpu_percent:.0f}%")
    if (
        settings.gpu_max_util is not None
        and status.gpu_percent is not None
        and status.gpu_percent > settings.gpu_max_util
    ):
        status.reasons.append(f"GPU 占用 {status.gpu_percent:.0f}%")
    return status
