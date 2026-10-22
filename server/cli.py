from __future__ import annotations

import argparse
import json
import shutil

from .cleanup import cleanup
from .config import Settings
from .db import connect, init_db
from .pairing import issue_pairing_code, revoke_device
from .utils import human_bytes


def _settings() -> Settings:
    settings = Settings.from_env()
    settings.ensure_dirs()
    init_db(settings.db_path)
    return settings


def _pair_code(settings: Settings, role: str, ttl: int) -> int:
    conn = connect(settings.db_path)
    try:
        code, expires_at = issue_pairing_code(conn, settings, role, ttl)
    finally:
        conn.close()
    print(f"配对码：{code}")
    print(f"角色：{role}")
    print(f"有效期至：{expires_at}")
    print("配对码只显示一次，请立即在客户端输入。")
    return 0


def _cleanup(settings: Settings) -> int:
    stats = cleanup(settings)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


def _stats(settings: Settings) -> int:
    conn = connect(settings.db_path)
    try:
        devices = conn.execute("SELECT COUNT(*) AS n FROM devices WHERE revoked=0").fetchone()["n"]
        recordings = conn.execute("SELECT COUNT(*) AS n FROM recordings").fetchone()["n"]
        jobs = {
            row["status"]: row["n"]
            for row in conn.execute("SELECT status, COUNT(*) AS n FROM jobs GROUP BY status")
        }
        notes = conn.execute("SELECT COUNT(*) AS n FROM notes").fetchone()["n"]
        audio_bytes = conn.execute(
            "SELECT COALESCE(SUM(size_bytes), 0) AS n FROM recordings "
            "WHERE audio_path IS NOT NULL AND audio_deleted_at IS NULL"
        ).fetchone()["n"]
        usage = shutil.disk_usage(settings.data_dir)
    finally:
        conn.close()
    print(
        json.dumps(
            {
                "data_dir": str(settings.data_dir),
                "devices": devices,
                "recordings": recordings,
                "jobs": jobs,
                "notes": notes,
                "audio_bytes": audio_bytes,
                "audio_human": human_bytes(audio_bytes),
                "disk_free_bytes": usage.free,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _list_devices(settings: Settings) -> int:
    conn = connect(settings.db_path)
    try:
        rows = conn.execute(
            "SELECT id, name, role, revoked, created_at, last_seen_at "
            "FROM devices ORDER BY created_at DESC"
        ).fetchall()
    finally:
        conn.close()
    for row in rows:
        print(
            f"{row['id']}  {row['role']:5s}  revoked={row['revoked']}  "
            f"{row['name']}  last_seen={row['last_seen_at']}"
        )
    return 0


def _revoke(settings: Settings, device_id: str) -> int:
    conn = connect(settings.db_path)
    try:
        ok = revoke_device(conn, device_id)
    finally:
        conn.close()
    print("已撤销" if ok else "设备不存在或已撤销")
    return 0 if ok else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="会议记录云端运维工具")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("init-db", help="初始化数据库")
    pair = sub.add_parser("pair-code", help="生成一次性配对码")
    pair.add_argument("--role", choices=["phone", "pc"], default="phone")
    pair.add_argument("--ttl", type=int, default=600, help="有效期秒数")
    sub.add_parser("cleanup", help="执行保留策略清理")
    sub.add_parser("stats", help="查看统计")
    sub.add_parser("list-devices", help="列出设备")
    revoke = sub.add_parser("revoke-device", help="撤销设备令牌")
    revoke.add_argument("device_id")

    args = parser.parse_args()
    settings = _settings()
    if args.command == "init-db":
        print(f"数据库已初始化：{settings.db_path}")
        return 0
    if args.command == "pair-code":
        return _pair_code(settings, args.role, args.ttl)
    if args.command == "cleanup":
        return _cleanup(settings)
    if args.command == "stats":
        return _stats(settings)
    if args.command == "list-devices":
        return _list_devices(settings)
    if args.command == "revoke-device":
        return _revoke(settings, args.device_id)
    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
