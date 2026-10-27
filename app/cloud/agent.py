from __future__ import annotations

import json
import logging
import shutil
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
    PREFETCH_DIR,
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
PREFETCH_MANIFEST = "manifest.json"
MAX_LOCAL_FAILURES = 3
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
        self.prefetch_jobs()
        status = evaluate_idle(self.settings, force=force)
        if not status.ready:
            logger.info("暂不领取任务：%s", "；".join(status.reasons))
            return "idle"
        if not ensure_ollama():
            logger.warning("Ollama 未运行，暂不转写")
            return "idle"
        folder = self.next_local_job()
        if folder is None:
            logger.info("本地没有待转写音频")
            return "empty"
        self.process_local_job(folder)
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
            if exc.status_code in {404, 410}:
                _move_to_orphan(folder, f"服务器拒绝：{exc}")
                return "orphaned"
            if exc.status_code == 409:
                logger.info("任务暂不可上传，稍后重试：%s", exc)
                return "pending"
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

    def prefetch_jobs(self) -> int:
        PREFETCH_DIR.mkdir(parents=True, exist_ok=True)
        local = self._local_jobs()
        if len(local) >= self.settings.prefetch_limit:
            return 0
        try:
            items = self.client.queued_jobs(
                limit=max(3, self.settings.prefetch_limit + 2)
            )
        except CloudError as exc:
            logger.warning("暂时无法预取音频：%s", exc)
            return 0

        for item in items:
            job_id = str(item.get("job_id") or "")
            if not job_id:
                continue
            if (
                job_id in local
                or (OUTBOX_DIR / job_id).exists()
                or self._is_orphaned(job_id)
            ):
                continue
            try:
                self._prefetch_job(item)
                logger.info("已预取音频：job=%s", job_id)
                return 1
            except (CloudError, AgentError, OSError, ValueError) as exc:
                logger.warning("预取音频失败：job=%s %s", job_id, exc)
        return 0

    def _prefetch_job(self, item: dict) -> None:
        job_id = str(item["job_id"])
        recording_id = str(item["recording_id"])
        recording = item.get("recording") or {}
        if not isinstance(recording, dict):
            raise AgentError("任务缺少录音信息")
        suffix = _audio_suffix(str(recording.get("original_filename") or ""))
        target = PREFETCH_DIR / job_id
        temp = PREFETCH_DIR / f".tmp-{job_id}-{int(time.time())}"
        shutil.rmtree(temp, ignore_errors=True)
        temp.mkdir(parents=True, exist_ok=False)
        audio = temp / f"audio{suffix}"
        try:
            size, digest = self.client.download_audio(recording_id, audio)
            expected_size = int(recording.get("size_bytes") or 0)
            expected_hash = str(recording.get("sha256") or "").lower()
            if expected_size and size != expected_size:
                raise AgentError(f"音频大小不一致：{size}/{expected_size}")
            if expected_hash and digest != expected_hash:
                raise AgentError("音频完整性校验失败（SHA-256 不一致）")
            manifest = {
                "job_id": job_id,
                "recording_id": recording_id,
                "recording": recording,
                "audio_file": audio.name,
                "downloaded_at": datetime.now().replace(microsecond=0).isoformat(),
                "failures": 0,
            }
            (temp / PREFETCH_MANIFEST).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            if target.exists():
                shutil.rmtree(target, ignore_errors=True)
            temp.replace(target)
        except Exception:
            shutil.rmtree(temp, ignore_errors=True)
            raise

    def _local_jobs(self) -> set[str]:
        if not PREFETCH_DIR.is_dir():
            return set()
        return {
            folder.name
            for folder in PREFETCH_DIR.iterdir()
            if folder.is_dir() and not folder.name.startswith(".tmp-")
        }

    def next_local_job(self) -> Path | None:
        if not PREFETCH_DIR.is_dir():
            return None
        folders = [
            folder
            for folder in PREFETCH_DIR.iterdir()
            if folder.is_dir() and not folder.name.startswith(".tmp-")
        ]
        folders.sort(key=lambda folder: folder.stat().st_mtime)
        for folder in folders:
            manifest_path = folder / PREFETCH_MANIFEST
            if not manifest_path.is_file():
                _move_to_orphan(folder, "预取目录缺少清单")
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                _move_to_orphan(folder, "预取清单无法读取")
                continue
            if not isinstance(manifest, dict):
                _move_to_orphan(folder, "预取清单格式无效")
                continue
            audio_name = str(manifest.get("audio_file") or "")
            if not audio_name or not (folder / audio_name).is_file():
                _move_to_orphan(folder, "预取音频缺失")
                continue
            return folder
        return None

    def process_local_job(self, folder: Path) -> None:
        try:
            manifest = json.loads(
                (folder / PREFETCH_MANIFEST).read_text(encoding="utf-8")
            )
        except (OSError, ValueError) as exc:
            _move_to_orphan(folder, f"预取清单无法读取：{exc}")
            return
        if not isinstance(manifest, dict):
            _move_to_orphan(folder, "预取清单格式无效")
            return
        job_id = str(manifest.get("job_id") or folder.name)
        recording_id = str(manifest.get("recording_id") or "")
        recording = manifest.get("recording") or {}
        if not isinstance(recording, dict):
            recording = {}
        audio = folder / str(manifest.get("audio_file") or "")
        logger.info(
            "开始本地转写 job=%s 标题=%s 大小=%s 时长=%s",
            job_id,
            recording.get("title", ""),
            recording.get("size_bytes", 0),
            recording.get("duration_s"),
        )
        try:
            result = self.pipeline(
                audio,
                content_type=str(recording.get("content_type") or "auto"),
                model=self.settings.model,
                asr_device=self.settings.asr_device,
                lock_wait=False,
            )
            outbox = save_outbox(job_id, recording_id, result)
            logger.info("本地转写完成：%s（%s）", result.topic, result.output_dir)
            try:
                self._upload_folder(outbox)
            except AgentError as exc:
                logger.warning("结果上传失败，保留待重试：%s", exc)
            shutil.rmtree(folder, ignore_errors=True)
            logger.info("本地任务完成：job=%s", job_id)
        except ProcessingBusy:
            logger.warning("本机算力正被其他任务占用，稍后重试：%s", job_id)
        except Exception as exc:
            logger.exception("本地转写失败：%s", job_id)
            self._record_local_failure(folder, manifest, exc)

    def _record_local_failure(self, folder: Path, manifest: dict, exc: Exception) -> None:
        failures = int(manifest.get("failures") or 0) + 1
        manifest["failures"] = failures
        manifest["last_error"] = str(exc)[:500]
        try:
            (folder / PREFETCH_MANIFEST).write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass
        if failures >= MAX_LOCAL_FAILURES:
            _move_to_orphan(folder, f"本地转写失败 {failures} 次：{exc}")
        else:
            logger.warning(
                "本地转写失败 %d/%d，保留待重试：%s",
                failures,
                MAX_LOCAL_FAILURES,
                folder.name,
            )

    def _is_orphaned(self, job_id: str) -> bool:
        if not ORPHAN_DIR.is_dir():
            return False
        prefix = f"{job_id}_"
        return any(
            path.is_dir() and path.name.startswith(prefix)
            for path in ORPHAN_DIR.iterdir()
        )


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
