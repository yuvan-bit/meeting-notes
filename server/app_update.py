from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any

from .config import Settings
from .utils import iso

APK_FILENAME = "latest.apk"
META_FILENAME = "latest.json"


class ReleaseError(RuntimeError):
    pass


def read_release(settings: Settings) -> dict[str, Any] | None:
    path = settings.app_dir / META_FILENAME
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        version_code = int(data["version_code"])
        version_name = str(data["version_name"]).strip()
        sha256 = str(data["sha256"]).strip().lower()
        size_bytes = int(data["size_bytes"])
        changelog = str(data.get("changelog") or "").strip()
        published_at = str(data.get("published_at") or "").strip()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ReleaseError("更新元数据损坏") from exc
    if (
        version_code <= 0
        or not version_name
        or not re.fullmatch(r"[0-9a-f]{64}", sha256)
        or size_bytes <= 0
    ):
        raise ReleaseError("更新元数据不完整")
    return {
        "version_code": version_code,
        "version_name": version_name,
        "sha256": sha256,
        "size_bytes": size_bytes,
        "changelog": changelog,
        "published_at": published_at,
    }


def publish_apk(
    settings: Settings,
    source: str | Path,
    version_code: int,
    version_name: str,
    changelog: str = "",
) -> dict[str, Any]:
    source = Path(source)
    if not source.is_file():
        raise ReleaseError(f"找不到 APK：{source}")
    if source.suffix.lower() != ".apk":
        raise ReleaseError("文件扩展名必须是 .apk")
    version_name = version_name.strip()
    if version_code <= 0:
        raise ReleaseError("version-code 必须是正整数")
    if not version_name:
        raise ReleaseError("version-name 不能为空")
    with source.open("rb") as handle:
        if handle.read(4) != b"PK\x03\x04":
            raise ReleaseError("文件不是有效的 APK（缺少 ZIP 头）")

    settings.app_dir.mkdir(parents=True, exist_ok=True)
    target = settings.app_dir / APK_FILENAME
    temp = settings.app_dir / (APK_FILENAME + ".tmp")
    digest = hashlib.sha256()
    size = 0
    with source.open("rb") as src, temp.open("wb") as dst:
        while True:
            block = src.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
            dst.write(block)
            size += len(block)
    os.replace(temp, target)

    meta = {
        "version_code": version_code,
        "version_name": version_name,
        "sha256": digest.hexdigest(),
        "size_bytes": size,
        "changelog": changelog.strip(),
        "published_at": iso(),
    }
    meta_temp = settings.app_dir / (META_FILENAME + ".tmp")
    meta_temp.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(meta_temp, settings.app_dir / META_FILENAME)
    return meta
