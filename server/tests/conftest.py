from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.config import Settings
from server.db import connect, init_db
from server.main import create_app
from server.pairing import issue_pairing_code


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    value = Settings.create(
        tmp_path / "data",
        pairing_pepper="test-pepper",
        chunk_size=4,
        max_chunk_bytes=8,
        max_upload_bytes=1024,
        audio_retention_days=30,
    )
    value.ensure_dirs()
    init_db(value.db_path)
    return value


@pytest.fixture
def client(settings: Settings):
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client


def make_pairing_code(settings: Settings, role: str = "phone") -> str:
    conn = connect(settings.db_path)
    try:
        code, _ = issue_pairing_code(conn, settings, role)
        return code
    finally:
        conn.close()


def pair(client: TestClient, settings: Settings, role: str = "phone", name: str = "test-device"):
    code = make_pairing_code(settings, role)
    response = client.post(
        "/api/v1/pair",
        json={"code": code, "device_name": name, "role": role},
    )
    assert response.status_code == 201, response.text
    return response.json()


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_recording(client: TestClient, token: str, data: bytes, **overrides):
    payload = {
        "title": "测试会议",
        "content_type": "meeting",
        "filename": "demo.m4a",
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "client_upload_id": "upload-1",
    }
    payload.update(overrides)
    response = client.post("/api/v1/recordings", json=payload, headers=auth(token))
    assert response.status_code == 201, response.text
    return response.json()


def upload_all_chunks(client: TestClient, token: str, recording: dict, data: bytes) -> None:
    chunk_size = recording["chunk_size"]
    for idx, offset in enumerate(range(0, len(data), chunk_size)):
        chunk = data[offset : offset + chunk_size]
        response = client.put(
            f"/api/v1/recordings/{recording['recording_id']}/chunks/{idx}",
            content=chunk,
            headers={
                **auth(token),
                "X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest(),
            },
        )
        assert response.status_code == 200, response.text


def complete(client: TestClient, token: str, recording_id: str) -> dict:
    response = client.post(
        f"/api/v1/recordings/{recording_id}/complete",
        headers=auth(token),
    )
    assert response.status_code == 200, response.text
    return response.json()


def submit_result(client: TestClient, token: str, job_id: str, content_type: str = "meeting") -> dict:
    minutes = "# 课程笔记\n\n## 一句话概括\n勾股定理及其应用\n\n## 核心概念\n直角三角形成立。\n"
    meta = {
        "content_type": content_type,
        "topic": "勾股定理",
        "summary": "勾股定理及其应用",
    }
    files = [
        ("files", ("minutes.md", minutes.encode("utf-8"), "text/markdown")),
        ("files", ("transcript.md", b"# transcript\n", "text/markdown")),
        ("files", ("transcript.txt", b"transcript\n", "text/plain")),
        ("files", ("transcript.json", b"[]", "application/json")),
        ("files", ("meta.json", json.dumps(meta).encode("utf-8"), "application/json")),
    ]
    response = client.post(
        f"/api/v1/agent/jobs/{job_id}/result",
        headers=auth(token),
        files=files,
    )
    assert response.status_code == 200, response.text
    return response.json()
