from __future__ import annotations

import argparse
import json
from pathlib import Path

from .transcriber import Transcriber


def _load_chunks(args: argparse.Namespace) -> list[dict]:
    if args.manifest:
        payload = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
        chunks = payload.get("chunks") or []
        if not chunks:
            raise ValueError("分段清单为空")
        return chunks
    if not args.input:
        raise ValueError("缺少 --input 或 --manifest")
    return [{"path": args.input, "offset_ms": 0, "index": 0}]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input")
    parser.add_argument("--manifest")
    parser.add_argument("--output", required=True)
    parser.add_argument("--hotwords", default="")
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    chunks = _load_chunks(args)
    transcriber = Transcriber(args.device)
    merged = []
    try:
        device = transcriber.load(lambda message: print(message, flush=True))
        total = len(chunks)
        for position, chunk in enumerate(chunks, start=1):
            print(f"[{position}/{total}] 转写第 {position} 段…", flush=True)
            segments = transcriber.transcribe(Path(chunk["path"]), args.hotwords)
            offset = int(chunk.get("offset_ms") or 0)
            prefix = f"第{position}段" if total > 1 else ""
            for segment in segments:
                segment.start_ms += offset
                segment.end_ms += offset
                if prefix:
                    segment.speaker = prefix + segment.speaker
                merged.append(segment)
    finally:
        transcriber.release()

    payload = {
        "device": device,
        "chunks": len(chunks),
        "segments": [segment.to_dict() for segment in merged],
    }
    Path(args.output).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
