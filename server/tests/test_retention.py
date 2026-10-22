from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from server.cleanup import cleanup
from server.config import Settings
from server.db import connect, init_db
from server.main import create_app

from .conftest import (
    auth,
    complete,
    create_recording,
    pair,
    submit_result,
    upload_all_chunks,
)


def _prepare(tmp_path: Path, audio_max_bytes: int, retention_days: int = 30):
    settings = Settings.create(
        tmp_path / "retention",
        pairing_pepper="test-pepper",
        chunk_size=4,
        max_chunk_bytes=8,
        max_upload_bytes=1024,
        audio_max_bytes=audio_max_bytes,
        audio_retention_days=retention_days,
    )
    settings.ensure_dirs()
    init_db(settings.db_path)
    app = create_app(settings)
    return settings, TestClient(app)


def test_cleanup_removes_audio_but_keeps_note(tmp_path: Path) -> None:
    settings, client = _prepare(tmp_path, audio_max_bytes=0)
    with client:
        phone = pair(client, settings, "phone")
        pc = pair(client, settings, "pc")
        data = b"abcdefgh"
        recording = create_recording(client, phone["token"], data)
        upload_all_chunks(client, phone["token"], recording, data)
        job = complete(client, phone["token"], recording["recording_id"])
        claimed = client.get("/api/v1/agent/jobs/next", headers=auth(pc["token"]))
        assert claimed.status_code == 200, claimed.text
        submit_result(client, pc["token"], job["job_id"])

        stats = cleanup(settings)
        assert stats["audio_deleted"] == 1
        audio = client.get(
            f"/api/v1/recordings/{recording['recording_id']}/audio",
            headers=auth(phone["token"]),
        )
        assert audio.status_code == 410
        note = client.get(f"/api/v1/notes/{job['job_id']}", headers=auth(phone["token"]))
        assert note.status_code == 200


def test_pinned_audio_is_not_cleaned(tmp_path: Path) -> None:
    settings, client = _prepare(tmp_path, audio_max_bytes=0)
    with client:
        phone = pair(client, settings, "phone")
        pc = pair(client, settings, "pc")
        data = b"abcdefgh"
        recording = create_recording(client, phone["token"], data)
        upload_all_chunks(client, phone["token"], recording, data)
        job = complete(client, phone["token"], recording["recording_id"])
        claimed = client.get("/api/v1/agent/jobs/next", headers=auth(pc["token"]))
        assert claimed.status_code == 200, claimed.text
        submit_result(client, pc["token"], job["job_id"])
        client.post(
            f"/api/v1/notes/{job['job_id']}/pin",
            json={"pinned": True},
            headers=auth(phone["token"]),
        )

        stats = cleanup(settings)
        assert stats["audio_deleted"] == 0
        audio = client.get(
            f"/api/v1/recordings/{recording['recording_id']}/audio",
            headers=auth(phone["token"]),
        )
        assert audio.status_code == 200
