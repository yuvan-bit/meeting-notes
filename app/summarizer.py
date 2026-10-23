from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests

from . import config
from .audio import format_ts
from .transcriber import Segment, gpu_info

ProgressFn = Callable[[float, str], None]


class SummaryError(RuntimeError):
    pass


MEETING_SYSTEM_PROMPT = (
    "你是一名严谨的中文会议纪要助手。你只依据用户提供的会议转写或分段摘要工作，"
    "绝不编造事实、负责人、期限或结论。原文没有的信息必须写“未提及”。"
    "不得添加原文没有的年份、日期、人名、数字，不得把推测写成结论。"
)
COURSE_SYSTEM_PROMPT = (
    "你是一名严谨的中文课程笔记助手。你只依据用户提供的课堂转写或分段摘要工作，"
    "绝不编造概念、定义、公式、例题或作业要求。原文没有的信息写“转写未提及”，"
    "听不清或语义不完整的内容写“转写不清”。不得补全原文没有的数字、年份和人名。"
)


def check_ollama(timeout: float = 5) -> tuple[bool, list[str], str]:
    try:
        response = requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=timeout)
        response.raise_for_status()
        models = [item.get("name", "") for item in response.json().get("models", [])]
        return True, models, ""
    except Exception as exc:
        return (
            False,
            [],
            f"无法连接 Ollama（{config.OLLAMA_URL}）：{exc}。请先运行 `ollama serve`。",
        )


def _ollama_executable() -> str | None:
    found = shutil.which("ollama")
    if found:
        return found
    local = os.environ.get("LOCALAPPDATA", "")
    candidates = [
        Path(local) / "Programs" / "Ollama" / "ollama.exe" if local else None,
        Path("C:/Program Files/Ollama/ollama.exe"),
    ]
    for candidate in candidates:
        if candidate is not None and candidate.is_file():
            return str(candidate)
    return None


def ensure_ollama(wait_seconds: float = 30) -> bool:
    ok, _, _ = check_ollama(timeout=2)
    if ok:
        return True
    executable = _ollama_executable()
    if not executable:
        return False
    try:
        subprocess.Popen(
            [executable, "serve"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError:
        return False
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        time.sleep(0.5)
        ok, _, _ = check_ollama(timeout=1)
        if ok:
            return True
    return False


def parse_speaker_map(text: str) -> dict[str, str]:
    mapping: dict[str, str] = {}
    for part in re.split(r"[,，;；\n]+", text or ""):
        part = part.strip()
        if not part:
            continue
        match = re.match(r"\s*(?:发言人)?\s*(\d+)\s*[=:：]\s*(.+?)\s*$", part)
        if match:
            mapping[match.group(1)] = match.group(2)
    return mapping


def resolve_speaker_names(
    segments: list[Segment], mapping: dict[str, str]
) -> dict[str, str]:
    names: dict[str, str] = {}
    for speaker in sorted({segment.speaker for segment in segments}):
        match = re.fullmatch(r"(?:发言人)?(\d+)", speaker)
        key = match.group(1) if match else speaker
        names[speaker] = mapping.get(key, speaker)
    return names


def transcript_lines(segments: list[Segment], names: dict[str, str]) -> list[str]:
    return [
        f"[{format_ts(segment.start_ms)}] {names.get(segment.speaker, segment.speaker)}: {segment.text}"
        for segment in segments
    ]


def chunk_lines(lines: list[str], max_chars: int = config.MAX_CHARS_PER_CHUNK) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    size = 0
    for line in lines:
        line_size = len(line) + 1
        if current and size + line_size > max_chars:
            chunks.append("\n".join(current))
            current = [line]
            size = line_size
        else:
            current.append(line)
            size += line_size
    if current:
        chunks.append("\n".join(current))
    return chunks


def _strip_fence(text: str) -> str:
    text = text.strip()
    text = re.sub(r"^```(?:markdown|md)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


@dataclass
class SummaryMeta:
    model: str
    num_gpu: int | None
    chunks: int
    elapsed_s: float


class Summarizer:
    def __init__(self, model: str = config.DEFAULT_LLM, content_type: str = "meeting"):
        self.requested_model = model
        self.content_type = "course" if content_type == "course" else "meeting"
        self.active: tuple[str, int | None] | None = None
        self.meta: SummaryMeta | None = None

    @property
    def label(self) -> str:
        return "课程笔记" if self.content_type == "course" else "会议纪要"

    def _system_prompt(self) -> str:
        return (
            COURSE_SYSTEM_PROMPT
            if self.content_type == "course"
            else MEETING_SYSTEM_PROMPT
        )

    def _post(self, payload: dict):
        try:
            return requests.post(
                f"{config.OLLAMA_URL}/api/chat",
                json=payload,
                timeout=(5, config.LLM_TIMEOUT),
            )
        except requests.RequestException as exc:
            raise SummaryError(f"调用 Ollama 失败：{exc}") from exc

    def _chat(
        self,
        model: str,
        messages: list[dict],
        num_predict: int,
        num_gpu: int | None,
    ) -> str:
        options = {
            "num_ctx": config.SUMMARY_NUM_CTX,
            "num_predict": num_predict,
            "temperature": 0.2,
            "top_p": 0.9,
        }
        if num_gpu is not None:
            options["num_gpu"] = num_gpu
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": False,
            "keep_alive": config.LLM_KEEP_ALIVE,
            "options": options,
        }
        response = self._post(payload)
        if response.status_code == 400 and "think" in payload:
            # 兼容不支持 think 参数的旧版 Ollama
            payload.pop("think", None)
            response = self._post(payload)
        if response.status_code != 200:
            raise SummaryError(
                f"Ollama 返回 {response.status_code}: {response.text[:800]}"
            )
        data = response.json()
        if data.get("error"):
            raise SummaryError(str(data["error"]))
        content = ((data.get("message") or {}).get("content") or "").strip()
        if not content:
            raise SummaryError("摘要模型返回了空内容。")
        return _strip_fence(content)

    def _candidates(self) -> list[tuple[str, int | None]]:
        requested = self.requested_model
        fast = config.FAST_LLM
        info = gpu_info()
        free_gb = info.get("free_gb", 0.0) if info.get("available") else 0.0
        candidates: list[tuple[str, int | None]] = []

        def add(model: str, num_gpu: int | None) -> None:
            item = (model, num_gpu)
            if item not in candidates:
                candidates.append(item)

        if requested == fast:
            if free_gb >= 4.2:
                add(fast, None)
            if free_gb >= 1.6:
                add(fast, 8)
            add(fast, 0)
            return candidates

        # 按当前空闲显存从好到差排列；9B 权重 5.7GB，加上 KV/开销约需 6.7GB
        if free_gb >= 6.7:
            add(requested, None)
        if free_gb >= 4.3:
            add(requested, 20)
        if free_gb >= 3.4:
            add(requested, 16)
        if free_gb >= 2.7:
            add(requested, 12)
        if free_gb >= 2.0:
            add(requested, 8)
        if free_gb >= 4.2:
            add(fast, None)
        if free_gb >= 1.5:
            add(fast, 8)
        add(fast, 0)
        add(requested, 0)
        return candidates

    def _run(self, messages: list[dict], num_predict: int) -> str:
        errors: list[str] = []
        if self.active is not None:
            model, num_gpu = self.active
            try:
                return self._chat(model, messages, num_predict, num_gpu)
            except SummaryError as exc:
                errors.append(f"{model} / num_gpu={num_gpu}（已加载配置失效）: {exc}")
                print(f"[摘要] {model} / num_gpu={num_gpu} 失败：{exc}", file=sys.stderr, flush=True)
                self.active = None

        for model, num_gpu in self._candidates():
            try:
                content = self._chat(model, messages, num_predict, num_gpu)
                self.active = (model, num_gpu)
                return content
            except SummaryError as exc:
                errors.append(f"{model} / num_gpu={num_gpu}: {exc}")
                print(f"[摘要] {model} / num_gpu={num_gpu} 失败：{exc}", file=sys.stderr, flush=True)
                time.sleep(0.5)
        detail = "\n".join(errors[-4:])
        raise SummaryError(
            "所有本地摘要模型配置均失败，请检查 Ollama 与显存。\n" + detail
        )

    def _map_prompt(self, chunk: str, index: int, total: int) -> str:
        if self.content_type == "course":
            return f"""下面是一堂课程的第 {index}/{total} 段转写，每行格式为“[时间戳] 发言人: 内容”。

请只依据这段原文，输出以下 Markdown 小节：

### 本段要点
- ...

### 关键概念/定义
- 概念：原文给出的解释（没有解释就只列概念）

### 例题/案例
- 无（本段未提及） / - ...

### 疑问/待确认
- 无（本段未提及） / - 转写不清之处

要求：
1. 不得补充原文没有的概念、公式、数字或结论，不得补全年份。
2. 术语、公式按原文保留，听不清就写“转写不清”。
3. 简洁、去重、简体中文。

转写内容：
{chunk}"""

        return f"""下面是一场会议的第 {index}/{total} 段转写，每行格式为“[时间戳] 发言人: 内容”。

请只依据这段原文，输出以下 Markdown 小节：

### 本段要点
- ...

### 明确结论/决策
- 无（本段未提及） / - ...

### 待办
- 事项｜负责人｜期限（原文未提及就写“未提及”）

### 风险/未决问题
- 无（本段未提及） / - ...

要求：
1. 不得补充原文没有的信息，不得推断负责人和期限，不得补全年份或换算相对时间。
2. 保留关键时间戳。
3. 简洁、去重、简体中文。

转写内容：
{chunk}"""

    def _final_prompt(self, material: str, kind: str) -> str:
        if self.content_type == "course":
            return f"""下面是同一堂课的{kind}。请生成最终课程笔记，严格使用以下结构：

# 课程笔记

## 课程主题
...

## 一句话概括
...

## 核心概念
- 概念：解释

## 知识点详解
- ...

## 例题与案例
- 无（未提及） / - ...

## 作业与复习建议
- 无（未提及） / - ...

## 疑问与待确认
- 转写不清或未展开的内容

规则：
1. 只依据给定内容，禁止编造；原文没有的概念、公式、数字、人名不得补全。
2. 术语和公式保持原文表述，听不清的写“转写不清”。
3. 合并重复内容，关键知识点尽量保留时间戳。
4. 简体中文，层次清楚，不写空话。

{kind}：
{material}"""

        return f"""下面是同一场会议的{kind}。请生成最终会议纪要，严格使用以下结构：

# 会议纪要

## 会议主题
...

## 一句话摘要
...

## 关键结论与决策
- ...

## 待办事项
| 事项 | 负责人 | 期限 | 依据 |
|---|---|---|---|
| ... | ... | ... | ... |

## 风险与未确认事项
- ...

## 讨论要点
- ...

规则：
1. 只依据给定内容，禁止编造；原文未提及的负责人/期限写“未提及”。
2. 原文没有的年份、日期、人名、数字一律不得补全或改写；相对时间（如“本周五”“十月底”）保持原表述，不要换算成具体日期。
3. 合并重复内容，关键结论尽量保留时间戳。
4. 简体中文，信息密度高，不写空话。

{kind}：
{material}"""

    def summarize(
        self,
        segments: list[Segment],
        names: dict[str, str],
        progress: ProgressFn | None = None,
    ) -> tuple[str, SummaryMeta]:
        started = time.time()
        lines = transcript_lines(segments, names)

        def report(fraction: float, message: str) -> None:
            if progress:
                progress(fraction, message)

        if not lines:
            raise SummaryError("没有可用于生成纪要的转写内容。")

        report(0.05, "检查本地摘要模型…")
        ensure_ollama()

        if len("\n".join(lines)) <= config.MAX_CHARS_PER_CHUNK:
            report(0.35, f"生成{self.label}…")
            content = self._run(
                [
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": self._final_prompt("\n".join(lines), "完整转写")},
                ],
                num_predict=2200,
            )
            chunks = 1
        else:
            chunks_text = chunk_lines(lines)
            chunk_summaries: list[str] = []
            for index, chunk in enumerate(chunks_text, start=1):
                report(
                    0.15 + 0.6 * (index - 1) / len(chunks_text),
                    f"分段摘要 {index}/{len(chunks_text)}…",
                )
                summary = self._run(
                    [
                        {"role": "system", "content": self._system_prompt()},
                        {"role": "user", "content": self._map_prompt(chunk, index, len(chunks_text))},
                    ],
                    num_predict=900,
                )
                chunk_summaries.append(f"## 第 {index} 段\n{summary}")
            report(0.82, f"汇总全篇{self.label}…")
            material = "\n\n".join(chunk_summaries)
            content = self._run(
                [
                    {"role": "system", "content": self._system_prompt()},
                    {"role": "user", "content": self._final_prompt(material, "分段摘要")},
                ],
                num_predict=2400,
            )
            chunks = len(chunks_text)

        report(1.0, f"{self.label}生成完成")
        model, num_gpu = self.active or (self.requested_model, None)
        self.meta = SummaryMeta(
            model=model,
            num_gpu=num_gpu,
            chunks=chunks,
            elapsed_s=round(time.time() - started, 1),
        )
        return content, self.meta

    def unload(self) -> None:
        if not self.active:
            return
        model, _ = self.active
        try:
            requests.post(
                f"{config.OLLAMA_URL}/api/generate",
                json={"model": model, "keep_alive": 0},
                timeout=(3, 10),
            )
        except requests.RequestException:
            pass
        self.active = None
