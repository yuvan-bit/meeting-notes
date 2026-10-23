from __future__ import annotations

import hashlib
import types
from datetime import timedelta

from fastapi.testclient import TestClient

from server.config import Settings
from server.db import connect
from server.utils import iso, utcnow

from .conftest import (
    auth,
    complete,
    create_recording,
    pair,
    submit_result,
    upload_all_chunks,
)


def _expire_lease(settings: Settings, job_id: str) -> None:
    conn = connect(settings.db_path)
    try:
        with conn:
            conn.execute(
                "UPDATE jobs SET lease_expires_at=? WHERE id=?",
                (iso(utcnow() - timedelta(seconds=1)), job_id),
            )
    finally:
        conn.close()


def _job(settings: Settings, job_id: str):
    conn = connect(settings.db_path)
    try:
        return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        conn.close()


def _recording_status(settings: Settings, recording_id: str) -> str:
    conn = connect(settings.db_path)
    try:
        row = conn.execute(
            "SELECT status FROM recordings WHERE id=?", (recording_id,)
        ).fetchone()
        return row["status"]
    finally:
        conn.close()


def _seed(client: TestClient, phone_token: str) -> tuple[dict, bytes]:
    data = b"abcdefgh"
    recording = create_recording(client, phone_token, data)
    upload_all_chunks(client, phone_token, recording, data)
    complete(client, phone_token, recording["recording_id"])
    return recording, data


def test_expired_lease_is_claimed_by_other_pc(client: TestClient, settings: Settings) -> None:
    phone = pair(client, settings, "phone")
    pc1 = pair(client, settings, "pc", "旧电脑")
    pc2 = pair(client, settings, "pc", "新电脑")
    recording, _ = _seed(client, phone["token"])

    first = client.get("/api/v1/agent/jobs/next", headers=auth(pc1["token"]))
    assert first.status_code == 200
    job_id = first.json()["job_id"]
    _expire_lease(settings, job_id)

    stale_heartbeat = client.post(
        f"/api/v1/agent/jobs/{job_id}/heartbeat",
        headers=auth(pc1["token"]),
    )
    assert stale_heartbeat.status_code == 409

    stale_result = client.post(
        f"/api/v1/agent/jobs/{job_id}/result",
        headers=auth(pc1["token"]),
        files=[("files", ("minutes.md", b"# stale\n", "text/markdown"))],
    )
    assert stale_result.status_code == 409

    second = client.get("/api/v1/agent/jobs/next", headers=auth(pc2["token"]))
    assert second.status_code == 200, second.text
    body = second.json()
    assert body["job_id"] == job_id
    assert body["attempts"] == 2

    stale_fail = client.post(
        f"/api/v1/agent/jobs/{job_id}/fail",
        json={"error": "旧进程中断"},
        headers=auth(pc1["token"]),
    )
    assert stale_fail.status_code == 409

    result = submit_result(client, pc2["token"], job_id)
    assert result["status"] == "done"
    assert _recording_status(settings, recording["recording_id"]) == "done"


def test_exhausted_lease_marks_job_and_recording_failed(
    client: TestClient, settings: Settings
) -> None:
    phone = pair(client, settings, "phone")
    pc = pair(client, settings, "pc")
    recording = create_recording(client, phone["token"], b"abcdefgh")
    upload_all_chunks(client, phone["token"], recording, b"abcdefgh")
    job = complete(client, phone["token"], recording["recording_id"])
    job_id = job["job_id"]

    for expected in range(1, settings.max_attempts + 1):
        claimed = client.get("/api/v1/agent/jobs/next", headers=auth(pc["token"]))
        assert claimed.status_code == 200
        assert claimed.json()["attempts"] == expected
        _expire_lease(settings, job_id)

    exhausted = client.get("/api/v1/agent/jobs/next", headers=auth(pc["token"]))
    assert exhausted.status_code == 204
    row = _job(settings, job_id)
    assert row["status"] == "failed"
    assert _recording_status(settings, recording["recording_id"]) == "failed"


def test_duplicate_result_returns_same_note(client: TestClient, settings: Settings) -> None:
    phone = pair(client, settings, "phone")
    pc = pair(client, settings, "pc")
    recording, _ = _seed(client, phone["token"])
    claimed = client.get("/api/v1/agent/jobs/next", headers=auth(pc["token"]))
    job_id = claimed.json()["job_id"]

    first = submit_result(client, pc["token"], job_id)
    second = submit_result(client, pc["token"], job_id)
    assert second["duplicate"] is True
    assert second["note_id"] == first["note_id"]

    notes = client.get("/api/v1/notes", headers=auth(phone["token"]))
    assert notes.json()["total"] == 1
    assert _recording_status(settings, recording["recording_id"]) == "done"


def test_complete_is_idempotent(client: TestClient, settings: Settings) -> None:
    phone = pair(client, settings, "phone")
    recording = create_recording(client, phone["token"], b"abcdefgh")
    upload_all_chunks(client, phone["token"], recording, b"abcdefgh")
    first = complete(client, phone["token"], recording["recording_id"])
    second = complete(client, phone["token"], recording["recording_id"])
    assert second["job_id"] == first["job_id"]
    assert second["status"] == "queued"


def test_chunk_status_supports_resume(client: TestClient, settings: Settings) -> None:
    phone = pair(client, settings, "phone")
    other = pair(client, settings, "phone", "另一台手机")
    data = b"abcdefgh"
    recording = create_recording(client, phone["token"], data)
    recording_id = recording["recording_id"]

    chunk = data[4:8]
    upload = client.put(
        f"/api/v1/recordings/{recording_id}/chunks/1",
        content=chunk,
        headers={
            **auth(phone["token"]),
            "X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest(),
        },
    )
    assert upload.status_code == 200

    status = client.get(
        f"/api/v1/recordings/{recording_id}/chunks",
        headers=auth(phone["token"]),
    )
    assert status.status_code == 200
    body = status.json()
    assert body["uploaded"] == [1]
    assert body["missing"] == [0]

    hidden = client.get(
        f"/api/v1/recordings/{recording_id}/chunks",
        headers=auth(other["token"]),
    )
    assert hidden.status_code == 404


def test_disk_full_rejects_create_chunk_and_assemble(
    client: TestClient, settings: Settings, monkeypatch
) -> None:
    phone = pair(client, settings, "phone")
    data = b"abcdefgh"

    def no_space(_path):
        return types.SimpleNamespace(free=0, total=1, used=1)

    monkeypatch.setattr("server.routers.recordings.shutil.disk_usage", no_space)
    rejected = client.post(
        "/api/v1/recordings",
        json={
            "title": "磁盘满",
            "content_type": "meeting",
            "filename": "demo.m4a",
            "size_bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
            "client_upload_id": "disk-full",
        },
        headers=auth(phone["token"]),
    )
    assert rejected.status_code == 507

    monkeypatch.undo()
    recording = create_recording(client, phone["token"], data)

    monkeypatch.setattr("server.routers.recordings.shutil.disk_usage", no_space)
    chunk = data[:4]
    blocked_chunk = client.put(
        f"/api/v1/recordings/{recording['recording_id']}/chunks/0",
        content=chunk,
        headers={
            **auth(phone["token"]),
            "X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest(),
        },
    )
    assert blocked_chunk.status_code == 507

    monkeypatch.undo()
    upload_all_chunks(client, phone["token"], recording, data)

    monkeypatch.setattr("server.routers.recordings.shutil.disk_usage", no_space)
    blocked_complete = client.post(
        f"/api/v1/recordings/{recording['recording_id']}/complete",
        headers=auth(phone["token"]),
    )
    assert blocked_complete.status_code == 507
