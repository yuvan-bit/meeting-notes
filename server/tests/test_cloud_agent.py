from __future__ import annotations

import hashlib
import json
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest
import uvicorn

from app.cloud import agent as agent_module
from app.cloud.config import AgentSettings
from app.cloud.store import AgentCredentials
from app.pipeline import JobResult
from server.config import Settings
from server.db import connect, init_db
from server.main import create_app
from server.pairing import create_device

AUDIO_DATA = b"fake-m4a-audio-bytes-for-agent-test"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def live_server(tmp_path: Path):
    settings = Settings.create(
        tmp_path / "server-data",
        pairing_pepper="test-pepper",
        chunk_size=4,
        max_chunk_bytes=8,
        max_upload_bytes=1024 * 1024,
        audio_retention_days=30,
    )
    settings.ensure_dirs()
    init_db(settings.db_path)
    app = create_app(settings)
    port = _free_port()
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    )
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 15
    while not server.started:
        if time.time() > deadline:
            raise RuntimeError("测试服务器启动超时")
        time.sleep(0.05)
    try:
        yield settings, f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=10)


@pytest.fixture
def devices(live_server):
    settings, base_url = live_server
    conn = connect(settings.db_path)
    try:
        phone_id, phone_token = create_device(conn, "phone", "phone")
        pc_id, pc_token = create_device(conn, "pc", "pc")
    finally:
        conn.close()
    return settings, base_url, phone_id, phone_token, pc_id, pc_token


def _seed_recording(base_url: str, token: str, data: bytes) -> dict:
    response = httpx.post(
        f"{base_url}/api/v1/recordings",
        json={
            "title": "云代理测试会议",
            "content_type": "meeting",
            "filename": "demo.m4a",
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "client_upload_id": "agent-test-upload",
        },
        headers=_auth(token),
        timeout=10,
    )
    assert response.status_code == 201, response.text
    recording = response.json()
    chunk_size = recording["chunk_size"]
    for idx, offset in enumerate(range(0, len(data), chunk_size)):
        chunk = data[offset : offset + chunk_size]
        response = httpx.put(
            f"{base_url}/api/v1/recordings/{recording['recording_id']}/chunks/{idx}",
            content=chunk,
            headers={
                **_auth(token),
                "X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest(),
            },
            timeout=10,
        )
        assert response.status_code == 200, response.text
    response = httpx.post(
        f"{base_url}/api/v1/recordings/{recording['recording_id']}/complete",
        headers=_auth(token),
        timeout=10,
    )
    assert response.status_code == 200, response.text
    return response.json()


def _fake_pipeline_factory(tmp_path: Path, expected: bytes):
    out_dir = tmp_path / "pipeline-output"
    out_dir.mkdir()
    minutes = (
        "# 会议纪要\n\n## 一句话摘要\n讨论了发布计划\n\n"
        "## 会议主题\n发布计划\n\n## 待办\n- 周五前完成灰度\n"
    )
    (out_dir / "minutes.md").write_text(minutes, encoding="utf-8")
    (out_dir / "transcript.md").write_text("# 转写稿\n发布计划讨论\n", encoding="utf-8")
    (out_dir / "transcript.txt").write_text("发布计划讨论\n", encoding="utf-8")
    (out_dir / "transcript.srt").write_text("1\n00:00:00,000 --> 00:00:02,000\n发布计划讨论\n", encoding="utf-8")
    (out_dir / "transcript.json").write_text("[]", encoding="utf-8")
    (out_dir / "meta.json").write_text(
        json.dumps(
            {
                "content_type": "meeting",
                "topic": "发布计划",
                "summary": "讨论了发布计划",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    def fake_pipeline(input_path, **kwargs):
        assert Path(input_path).read_bytes() == expected
        assert kwargs.get("lock_wait") is False
        files = {
            "minutes": str(out_dir / "minutes.md"),
            "transcript_md": str(out_dir / "transcript.md"),
            "transcript_txt": str(out_dir / "transcript.txt"),
            "transcript_srt": str(out_dir / "transcript.srt"),
            "transcript_json": str(out_dir / "transcript.json"),
            "job_json": str(out_dir / "meta.json"),
        }
        return JobResult(
            job_id="local-pipeline-job",
            input_name="demo.m4a",
            duration_s=3.0,
            asr_device="cpu",
            summary_model="fake",
            summary_num_gpu=None,
            summary_chunks=0,
            elapsed_s=0.1,
            output_dir=str(out_dir),
            content_type="meeting",
            content_type_label="会议",
            topic="发布计划",
            summary="讨论了发布计划",
            created_at="2026-10-23T00:00:00",
            files=files,
        )

    return fake_pipeline


def _agent(tmp_path: Path, monkeypatch, base_url: str, pc_id: str, pc_token: str, pipeline):
    for name in ("OUTBOX_DIR", "INBOX_DIR", "ORPHAN_DIR"):
        target = tmp_path / name.lower()
        target.mkdir()
        monkeypatch.setattr(agent_module, name, target)
    credentials = AgentCredentials(
        server_url=base_url,
        device_id=pc_id,
        device_name="pc",
        role="pc",
        token=pc_token,
        paired_at="2026-10-23T00:00:00",
    )
    settings = AgentSettings(
        server_url=base_url,
        idle_seconds=0,
        require_ac=False,
        cpu_max_percent=None,
        gpu_max_util=None,
        heartbeat_seconds=60,
        model="fake",
        asr_device="cpu",
    )
    from app.cloud.agent import CloudAgent

    return CloudAgent(credentials, settings, pipeline=pipeline)


def test_agent_full_cycle_over_http(devices, tmp_path: Path, monkeypatch) -> None:
    settings, base_url, phone_id, phone_token, pc_id, pc_token = devices
    _seed_recording(base_url, phone_token, AUDIO_DATA)
    pipeline = _fake_pipeline_factory(tmp_path, AUDIO_DATA)
    agent = _agent(tmp_path, monkeypatch, base_url, pc_id, pc_token, pipeline)
    try:
        assert agent.tick(force=True) == "processed"
    finally:
        agent.close()

    notes = httpx.get(
        f"{base_url}/api/v1/notes", headers=_auth(phone_token), timeout=10
    ).json()
    assert notes["total"] == 1
    item = notes["items"][0]
    assert item["topic"] == "发布计划"
    assert item["content_type"] == "meeting"
    assert item["audio_available"] is True

    detail = httpx.get(
        f"{base_url}/api/v1/notes/{item['job_id']}",
        headers=_auth(phone_token),
        timeout=10,
    ).json()
    assert "发布计划" in detail["minutes_markdown"]
    names = {entry["name"] for entry in detail["files"]}
    assert {"minutes.md", "transcript.md", "meta.json"} <= names

    transcript = httpx.get(
        f"{base_url}/api/v1/notes/{item['job_id']}/files/transcript.md",
        headers=_auth(phone_token),
        timeout=10,
    )
    assert transcript.status_code == 200
    assert "发布计划讨论" in transcript.text

    audio = httpx.get(
        f"{base_url}/api/v1/recordings/{item['recording_id']}/audio",
        headers=_auth(phone_token),
        timeout=10,
    )
    assert audio.status_code == 200
    assert audio.content == AUDIO_DATA

    assert list(agent_module.OUTBOX_DIR.iterdir()) == []
    assert list(agent_module.INBOX_DIR.iterdir()) == []


def test_agent_orphans_result_when_server_rejects(devices, tmp_path: Path, monkeypatch) -> None:
    settings, base_url, phone_id, phone_token, pc_id, pc_token = devices
    pipeline = _fake_pipeline_factory(tmp_path, AUDIO_DATA)
    agent = _agent(tmp_path, monkeypatch, base_url, pc_id, pc_token, pipeline)
    try:
        folder = agent_module.OUTBOX_DIR / "job_missing"
        folder.mkdir()
        (folder / "minutes.md").write_text("# 会议纪要\n", encoding="utf-8")
        (folder / "manifest.json").write_text(
            json.dumps({"job_id": "job_missing", "recording_id": "rec_missing"}),
            encoding="utf-8",
        )
        assert agent.flush_outbox() == 0
    finally:
        agent.close()
    assert not folder.exists()
    orphaned = list(agent_module.ORPHAN_DIR.iterdir())
    assert len(orphaned) == 1
    assert (orphaned[0] / "minutes.md").is_file()
