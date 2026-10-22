from __future__ import annotations

import argparse
import json
from pathlib import Path

from .transcriber import Transcriber


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--hotwords", default="")
    parser.add_argument("--device", default="auto")
    args = parser.parse_args()

    transcriber = Transcriber(args.device)
    try:
        device = transcriber.load(lambda message: print(message, flush=True))
        print(f"转写与说话人分离中（{device}）…", flush=True)
        segments = transcriber.transcribe(Path(args.input), args.hotwords)
    finally:
        transcriber.release()

    payload = {
        "device": device,
        "segments": [segment.to_dict() for segment in segments],
    }
    Path(args.output).write_text(
        json.dumps(payload, ensure_ascii=False),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
