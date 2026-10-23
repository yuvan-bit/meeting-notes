from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
OUTPUT_DIR = DATA_DIR / "outputs"
WORK_DIR = DATA_DIR / "work"
SAMPLE_DIR = DATA_DIR / "samples"
LIBRARY_DIR = DATA_DIR / "library"
MODEL_DIR = BASE_DIR / "models"

for _dir in (OUTPUT_DIR, WORK_DIR, SAMPLE_DIR, LIBRARY_DIR, MODEL_DIR):
    _dir.mkdir(parents=True, exist_ok=True)

# 模型缓存全部留在项目目录，避免污染用户主目录
os.environ.setdefault("MODELSCOPE_CACHE", str(MODEL_DIR / "modelscope"))
os.environ.setdefault("MODELSCOPE_CACHE_HOME", str(MODEL_DIR / "modelscope"))
os.environ.setdefault("HF_HOME", str(MODEL_DIR / "huggingface"))
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("GRADIO_ANALYTICS_ENABLED", "False")

OLLAMA_URL = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434").rstrip("/")
if not OLLAMA_URL.startswith(("http://", "https://")):
    OLLAMA_URL = "http://" + OLLAMA_URL

DEFAULT_LLM = os.environ.get("MEETING_LLM", "qwen3.5:9b")
FAST_LLM = os.environ.get("MEETING_LLM_FAST", "qwen3.5:4b")

ASR_MODEL = os.environ.get("MEETING_ASR_MODEL", "paraformer-zh")
VAD_MODEL = os.environ.get("MEETING_VAD_MODEL", "fsmn-vad")
PUNC_MODEL = os.environ.get("MEETING_PUNC_MODEL", "ct-punc")
SPK_MODEL = os.environ.get("MEETING_SPK_MODEL", "cam++")
ASR_DEVICE = os.environ.get("MEETING_ASR_DEVICE", "auto").lower()

# 超过阈值的长音频按停顿位置自动切段，避免单次加载过大。
ASR_CHUNK_THRESHOLD_S = int(os.environ.get("MEETING_ASR_CHUNK_THRESHOLD_S", "1800"))
ASR_CHUNK_TARGET_S = int(os.environ.get("MEETING_ASR_CHUNK_TARGET_S", "900"))
ASR_CHUNK_MIN_S = int(os.environ.get("MEETING_ASR_CHUNK_MIN_S", "300"))
ASR_CHUNK_MAX_S = int(os.environ.get("MEETING_ASR_CHUNK_MAX_S", "1200"))

MAX_CHARS_PER_CHUNK = int(os.environ.get("MEETING_CHUNK_CHARS", "4000"))
SUMMARY_NUM_CTX = int(os.environ.get("MEETING_NUM_CTX", "8192"))
LLM_KEEP_ALIVE = os.environ.get("MEETING_LLM_KEEP_ALIVE", "10m")
LLM_TIMEOUT = int(os.environ.get("MEETING_LLM_TIMEOUT", "1800"))
