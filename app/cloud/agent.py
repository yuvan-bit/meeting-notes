from __future__ import annotations

import json
import logging
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from ..locks import ProcessingBusy
from ..pipeline import JobResult, run_pipeline
from .client import CloudClient, CloudError
from .config import (
    INBOX_DIR,
    ORPHAN_DIR,
    OUTBOX_DIR,
    AgentSettings,
)
from .idle import IdleStatus, evaluate_idle
from .ollama import ensure_ollama
from .store import AgentCredentials

logger = logging.getLogger("cloud_agent")

AUDIO_SUFFIXES = {
    ".m4a", ".aac", ".mp3", ".wav", ".flac", ".ogg", ".opus",
    ".amr", ".wma", ".mp4", ".mkv", ".mov", ".webm",
}
RESULT_FILE_NAMES = (
    "minutes.md",
    "transcript.md",
    "transcript.txt",
    "transcript.srt",
    "transcript.json",
    "meta.json",
)
PIPELINE_FILE_KEYS = {
    "minutes.md": "minutes",
    "transcript.md": "transcript_md",
    "transcript.txt": "transcript_txt",
    "transcript.srt": "transcript_srt",
    "transcript.json": "transcript_json",
    "meta.json": "job_json",
}


class AgentError(RuntimeError):
    pass


def _audio_suffix(filename: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    return suffix if suffix in AUDIO_SUFFIXES else ".m4a"


def _move_to_orphan(folder: Path, reason: str) -> Path:
    ORPHAN_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = ORPHAN_DIR / f"{folder.name}_{stamp}"
    suffix = 2
    while target.exists():
        target = ORPHAN_DIR / f"{folder.name}_{stamp}_{suffix}"
        suffix += 1
    shutil.move(str(folder), str(target))
    logger.warning("结果已移入待人工处理目录（%s）：%s", reason, target)
    return target


def save_outbox(job_id: str, recording_id: str, result: JobResult) -> Path:
    final_dir = OUTBOX_DIR / job_id
    if final_dir.exists():
        _move_to_orphan(final_dir, "同一任务存在旧的待上传结果")
    tmp_dir = OUTBOX_DIR / f".tmp-{job_id}-{int(time.time())}"
    shutil.rmtree(tmp_dir, ignore_errors=True)
    tmp_dir.mkdir(parents=True, exist_ok=False)
    try:
        copied = []
        for name in RESULT_FILE_NAMES:
            source = result.files.get(PIPELINE_FILE_KEYS[name])
            if not source:
                continue
            source_path = Path(source)
            if not source_path.is_file():
                continue
            shutil.copy2(source_path, tmp_dir / name)
            copied.append(name)
        if "minutes.md" not in copied:
            raise AgentError("流水线没有产出 minutes.md")
        manifest = {
            "job_id": job_id,
            "recording_id": recording_id,
            "created_at": datetime.now().replace(microsecond=0).isoformat(),
            "files": copied,
        }
        (tmp_dir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        final_dir.parent.mkdir(parents=True, exist_ok=True)
        tmp_dir.replace(final_dir)
        return final_dir
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def _load_manifest(folder: Path) -> dict:
    try:
        data = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise AgentError(f"待上传结果缺少有效清单：{folder.name}") from exc
    if not isinstance(data, dict) or not data.get("job_id"):
        raise AgentError(f"待上传结果清单无效：{folder.name}")
    return data


class CloudAgent:
    def __init__(
        self,
        credentials: AgentCredentials,
        settings: AgentSettings,
        client: CloudClient | None = None,
        pipeline: Callable[..., JobResult] = run_pipeline,
    ) -> None:
        self.credentials = credentials
        self.settings = settings
        self.client = client or CloudClient(credentials.server_url, credentials.token)
        self.pipeline = pipeline

    def close(self) -> None:
        self.client.close()

    def tick(self, force: bool = False) -> str:
        self.flush_outbox()
        status = evaluate_idle(self.settings, force=force)
        if not status.ready:
            logger.info("暂不领取任务：%s", "；".join(status.reasons))
            return "idle"
        if not ensure_ollama():
            logger.warning("Ollama 未运行，暂不领取任务")
            return "idle"
        job = self.client.next_job()
        if job is None:
            logger.info("服务器暂无待处理录音")
            return "empty"
        self.process_job(job)
        return "processed"

    def flush_outbox(self) -> int:
        pending = 0
        for folder in sorted(OUTBOX_DIR.iterdir()):
            if not folder.is_dir() or folder.name.startswith(".tmp-"):
                continue
            try:
                outcome = self._upload_folder(folder)
            except AgentError as exc:
                logger.warning("%s", exc)
                _move_to_orphan(folder, str(exc))
                continue
            except Exception:
                logger.exception("刷新待上传结果失败：%s", folder)
                pending += 1
                continue
            if outcome == "pending":
                pending += 1
        if pending:
            logger.info("仍有 %d 份结果等待上传", pending)
        return pending

    def _upload_folder(self, folder: Path) -> str:
        manifest = _load_manifest(folder)
        job_id = str(manifest["job_id"])
        paths = [
            folder / name for name in RESULT_FILE_NAMES if (folder / name).is_file()
        ]
        if not any(path.name == "minutes.md" for path in paths):
            raise AgentError("待上传结果缺少 minutes.md")
        try:
            response = self.client.upload_result(job_id, paths)
        except CloudError as exc:
            if exc.status_code in {404, 409, 410}:
                _move_to_orphan(folder, f"服务器拒绝：{exc}")
                return "orphaned"
            logger.warning("上传结果失败，稍后重试：%s", exc)
            return "pending"
        shutil.rmtree(folder, ignore_errors=True)
        logger.info(
            "结果已同步：job=%s note=%s duplicate=%s",
            job_id,
            response.get("note_id"),
            response.get("duplicate", False),
        )
        return "uploaded"

    def process_job(self, job: dict) -> None:
        job_id = str(job["job_id"])
        recording = job.get("recording") or {}
        recording_id = str(job["recording_id"])
        original = str(recording.get("original_filename") or "")
        audio_path = INBOX_DIR / f"{job_id}{_audio_suffix(original)}"
        logger.info(
            "领取任务 job=%s 标题=%s 大小=%s 时长=%s",
            job_id,
            recording.get("title", ""),
            recording.get("size_bytes", 0),
            recording.get("duration_s"),
        )

        stop = threading.Event()
        lease_seconds = int(job.get("lease_seconds") or 900)
        interval = max(60, min(self.settings.heartbeat_seconds, lease_seconds // 3))
        heartbeat = threading.Thread(
            target=self._heartbeat_loop,
            args=(job_id, interval, stop),
            daemon=True,
            name="cloud-heartbeat",
        )
        heartbeat.start()
        success = False
        try:
            try:
                size, digest = self.client.download_audio(recording_id, audio_path)
            except CloudError as exc:
                raise AgentError(f"下载音频失败：{exc}") from exc
            expected = str(recording.get("sha256") or "").lower()
            if expected and digest != expected:
                raise AgentError("音频完整性校验失败（SHA-256 不一致）")
            logger.info("音频已下载并通过校验：%s 字节", size)

            result = self.pipeline(
                audio_path,
                content_type=str(recording.get("content_type") or "auto"),
                model=self.settings.model,
                asr_device=self.settings.asr_device,
                lock_wait=False,
            )
            folder = save_outbox(job_id, recording_id, result)
            logger.info("本地转写完成：%s（%s）", result.topic, result.output_dir)
            self._upload_folder(folder)
            success = True
        except ProcessingBusy:
            self._fail(job_id, "本机算力正被其他任务占用，稍后重试")
        except AgentError as exc:
            logger.warning("任务失败：%s", exc)
            self._fail(job_id, str(exc))
        except Exception as exc:
            logger.exception("任务处理异常：%s", job_id)
            self._fail(job_id, f"处理失败：{exc}")
        finally:
            stop.set()
            heartbeat.join(timeout=5)
            audio_path.unlink(missing_ok=True)
            logger.info("任务收尾：job=%s success=%s", job_id, success)

    def _fail(self, job_id: str, message: str) -> None:
        try:
            response = self.client.fail(job_id, message)
            logger.info("已回传失败状态：%s → %s", job_id, response.get("status"))
        except CloudError as exc:
            logger.warning("回传失败状态失败（任务可能已超时）：%s", exc)

    def _heartbeat_loop(self, job_id: str, interval: int, stop: threading.Event) -> None:
        while not stop.wait(interval):
            try:
                self.client.heartbeat(job_id)
                logger.debug("心跳成功：%s", job_id)
            except CloudError as exc:
                if exc.status_code == 409:
                    logger.warning("任务租约已失效：%s", job_id)
                    return
                logger.warning("心跳失败，稍后重试：%s", exc)


def collect_status(
    settings: AgentSettings, client: CloudClient
) -> tuple[IdleStatus, dict | None, str]:
    status = evaluate_idle(settings)
    health = None
    error = ""
    try:
        health = client.health()
    except CloudError as exc:
        error = str(exc)
    return status, health, error


def cleanup_inbox(max_age_hours: int = 48) -> int:
    removed = 0
    cutoff = time.time() - max_age_hours * 3600
    for path in INBOX_DIR.iterdir():
        if not path.is_file():
            continue
        try:
            if path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
