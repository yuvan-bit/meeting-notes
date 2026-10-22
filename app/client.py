from __future__ import annotations

import argparse
import ctypes
import html
import os
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import requests

from . import config

LOG_DIR = config.DATA_DIR / "logs"
CLIENT_LOG = LOG_DIR / "client.log"
WEBUI_LOG = LOG_DIR / "webui.log"
ICON_PATH = config.BASE_DIR / "assets" / "app.ico"
TRAY_MUTEX = "MeetingNotes.Local.Tray.Mutex"
WINDOW_MUTEX = "MeetingNotes.Local.Window.Mutex"
AGENT_TASK_NAME = "MeetingNotesCloudAgent"

# WebView2 默认会为更新、翻译、购物等组件常驻额外进程；本机界面用不到。
WEBVIEW2_ARGS = (
    "--disable-background-networking "
    "--disable-component-update "
    "--disable-sync "
    "--no-first-run "
    "--disable-features=msEdgeSidebarV2,msEdgeCollections,msEdgeShoppingAssistant,"
    "msEdgeReadAloud,msEdgeAutofill,msEdgeWebCapture,msEdgeTranslate "
    "--js-flags=--max-old-space-size=192"
)

if sys.platform.startswith("win"):
    _KERNEL32 = ctypes.windll.kernel32
    _KERNEL32.CreateMutexW.restype = ctypes.c_void_p
    _KERNEL32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    _KERNEL32.CloseHandle.argtypes = [ctypes.c_void_p]

SPLASH_HTML = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
  html, body { margin: 0; height: 100%; background: #0f172a; color: #e2e8f0;
    font-family: "Microsoft YaHei UI", "Segoe UI", sans-serif; }
  .wrap { height: 100%; display: flex; flex-direction: column;
    align-items: center; justify-content: center; gap: 18px; }
  .mark { width: 58px; height: 58px; border-radius: 16px;
    background: linear-gradient(135deg, #38bdf8, #6366f1);
    display: flex; align-items: center; justify-content: center;
    font-size: 28px; font-weight: 700; color: #0b1220; }
  h1 { font-size: 22px; font-weight: 600; margin: 0; letter-spacing: 1px; }
  p { margin: 0; color: #94a3b8; font-size: 13px; }
  .bar { width: 220px; height: 3px; border-radius: 999px; overflow: hidden;
    background: #1e293b; }
  .bar span { display: block; width: 40%; height: 100%; border-radius: 999px;
    background: linear-gradient(90deg, #38bdf8, #818cf8);
    animation: slide 1.2s ease-in-out infinite; }
  @keyframes slide { 0% { transform: translateX(-100%); }
    100% { transform: translateX(260%); } }
</style>
</head>
<body>
  <div class="wrap">
    <div class="mark">录</div>
    <h1>会议记录 · 本地纪要工作台</h1>
    <p>正在启动本地服务并检查模型环境…</p>
    <div class="bar"><span></span></div>
  </div>
</body>
</html>"""


def _log(message: str) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] [{os.getpid()}] {message}"
    try:
        with CLIENT_LOG.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
    except OSError:
        pass
    try:
        print(line, flush=True)
    except Exception:
        pass


def _notify(message: str, title: str = "会议记录客户端") -> None:
    _log(message)
    try:
        ctypes.windll.user32.MessageBoxW(None, message, title, 0x40)
    except Exception:
        pass


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _tail(path: Path, limit: int = 4000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return text[-limit:]


def _wait_for_ui(port: int, process: subprocess.Popen, timeout: float = 180) -> str:
    url = f"http://127.0.0.1:{port}/"
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            detail = _tail(WEBUI_LOG)
            raise RuntimeError(
                f"本地服务进程已退出（代码 {process.returncode}）。\n{detail}"
            )
        try:
            response = requests.get(url, timeout=2)
            if response.status_code == 200:
                return url
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise TimeoutError(f"本地服务启动超时（{timeout:.0f} 秒）。\n{_tail(WEBUI_LOG)}")


def _stop_process(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    _log(f"正在关闭本地服务（PID {process.pid}）…")
    if sys.platform.startswith("win"):
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    else:
        process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()


def _start_server(port: int) -> subprocess.Popen:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["MEETING_UI_PORT"] = str(port)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    log_handle = WEBUI_LOG.open("w", encoding="utf-8")
    _log(f"启动本地服务：端口 {port}")
    process = subprocess.Popen(
        [sys.executable, "-m", "app.webui"],
        cwd=str(config.BASE_DIR),
        env=env,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    process._log_handle = log_handle  # type: ignore[attr-defined]
    return process


def _agent_task_installed() -> bool:
    # 直接看任务定义文件，避免 schtasks/PowerShell 在无控制台进程里查询失败。
    system_root = os.environ.get("SystemRoot", "C:/Windows")
    return (Path(system_root) / "System32" / "Tasks" / AGENT_TASK_NAME).is_file()


def _spawn_cloud_agent(*args: str) -> bool:
    pythonw = config.BASE_DIR / ".venv" / "Scripts" / "pythonw.exe"
    executable = str(pythonw) if pythonw.is_file() else sys.executable
    creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NO_WINDOW", 0
    )
    try:
        subprocess.Popen(
            [executable, "-m", "app.cloud_agent", *args],
            cwd=str(config.BASE_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
            close_fds=True,
        )
        return True
    except Exception as exc:
        _log(f"启动云代理失败：{exc}")
        return False


def _kick_cloud_agent() -> None:
    try:
        from .cloud.store import load_agent

        if load_agent() is None:
            _log("尚未配对云代理，跳过云端检查")
            return
    except Exception as exc:
        _log(f"读取云配对信息失败：{exc}")
        return

    if _agent_task_installed():
        _spawn_cloud_agent("run", "--once")
        _log("已触发一次云端检查（计划任务每 2 分钟自动运行）")
    else:
        _spawn_cloud_agent("run")
        _log("未安装计划任务，已启动常驻云代理；建议运行 tools\\install_agent_task.ps1")


def _run_window(url: str, port: int, process: subprocess.Popen) -> None:
    # 必须在创建 WebView2 之前设置，否则不会生效。
    os.environ.setdefault("WEBVIEW2_ADDITIONAL_BROWSER_ARGUMENTS", WEBVIEW2_ARGS)
    import webview

    window = webview.create_window(
        "会议记录 · 本地纪要工作台",
        html=SPLASH_HTML,
        width=1360,
        height=900,
        min_size=(1040, 720),
        background_color="#0f172a",
    )

    def boot() -> None:
        try:
            _log(f"等待本地服务就绪：{url}")
            _wait_for_ui(port, process)
            _log("本地服务已就绪，加载工作台")
            window.load_url(url)
        except Exception as exc:
            _log(f"工作台启动失败：{exc}")
            window.load_html(
                "<html><body style='background:#0f172a;color:#e2e8f0;"
                "font-family:Microsoft YaHei UI;padding:48px'>"
                "<h2>启动失败</h2><pre style='white-space:pre-wrap;color:#fca5a5'>"
                f"{html.escape(str(exc))}</pre><p style='color:#94a3b8'>详细日志："
                f"{html.escape(str(CLIENT_LOG))}</p></body></html>"
            )

    webview.start(
        boot,
        icon=str(ICON_PATH) if ICON_PATH.is_file() else None,
    )
    _log("窗口已关闭")


def _chromium_executable() -> tuple[str, str] | None:
    candidates = [
        (
            "Edge",
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
            / "Microsoft"
            / "Edge"
            / "Application"
            / "msedge.exe",
        ),
        (
            "Edge",
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "Microsoft"
            / "Edge"
            / "Application"
            / "msedge.exe",
        ),
        (
            "Chrome",
            Path(os.environ.get("ProgramFiles", "C:/Program Files"))
            / "Google"
            / "Chrome"
            / "Application"
            / "chrome.exe",
        ),
        (
            "Chrome",
            Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)"))
            / "Google"
            / "Chrome"
            / "Application"
            / "chrome.exe",
        ),
    ]
    for name, path in candidates:
        if path.is_file():
            return name, str(path)
    return None


def _run_app_window(url: str) -> bool:
    # Edge/Chrome 的 --app 模式没有地址栏，窗口关闭后浏览器进程会退出，
    # 可以可靠地停止本地 WebUI；比 pywebview 的 pythonnet 依赖更稳。
    found = _chromium_executable()
    if found is None:
        return False
    name, executable = found
    profile = config.DATA_DIR / f"{name.lower()}-app-profile"
    profile.mkdir(parents=True, exist_ok=True)
    args = [
        executable,
        f"--app={url}",
        f"--user-data-dir={profile}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-background-mode",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-extensions",
        "--disable-sync",
        "--hide-crash-restore-bubble",
        "--disable-features=Translate,msEdgeTranslate,msEdgeSidebarV2,"
        "msEdgeCollections,msEdgeShoppingAssistant,msEdgeReadAloud,msEdgeAutofill,"
        "msEdgeWebCapture",
        "--js-flags=--max-old-space-size=192",
        "--disk-cache-size=52428800",
        "--window-size=1360,900",
    ]
    try:
        process = subprocess.Popen(
            args,
            cwd=str(config.BASE_DIR),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        _log(f"启动{name}应用窗口失败：{exc}")
        return False
    _log(f"已打开{name}应用窗口：{url}")
    process.wait()
    _log("应用窗口已关闭")
    return True


def _run_browser(url: str, port: int, process: subprocess.Popen) -> None:
    try:
        _wait_for_ui(port, process)
        _notify(
            "未启用桌面窗口（缺少 pywebview 或 WebView2 运行时），"
            f"已改用系统浏览器打开：\n{url}\n\n关闭此提示后请保留后台服务，"
            "需要退出时关闭本窗口或结束 python 进程。"
        )
        webbrowser.open(url)
        process.wait()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        _notify(f"启动失败：{exc}\n\n日志：{CLIENT_LOG}")
        _log(str(exc))


def _mutex_handle(name: str):
    handle = _KERNEL32.CreateMutexW(None, False, name)
    if _KERNEL32.GetLastError() == 183:
        if handle:
            _KERNEL32.CloseHandle(handle)
        return None
    return handle


def _mutex_active(name: str) -> bool:
    handle = _KERNEL32.CreateMutexW(None, False, name)
    exists = _KERNEL32.GetLastError() == 183
    if handle:
        _KERNEL32.CloseHandle(handle)
    return exists


def _open_folder(path: Path) -> None:
    try:
        if sys.platform.startswith("win"):
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        _log(f"打开文件夹失败：{exc}")


def _window_main() -> int:
    if sys.platform.startswith("win") and _mutex_handle(WINDOW_MUTEX) is None:
        _notify("会议记录工作台已经在运行。")
        return 0
    _log("=" * 60)
    _log("打开工作台窗口")
    port = _free_port()
    process = _start_server(port)
    url = f"http://127.0.0.1:{port}/"
    try:
        try:
            import webview  # noqa: F401
            desktop = True
        except Exception as exc:
            _log(f"pywebview 不可用：{exc}")
            desktop = False

        if desktop:
            try:
                _run_window(url, port, process)
                return 0
            except Exception as exc:
                _log(f"原生桌面窗口不可用，改用应用窗口：{exc}")
        if _run_app_window(url):
            return 0
        _run_browser(url, port, process)
        return 0
    finally:
        _stop_process(process)
        log_handle = getattr(process, "_log_handle", None)
        if log_handle is not None:
            try:
                log_handle.close()
            except Exception:
                pass
        _log("工作台窗口已关闭，界面内存已释放")


def _tray_main(auto_open: bool = True) -> int:
    try:
        import pystray
        from PIL import Image

        if sys.platform.startswith("win"):
            # pystray 在部分 Windows 11 版本上调用 ChangeWindowMessageFilterEx
            # 会被拒绝，导致托盘消息循环无法建立；非提权进程不需要该调用。
            import pystray._win32 as pystray_win32

            pystray_win32.win32.ChangeWindowMessageFilterEx = (
                lambda *args, **kwargs: True
            )
    except Exception as exc:
        _log(f"托盘组件不可用（{exc}），直接打开窗口")
        return _window_main()

    if sys.platform.startswith("win"):
        if _mutex_handle(TRAY_MUTEX) is None:
            _log("客户端已在托盘中运行，改为打开工作台窗口")
            return _window_main()

    _log("=" * 60)
    _log("会议记录客户端启动（托盘模式）")
    _kick_cloud_agent()

    pythonw = config.BASE_DIR / ".venv" / "Scripts" / "pythonw.exe"
    executable = str(pythonw) if pythonw.is_file() else sys.executable
    creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
        subprocess, "CREATE_NO_WINDOW", 0
    )
    child: dict[str, subprocess.Popen | None] = {"process": None}
    child_lock = threading.Lock()

    def open_workbench(icon=None, item=None) -> None:
        with child_lock:
            running = child["process"]
            if running is not None and running.poll() is None:
                return
            if sys.platform.startswith("win") and _mutex_active(WINDOW_MUTEX):
                if icon is not None:
                    try:
                        icon.notify("工作台窗口已经在运行。", "会议记录")
                    except Exception:
                        pass
                return
            _log("从托盘打开工作台")
            try:
                child["process"] = subprocess.Popen(
                    [executable, "-m", "app.client", "--window"],
                    cwd=str(config.BASE_DIR),
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=creationflags,
                    close_fds=True,
                )
            except Exception as exc:
                _log(f"打开工作台失败：{exc}")

    def quit_app(icon, item) -> None:
        with child_lock:
            running = child["process"]
            if running is not None and running.poll() is None:
                _stop_process(running)
        icon.stop()

    def menu_folder(path: Path):
        return lambda icon, item: _open_folder(path)

    try:
        image = Image.open(ICON_PATH)
        image.load()
        image = image.copy()
    except Exception:
        image = Image.new("RGBA", (64, 64), (56, 189, 248, 255))

    menu = pystray.Menu(
        pystray.MenuItem("打开工作台", open_workbench, default=True),
        pystray.MenuItem("打开资料库文件夹", menu_folder(config.LIBRARY_DIR)),
        pystray.MenuItem("打开日志文件夹", menu_folder(LOG_DIR)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("退出", quit_app),
    )
    icon = pystray.Icon("meeting-notes", image, "会议记录 · 本地纪要工作台", menu)
    if auto_open:
        open_workbench(icon)
    try:
        icon.run()
    except Exception as exc:
        _log(f"托盘启动失败：{exc}")
        os._exit(1)
    else:
        _log("托盘已退出")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.client")
    parser.add_argument(
        "--window",
        action="store_true",
        help="直接打开工作台窗口，关闭后退出（供托盘调用）",
    )
    parser.add_argument(
        "--no-tray",
        action="store_true",
        help="不使用托盘，关闭窗口即退出",
    )
    parser.add_argument(
        "--silent",
        action="store_true",
        help="托盘模式启动时不自动打开窗口",
    )
    args = parser.parse_args(argv)

    if sys.platform.startswith("win"):
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "MeetingNotes.Local.Client"
            )
        except Exception:
            pass

    if args.window or args.no_tray:
        return _window_main()
    return _tray_main(auto_open=not args.silent)


if __name__ == "__main__":
    raise SystemExit(main())
