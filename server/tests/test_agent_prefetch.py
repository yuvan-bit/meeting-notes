from __future__ import annotations

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


def _queued_job(client: TestClient, settings: Settings) -> tuple[str, str, str, bytes]:
    phone = pair(client, settings, "phone")
    pc = pair(client, settings, "pc", "书桌电脑")
    data = b"prefetch audio bytes"
    recording = create_recording(client, phone["token"], data)
    upload_all_chunks(client, phone["token"], recording, data)
    completed = complete(client, phone["token"], recording["recording_id"])
    return phone["token"], pc["token"], completed["job_id"], data


def test_queued_jobs_are_listed_without_leasing(client: TestClient, settings: Settings) -> None:
    _, pc_token, job_id, data = _queued_job(client, settings)

    response = client.get("/api/v1/agent/jobs/queued", headers=auth(pc_token))
    assert response.status_code == 200, response.text
    items = response.json()["items"]
    assert len(items) == 1
    item = items[0]
    assert item["job_id"] == job_id
    assert item["attempts"] == 0
    assert item["recording"]["size_bytes"] == len(data)
    assert item["recording"]["audio_url"].endswith(f"/agent/recordings/{item['recording_id']}/audio")

    claimed = client.get("/api/v1/agent/jobs/next", headers=auth(pc_token))
    assert claimed.status_code == 200, claimed.text
    assert claimed.json()["job_id"] == job_id
    assert claimed.json()["attempts"] == 1


def test_queued_job_accepts_offline_result_without_claim(
    client: TestClient, settings: Settings
) -> None:
    phone_token, pc_token, job_id, _ = _queued_job(client, settings)

    result = submit_result(client, pc_token, job_id)
    assert result["status"] == "done"
    assert result["duplicate"] is False

    listing = client.get("/api/v1/notes", headers=auth(phone_token))
    assert listing.status_code == 200
    assert listing.json()["total"] == 1

    # 离线结果不应消耗任务尝试次数
    from server.db import connect

    conn = connect(settings.db_path)
    try:
        row = conn.execute("SELECT status, attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
    finally:
        conn.close()
    assert row["status"] == "done"
    assert row["attempts"] == 0


def test_new_recording_bumps_notification(client: TestClient, settings: Settings) -> None:
    from server import notify

    phone = pair(client, settings, "phone")
    pc = pair(client, settings, "pc", "书桌电脑")
    before = notify.current_version()

    data = b"notification audio"
    recording = create_recording(client, phone["token"], data)
    upload_all_chunks(client, phone["token"], recording, data)
    complete(client, phone["token"], recording["recording_id"])

    response = client.get(
        "/api/v1/agent/notifications",
        params={"since": before, "wait": 0},
        headers=auth(pc["token"]),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["changed"] is True
    assert body["version"] > before

    current = body["version"]
    quiet = client.get(
        "/api/v1/agent/notifications",
        params={"since": current, "wait": 0},
        headers=auth(pc["token"]),
    )
    assert quiet.status_code == 200
    assert quiet.json()["changed"] is False


def test_notification_long_poll_wakes_on_bump(
    client: TestClient, settings: Settings
) -> None:
    import threading
    import time

    from server import notify

    pc = pair(client, settings, "pc", "书桌电脑")
    since = notify.current_version()
    result: dict = {}

    def wait_for_notification() -> None:
        result["response"] = client.get(
            "/api/v1/agent/notifications",
            params={"since": since, "wait": 3},
            headers=auth(pc["token"]),
        )

    thread = threading.Thread(target=wait_for_notification)
    thread.start()
    time.sleep(0.3)
    notify.bump()
    thread.join(timeout=5)
    assert not thread.is_alive()
    response = result["response"]
    assert response.status_code == 200
    assert response.json()["changed"] is True
