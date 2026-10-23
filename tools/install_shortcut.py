from __future__ import annotations

import base64
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
PYTHONW = BASE_DIR / ".venv" / "Scripts" / "pythonw.exe"
ICON = BASE_DIR / "assets" / "app.ico"
ICON_DIR = (
    Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    / "MeetingNotes"
)


def stable_icon() -> Path:
    # Explorer 无法解析含中文的快捷方式图标路径；按内容哈希放到纯英文目录，
    # 文件名随图标内容变化，避免覆盖正被资源管理器占用的旧文件。
    digest = hashlib.sha256(ICON.read_bytes()).hexdigest()[:12]
    target = ICON_DIR / f"app-{digest}.ico"
    if not target.is_file():
        ICON_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ICON, target)
    return target


def main() -> int:
    if not PYTHONW.is_file():
        print(f"找不到虚拟环境：{PYTHONW}")
        return 1
    if sys.platform != "win32":
        print("仅支持 Windows。")
        return 1
    base = str(BASE_DIR).replace("'", "''")
    target = str(PYTHONW).replace("'", "''")
    icon = str(stable_icon()).replace("'", "''")
    script = f"""
$desktop = [Environment]::GetFolderPath('Desktop')
$path = Join-Path $desktop '会议记录.lnk'
$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut($path)
$link.TargetPath = '{target}'
$link.Arguments = '-m app.client'
$link.WorkingDirectory = '{base}'
$link.IconLocation = '{icon},0'
$link.Description = '本地会议与课程纪要工作台'
$link.Save()
Write-Output $path
"""
    encoded = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    result = subprocess.run(
        ["powershell.exe", "-NoProfile", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        print(result.stderr.strip() or "创建快捷方式失败。")
        return 1
    print(f"已创建桌面快捷方式：{result.stdout.strip()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
