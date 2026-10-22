from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config
from .health import run_checks
from .pipeline import run_pipeline
from .transcriber import Transcriber


def _progress_printer():
    last = {"pct": -1}

    def report(fraction: float, message: str) -> None:
        pct = int(round(fraction * 100))
        if pct == last["pct"] and pct not in (0, 100):
            return
        last["pct"] = pct
        print(f"[{pct:3d}%] {message}", flush=True)

    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="本地会议录音转写与纪要生成（FunASR + Ollama）"
    )
    parser.add_argument("input", nargs="?", help="音频或视频文件路径")
    parser.add_argument("--hotwords", default="", help="热词，用空格分隔，例如：产品名 人名")
    parser.add_argument(
        "--speakers",
        default="",
        help="发言人映射，例如：0=张三,1=李四",
    )
    parser.add_argument(
        "--model",
        default=config.DEFAULT_LLM,
        help=f"Ollama 摘要模型，默认 {config.DEFAULT_LLM}",
    )
    parser.add_argument(
        "--asr-device",
        default=config.ASR_DEVICE,
        choices=["auto", "cuda", "cpu"],
        help="ASR 设备，默认 auto",
    )
    parser.add_argument(
        "--type",
        dest="content_type",
        default="auto",
        choices=["auto", "meeting", "course"],
        help="内容类型：auto 自动识别，meeting 会议，course 课程",
    )
    parser.add_argument("--check", action="store_true", help="检查运行环境后退出")
    parser.add_argument("--preload", action="store_true", help="预下载并加载 ASR 模型后退出")
    args = parser.parse_args()

    if args.check:
        print(run_checks())
        return 0

    if args.preload:
        transcriber = Transcriber(args.asr_device)
        try:
            device = transcriber.load(lambda message: print(message, flush=True))
            print(f"ASR 模型加载成功，设备：{device}")
        finally:
            transcriber.release()
        return 0

    if not args.input:
        parser.error("需要提供输入文件，或使用 --check / --preload")

    source = Path(args.input)
    try:
        result = run_pipeline(
            source,
            hotwords=args.hotwords,
            speaker_map_text=args.speakers,
            model=args.model,
            asr_device=args.asr_device,
            content_type=args.content_type,
            progress=_progress_printer(),
        )
    except Exception as exc:
        print(f"\n处理失败：{exc}", file=sys.stderr)
        return 1

    print("\n完成。")
    print(f"类型：{result.content_type_label}；主题：{result.topic}")
    print(f"耗时：{result.elapsed_s}s；转写设备：{result.asr_device}；"
          f"摘要模型：{result.summary_model}（num_gpu={result.summary_num_gpu}）")
    for warning in result.warnings:
        print(f"提示：{warning}")
    print(f"资料库目录：{result.output_dir}")
    for name, path in result.files.items():
        print(f"  {name}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
