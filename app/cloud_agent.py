from __future__ import annotations

import argparse
import logging
import socket
import sys
import time
from dataclasses import replace
from logging.handlers import RotatingFileHandler

from .cloud.agent import CloudAgent, cleanup_inbox, collect_status
from .cloud.client import CloudClient, CloudError
from .cloud.importer import LocalImportError, push_entry, resolve_entry
from .cloud.config import (
    AGENT_FILE,
    AGENT_LOCK,
    LOG_FILE,
    OUTBOX_DIR,
    AgentSettings,
    mask_token,
    resolve_server_url,
)
from .cloud.store import build_credentials, clear_agent, load_agent, save_agent
from .locks import single_instance

logger = logging.getLogger("cloud_agent")


def setup_logging(verbose: bool = False) -> None:
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False
    if logger.handlers:
        return
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    logger.addHandler(console)
    try:
        file_handler = RotatingFileHandler(
            LOG_FILE, maxBytes=2 * 1024 * 1024, backupCount=3, encoding="utf-8"
        )
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    except OSError:
        pass


def _human_bytes(value: int | float) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def _load_or_exit():
    try:
        credentials = load_agent()
    except Exception as exc:
        print(f"读取配对信息失败：{exc}")
        raise SystemExit(2)
    if credentials is None:
        print("尚未配对。请先在服务器上生成 PC 配对码，然后运行：")
        print("  python -m app.cloud_agent pair --url http://<服务器地址>:8000 --code <配对码>")
        raise SystemExit(2)
    return credentials


def cmd_pair(args: argparse.Namespace) -> int:
    server_url = resolve_server_url(args.url)
    if not server_url:
        print("缺少服务器地址：请用 --url 指定，或设置 MEETING_CLOUD_URL")
        return 2
    name = (args.name or socket.gethostname()).strip()
    with CloudClient(server_url) as client:
        try:
            response = client.pair(args.code, name)
        except CloudError as exc:
            print(f"配对失败：{exc}")
            return 1
    credentials = build_credentials(
        server_url=server_url,
        device_id=str(response["device_id"]),
        device_name=name,
        role=str(response.get("role", "pc")),
        token=str(response["token"]),
    )
    save_agent(credentials)
    print("配对成功。")
    print(f"服务器：{credentials.server_url}")
    print(f"设备：{credentials.device_name}（{credentials.device_id}）")
    print(f"令牌已保存到 {AGENT_FILE}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    credentials = _load_or_exit()
    settings = AgentSettings.from_env(credentials.server_url)
    if args.idle_seconds is not None:
        settings = replace(settings, idle_seconds=args.idle_seconds)
    removed = cleanup_inbox()
    if removed:
        logger.info("已清理 %d 个过期的临时音频", removed)

    with single_instance(AGENT_LOCK) as acquired:
        if not acquired:
            print("已有云代理在运行，本次退出。")
            return 2
        agent = CloudAgent(credentials, settings)
        logger.info(
            "云代理启动：%s 设备=%s 空闲阈值=%ss %s",
            credentials.server_url,
            credentials.device_name,
            settings.idle_seconds,
            "单轮执行" if args.once else f"轮询={settings.poll_seconds}s",
        )
        try:
            while True:
                outcome = "error"
                try:
                    outcome = agent.tick(force=args.force)
                except CloudError as exc:
                    logger.warning("服务器暂不可用：%s", exc)
                except KeyboardInterrupt:
                    raise
                except Exception:
                    logger.exception("代理轮次异常")
                if args.once:
                    break
                delay = 5 if outcome == "processed" else settings.poll_seconds
                time.sleep(delay)
        except KeyboardInterrupt:
            logger.info("收到中断，云代理退出")
        finally:
            agent.close()
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    server_url = resolve_server_url(args.url)
    try:
        credentials = load_agent()
    except Exception as exc:
        print(f"读取配对信息失败：{exc}")
        return 2

    if credentials is None:
        print("尚未配对。")
        if not server_url:
            return 2
        with CloudClient(server_url) as client:
            try:
                health = client.health()
                print(f"服务器 {server_url} 可用：v{health.get('version')}，队列 {health.get('queue')}")
                return 0
            except CloudError as exc:
                print(f"服务器不可用：{exc}")
                return 1

    url = server_url or credentials.server_url
    settings = AgentSettings.from_env(url)
    print(f"服务器：{url}")
    print(f"设备：{credentials.device_name}（{credentials.device_id}）")
    print(f"令牌：{mask_token(credentials.token)}")
    print(f"本机配对文件：{AGENT_FILE}")

    with CloudClient(url, credentials.token) as client:
        try:
            me = client.me()
            print(f"服务端身份：{me.get('name')} / {me.get('role')}")
        except CloudError as exc:
            print(f"服务端身份校验失败：{exc}")

        status, health, error = collect_status(settings, client)
        print("")
        print(f"空闲检测：{'就绪' if status.ready else '暂不领取'}")
        if status.idle_seconds is not None:
            print(f"  用户空闲：{int(status.idle_seconds)} 秒（阈值 {settings.idle_seconds}）")
        if status.cpu_percent is not None:
            print(f"  CPU 占用：{status.cpu_percent:.0f}%")
        if status.gpu_percent is not None:
            print(f"  GPU 占用：{status.gpu_percent:.0f}%")
        if status.on_ac is not None:
            print(f"  供电：{'交流电' if status.on_ac else '电池'}")
        for reason in status.reasons:
            print(f"  - {reason}")
        print("")
        if health:
            queue = health.get("queue") or {}
            print(
                f"服务器：ok v{health.get('version')} 队列={queue.get('queued', 0)}"
                f"/{queue.get('leased', 0)} 笔记={health.get('notes', 0)} "
                f"音频={_human_bytes(health.get('audio_bytes', 0))} "
                f"磁盘可用={_human_bytes(health.get('disk_free_bytes', 0))}"
            )
        else:
            print(f"服务器：不可用（{error}）")
    pending = [p for p in OUTBOX_DIR.iterdir() if p.is_dir() and not p.name.startswith(".tmp-")]
    print(f"待上传结果：{len(pending)} 份")
    return 0 if health else 1


def cmd_push(args: argparse.Namespace) -> int:
    _load_or_exit()
    try:
        entry = resolve_entry(args.entry)
        result = push_entry(entry)
    except (LocalImportError, CloudError) as exc:
        print(f"同步失败：{exc}")
        return 1
    if result.get("duplicate"):
        print("这篇已经在手机端，文件已更新为最新版本。")
    else:
        print("已同步到手机端。")
    print(f"note_id：{result.get('note_id')}")
    print(f"文件数：{len(result.get('files') or [])}")
    return 0


def cmd_unpair(args: argparse.Namespace) -> int:
    credentials = load_agent() if AGENT_FILE.exists() else None
    if credentials is None:
        print("本机尚未配对。")
        return 0
    if not args.yes:
        answer = input(f"确认解除设备 {credentials.device_name} 的配对？[y/N] ").strip().lower()
        if answer not in {"y", "yes"}:
            print("已取消。")
            return 0
    clear_agent()
    print("本机配对信息已删除。服务器端设备仍可保留，可在服务器执行 revoke-device 撤销。")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.cloud_agent",
        description="会议记录 PC 云代理：空闲时领取录音、转写并回传笔记",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    pair = sub.add_parser("pair", help="用配对码绑定本机")
    pair.add_argument("--url", default="", help="服务器地址，如 http://100.x.y.z:8000")
    pair.add_argument("--code", required=True, help="PC 配对码")
    pair.add_argument("--name", default="", help="设备名，默认使用主机名")
    pair.set_defaults(func=cmd_pair)

    run = sub.add_parser("run", help="启动空闲拉取循环")
    run.add_argument("--force", action="store_true", help="忽略空闲条件（调试用）")
    run.add_argument("--once", action="store_true", help="只执行一轮后退出")
    run.add_argument("--idle-seconds", type=int, default=None, help="覆盖空闲阈值")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="查看配对、空闲与服务器状态")
    status.add_argument("--url", default="", help="覆盖已保存的服务器地址")
    status.set_defaults(func=cmd_status)

    push = sub.add_parser("push", help="把本地资料库的一篇纪要同步到手机端")
    push.add_argument("entry", help="资料库条目目录，或条目 job_id")
    push.set_defaults(func=cmd_push)

    unpair = sub.add_parser("unpair", help="删除本机配对信息")
    unpair.add_argument("--yes", action="store_true", help="不询问直接删除")
    unpair.set_defaults(func=cmd_unpair)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except (AttributeError, ValueError):
        pass
    args = build_parser().parse_args(argv)
    setup_logging()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
