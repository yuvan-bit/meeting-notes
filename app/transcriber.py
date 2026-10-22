from __future__ import annotations

import gc
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

from . import config


class TranscriptionError(RuntimeError):
    pass


@dataclass
class Segment:
    start_ms: int
    end_ms: int
    speaker: str
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def free_vram() -> None:
    try:
        import torch

        if torch.cuda.is_available():
            gc.collect()
            torch.cuda.empty_cache()
    except Exception:
        pass


def gpu_info() -> dict:
    # 用 nvidia-smi 读取真实空闲显存；torch 在 WDDM 下会高估可用显存，
    # 且在主进程初始化 CUDA 上下文本身就会占用显存。
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=name,memory.total,memory.free",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode == 0 and result.stdout.strip():
            name, total_mb, free_mb = [
                part.strip() for part in result.stdout.strip().splitlines()[0].rsplit(",", 2)
            ]
            return {
                "available": True,
                "name": name,
                "free_gb": round(float(free_mb) / 1024, 2),
                "total_gb": round(float(total_mb) / 1024, 2),
            }
    except Exception:
        pass

    try:
        import torch

        if not torch.cuda.is_available():
            return {"available": False}
        free, total = torch.cuda.mem_get_info()
        return {
            "available": True,
            "name": torch.cuda.get_device_name(0),
            "free_gb": round(free / 1024**3, 2),
            "total_gb": round(total / 1024**3, 2),
        }
    except Exception as exc:
        return {"available": False, "error": str(exc)}


def choose_device(preferred: str = "auto") -> str:
    preferred = (preferred or "auto").lower()
    if preferred == "cuda":
        return "cuda:0"
    if preferred in {"cpu", "cuda:0"}:
        return preferred
    info = gpu_info()
    if not info.get("available"):
        return "cpu"
    # Paraformer + VAD + 标点 + cam++ 大约需要 1.5-2 GB 显存
    return "cuda:0" if info.get("free_gb", 0) >= 2.0 else "cpu"


class Transcriber:
    def __init__(self, device: str = "auto"):
        self.requested_device = device
        self.device: str | None = None
        self.model = None

    def _build(self, device: str):
        from funasr import AutoModel

        kwargs = {
            "model": config.ASR_MODEL,
            "vad_model": config.VAD_MODEL,
            "punc_model": config.PUNC_MODEL,
            "spk_model": config.SPK_MODEL,
            "device": device,
            "disable_update": True,
        }
        try:
            return AutoModel(**kwargs)
        except TypeError:
            kwargs.pop("disable_update", None)
            return AutoModel(**kwargs)

    def load(self, progress: Callable[[str], None] | None = None) -> str:
        free_vram()
        self.device = choose_device(self.requested_device)
        if progress:
            progress(f"加载 FunASR 模型（{self.device}）…")
        try:
            self.model = self._build(self.device)
        except Exception as exc:
            if self.device != "cpu":
                free_vram()
                self.device = "cpu"
                if progress:
                    progress("GPU 装载失败，改用 CPU 加载模型…")
                self.model = self._build("cpu")
            else:
                raise TranscriptionError(f"FunASR 模型加载失败：{exc}") from exc
        return self.device

    def _generate(self, wav_path: Path, hotwords: str):
        kwargs: dict = {"input": str(wav_path), "batch_size_s": 300}
        if hotwords.strip():
            kwargs["hotword"] = hotwords.strip()
        try:
            return self.model.generate(**kwargs)
        except TypeError:
            if "hotword" not in kwargs:
                raise
            kwargs.pop("hotword")
            return self.model.generate(**kwargs)

    def transcribe(
        self,
        wav_path: Path,
        hotwords: str = "",
        progress: Callable[[str], None] | None = None,
    ) -> list[Segment]:
        if self.model is None:
            self.load(progress)
        if progress:
            progress(f"转写与说话人分离中（{self.device}）…")
        try:
            result = self._generate(wav_path, hotwords)
        except Exception as exc:
            message = str(exc).lower()
            oom = "out of memory" in message or "cuda error" in message
            if self.device != "cpu" and oom:
                self.release()
                self.device = "cpu"
                if progress:
                    progress("显存不足，改为 CPU 重试…")
                self.model = self._build("cpu")
                result = self._generate(wav_path, hotwords)
            else:
                raise TranscriptionError(f"转写失败：{exc}") from exc

        if not result:
            raise TranscriptionError("ASR 未返回任何结果。")

        item = result[0] or {}
        sentence_info = item.get("sentence_info") or []
        segments: list[Segment] = []
        for sentence in sentence_info:
            text = (sentence.get("sentence") or sentence.get("text") or "").strip()
            if not text:
                continue
            match = re.search(r"\d+", str(sentence.get("spk", 0)))
            speaker = f"发言人{int(match.group()) if match else 0}"
            segments.append(
                Segment(
                    start_ms=int(sentence.get("start") or 0),
                    end_ms=int(sentence.get("end") or 0),
                    speaker=speaker,
                    text=text,
                )
            )

        if not segments:
            text = (item.get("text") or "").strip()
            if not text:
                raise TranscriptionError("ASR 返回了空转写。")
            segments = [Segment(0, 0, "发言人0", text)]

        return segments

    def release(self) -> None:
        self.model = None
        free_vram()
