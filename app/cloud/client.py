from __future__ import annotations

import hashlib
import mimetypes
from contextlib import ExitStack
from pathlib import Path
from typing import BinaryIO

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(connect=15.0, read=120.0, write=300.0, pool=15.0)


class CloudError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


def _detail(response: httpx.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:300].strip()
    if isinstance(data, dict):
        detail = data.get("detail", data)
        if isinstance(detail, str):
            return detail
        if isinstance(detail, list):
            parts = []
            for item in detail:
                if isinstance(item, dict):
                    parts.append(str(item.get("msg", item)))
                else:
                    parts.append(str(item))
            return "；".join(parts)
        return str(detail)
    return str(data)


def _raise_for(response: httpx.Response) -> None:
    if response.is_success:
        return
    message = _detail(response) or f"HTTP {response.status_code}"
    raise CloudError(f"服务器返回 {response.status_code}：{message}", response.status_code)


class CloudClient:
    def __init__(
        self,
        server_url: str,
        token: str = "",
        timeout: httpx.Timeout = DEFAULT_TIMEOUT,
    ) -> None:
        if not server_url:
            raise CloudError("尚未配置服务器地址")
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        self._client = httpx.Client(
            base_url=server_url.rstrip("/"),
            headers=headers,
            timeout=timeout,
            follow_redirects=True,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "CloudClient":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def health(self) -> dict:
        try:
            response = self._client.get("/health", timeout=20.0)
        except httpx.HTTPError as exc:
            raise CloudError(f"无法连接服务器：{exc}") from exc
        _raise_for(response)
        return response.json()

    def pair(self, code: str, device_name: str) -> dict:
        payload = {"code": code.strip(), "device_name": device_name, "role": "pc"}
        try:
            response = self._client.post("/api/v1/pair", json=payload)
        except httpx.HTTPError as exc:
            raise CloudError(f"无法连接服务器：{exc}") from exc
        _raise_for(response)
        return response.json()

    def me(self) -> dict:
        return self._get_json("/api/v1/me")

    def _get_json(self, path: str) -> dict:
        try:
            response = self._client.get(path)
        except httpx.HTTPError as exc:
            raise CloudError(f"无法连接服务器：{exc}") from exc
        _raise_for(response)
        return response.json()

    def next_job(self) -> dict | None:
        try:
            response = self._client.get("/api/v1/agent/jobs/next")
        except httpx.HTTPError as exc:
            raise CloudError(f"无法连接服务器：{exc}") from exc
        if response.status_code == 204:
            return None
        _raise_for(response)
        return response.json()

    def heartbeat(self, job_id: str) -> dict:
        try:
            response = self._client.post(f"/api/v1/agent/jobs/{job_id}/heartbeat")
        except httpx.HTTPError as exc:
            raise CloudError(f"心跳失败：{exc}") from exc
        _raise_for(response)
        return response.json()

    def download_audio(self, recording_id: str, dest: Path) -> tuple[int, str]:
        dest.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        total = 0
        try:
            with self._client.stream(
                "GET", f"/api/v1/agent/recordings/{recording_id}/audio"
            ) as response:
                if not response.is_success:
                    response.read()
                    _raise_for(response)
                with dest.open("wb") as handle:
                    for block in response.iter_bytes(1024 * 1024):
                        handle.write(block)
                        digest.update(block)
                        total += len(block)
        except httpx.HTTPError as exc:
            dest.unlink(missing_ok=True)
            raise CloudError(f"下载音频失败：{exc}") from exc
        return total, digest.hexdigest()

    def upload_result(self, job_id: str, paths: list[Path]) -> dict:
        files = []
        with ExitStack() as stack:
            for path in paths:
                handle: BinaryIO = stack.enter_context(path.open("rb"))
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                files.append(("files", (path.name, handle, mime)))
            try:
                response = self._client.post(
                    f"/api/v1/agent/jobs/{job_id}/result",
                    files=files,
                    timeout=httpx.Timeout(
                        connect=15.0, read=300.0, write=300.0, pool=15.0
                    ),
                )
            except httpx.HTTPError as exc:
                raise CloudError(f"上传结果失败：{exc}") from exc
        _raise_for(response)
        return response.json()

    def fail(self, job_id: str, error: str) -> dict:
        try:
            response = self._client.post(
                f"/api/v1/agent/jobs/{job_id}/fail",
                json={"error": (error or "未知错误")[:2000]},
            )
        except httpx.HTTPError as exc:
            raise CloudError(f"回传失败状态失败：{exc}") from exc
        _raise_for(response)
        return response.json()

    def import_note(self, payload: dict, paths: list[Path]) -> dict:
        files = []
        with ExitStack() as stack:
            for path in paths:
                handle: BinaryIO = stack.enter_context(path.open("rb"))
                mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                files.append(("files", (path.name, handle, mime)))
            try:
                response = self._client.post(
                    "/api/v1/notes/import",
                    data={key: str(value) for key, value in payload.items()},
                    files=files,
                    timeout=httpx.Timeout(
                        connect=15.0, read=300.0, write=300.0, pool=15.0
                    ),
                )
            except httpx.HTTPError as exc:
                raise CloudError(f"同步本地纪要失败：{exc}") from exc
        _raise_for(response)
        return response.json()
