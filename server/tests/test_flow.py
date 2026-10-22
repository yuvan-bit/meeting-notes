from __future__ import annotations

import hashlib

from fastapi.testclient import TestClient

from server.config import Settings

from .conftest import (
    auth,
    complete,
    create_recording,
    pair,
    submit_result,
    upload_all_chunks,
)


def test_record_upload_and_agent_flow(client: TestClient, settings: Settings) -> None:
    phone = pair(client, settings, "phone")
    pc = pair(client, settings, "pc", "书桌电脑")
    data = b"hello meeting audio"

    recording = create_recording(client, phone["token"], data)
    assert recording["created"] is True
    upload_all_chunks(client, phone["token"], recording, data)

    # 重复分片应幂等
    duplicate = client.put(
        f"/api/v1/recordings/{recording['recording_id']}/chunks/0",
        content=data[:4],
        headers={
            **auth(phone["token"]),
            "X-Chunk-SHA256": hashlib.sha256(data[:4]).hexdigest(),
        },
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True

    completed = complete(client, phone["token"], recording["recording_id"])
    assert completed["status"] == "queued"
    job_id = completed["job_id"]

    claimed = client.get("/api/v1/agent/jobs/next", headers=auth(pc["token"]))
    assert claimed.status_code == 200
    claimed_body = claimed.json()
    assert claimed_body["job_id"] == job_id
    assert claimed_body["attempts"] == 1

    heartbeat = client.post(
        f"/api/v1/agent/jobs/{job_id}/heartbeat",
        headers=auth(pc["token"]),
    )
    assert heartbeat.status_code == 200

    audio = client.get(
        claimed_body["recording"]["audio_url"],
        headers=auth(pc["token"]),
    )
    assert audio.status_code == 200
    assert audio.content == data

    result = submit_result(client, pc["token"], job_id)
    assert result["status"] == "done"
    assert result["note_id"]

    listing = client.get("/api/v1/notes", headers=auth(phone["token"]))
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    item = listing.json()["items"][0]
    assert item["topic"] == "勾股定理"
    assert item["audio_available"] is True

    detail = client.get(f"/api/v1/notes/{job_id}", headers=auth(phone["token"]))
    assert detail.status_code == 200
    assert "勾股定理" in detail.json()["minutes_markdown"]
    assert detail.json()["files"]

    file_response = client.get(
        f"/api/v1/notes/{job_id}/files/minutes.md",
        headers=auth(phone["token"]),
    )
    assert file_response.status_code == 200
    assert "勾股定理" in file_response.text

    pinned = client.post(
        f"/api/v1/notes/{job_id}/pin",
        json={"pinned": True},
        headers=auth(phone["token"]),
    )
    assert pinned.status_code == 200
    assert pinned.json()["pinned"] is True


def test_client_upload_id_is_idempotent(client: TestClient, settings: Settings) -> None:
    phone = pair(client, settings, "phone")
    data = b"abcdefgh"
    first = create_recording(client, phone["token"], data)
    second = create_recording(client, phone["token"], data)
    assert second["recording_id"] == first["recording_id"]
    assert second["created"] is False


def test_claim_has_no_job_twice(client: TestClient, settings: Settings) -> None:
    phone = pair(client, settings, "phone")
    pc = pair(client, settings, "pc")
    data = b"abcdefgh"
    recording = create_recording(client, phone["token"], data)
    upload_all_chunks(client, phone["token"], recording, data)
    complete(client, phone["token"], recording["recording_id"])

    first = client.get("/api/v1/agent/jobs/next", headers=auth(pc["token"]))
    assert first.status_code == 200
    second = client.get("/api/v1/agent/jobs/next", headers=auth(pc["token"]))
    assert second.status_code == 204
