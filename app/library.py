from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Iterable

from . import config

LIBRARY_DIR = config.LIBRARY_DIR
INDEX_PATH = LIBRARY_DIR / "index.json"

TYPE_LABELS = {"meeting": "会议", "course": "课程"}

COURSE_HINTS = (
    "同学们", "大家好", "老师", "上课", "这节课", "本节课", "本章", "这一章",
    "知识点", "作业", "考试", "复习", "教材", "例题", "定理", "公式", "实验",
    "课程", "课堂", "定义", "证明",
)
MEETING_HINTS = (
    "会议", "项目", "进度", "上线", "需求", "负责人", "决策", "待办", "排期",
    "评审", "汇报", "客户", "预算", "风险", "方案", "交付", "产品",
)


def detect_content_type(text: str) -> str:
    course_score = sum(text.count(word) for word in COURSE_HINTS)
    meeting_score = sum(text.count(word) for word in MEETING_HINTS)
    return "course" if course_score > meeting_score else "meeting"


def type_label(content_type: str) -> str:
    return TYPE_LABELS.get(content_type, content_type)


def sanitize_topic(topic: str, limit: int = 40) -> str:
    text = re.sub(r'[\\/:*?"<>|\r\n\t]+', " ", topic or "")
    text = re.sub(r"\s+", " ", text).strip(" .")
    if not text:
        return "未命名"
    return text[:limit].rstrip(" .")


def extract_section(markdown: str, names: Iterable[str]) -> str:
    wanted = tuple(names)
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        heading = line.strip()
        if not heading.startswith("## ") or not any(name in heading for name in wanted):
            continue
        for candidate in lines[index + 1:]:
            value = candidate.strip()
            if not value or value.startswith("#"):
                continue
            value = re.sub(r"^[-*>\s]+", "", value).strip("*").strip()
            if value and not re.fullmatch(r"[|\-\s:]+", value):
                return value
    return ""


def create_entry_dir(created: datetime, content_type: str, topic: str) -> Path:
    month_dir = LIBRARY_DIR / created.strftime("%Y") / created.strftime("%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    stem = (
        f"{created.strftime('%Y-%m-%d_%H%M')}"
        f"_{type_label(content_type)}_{sanitize_topic(topic)}"
    )
    candidate = month_dir / stem
    suffix = 2
    while candidate.exists():
        candidate = month_dir / f"{stem}_{suffix}"
        suffix += 1
    candidate.mkdir(parents=True)
    return candidate


def _load_meta(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    try:
        data["path"] = path.parent.relative_to(LIBRARY_DIR).as_posix()
    except ValueError:
        return None
    return data


def scan_entries() -> list[dict]:
    if not LIBRARY_DIR.exists():
        return []
    entries: list[dict] = []
    for meta_path in LIBRARY_DIR.glob("*/*/*/meta.json"):
        meta = _load_meta(meta_path)
        if meta is not None:
            entries.append(meta)
    entries.sort(key=lambda item: item.get("created_at", ""), reverse=True)
    return entries


def rebuild_index() -> list[dict]:
    entries = scan_entries()
    LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
    temp = INDEX_PATH.with_suffix(".json.tmp")
    temp.write_text(
        json.dumps(
            {
                "updated_at": datetime.now().isoformat(timespec="seconds"),
                "entries": entries,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    temp.replace(INDEX_PATH)
    return entries


def list_entries() -> list[dict]:
    if not INDEX_PATH.exists():
        return rebuild_index()
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
        entries = data.get("entries", [])
        if isinstance(entries, list) and entries:
            return entries
    except Exception:
        pass
    return rebuild_index()


def filter_entries(
    entries: list[dict],
    type_filter: str = "全部",
    search: str = "",
) -> list[dict]:
    result = entries
    if type_filter in TYPE_LABELS.values():
        result = [item for item in result if item.get("type_label") == type_filter]
    keyword = (search or "").strip().lower()
    if keyword:
        def haystack(item: dict) -> str:
            parts = [
                str(item.get("topic", "")),
                str(item.get("summary", "")),
                str(item.get("source", "")),
                " ".join(item.get("tags", []) or []),
            ]
            return " ".join(parts).lower()

        result = [item for item in result if keyword in haystack(item)]
    return result


def entry_label(entry: dict) -> str:
    created = str(entry.get("created_at", "")).replace("T", " ")[:16]
    return (
        f"{created}｜{entry.get('type_label', '')}｜"
        f"{entry.get('topic', '未命名')}"
    )


def entry_path(entry: dict) -> Path:
    return LIBRARY_DIR / entry["path"]


def entry_file_paths(entry: dict) -> list[str]:
    root = entry_path(entry)
    paths: list[str] = []
    seen: set[str] = set()
    for name in (entry.get("files") or {}).values():
        candidate = root / name
        if candidate.is_file() and str(candidate) not in seen:
            seen.add(str(candidate))
            paths.append(str(candidate))
    return paths


def read_text_file(path: str | Path, limit: int = 600_000) -> str:
    candidate = Path(path)
    try:
        text = candidate.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"无法读取文件：{exc}"
    if len(text) > limit:
        return text[:limit] + "\n\n…（内容过长，已截断）"
    return text
