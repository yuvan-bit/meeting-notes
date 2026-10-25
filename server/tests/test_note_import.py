from __future__ import annotations

from fastapi.testclient import TestClient

from server.config import Settings

from .conftest import auth, pair


def import_note(
    client: TestClient,
    token: str,
    *,
    local_id: str = "job_20261024_0101",
    title: str = "项目周会",
    created_at: str = "2026-10-23T17:01:00Z",
    minutes: str = "# 项目周会\n\n## 一句话概括\n讨论项目进度与分工。\n",
    extra_files: list[tuple[str, bytes, str]] | None = None,
):
    files = [("files", ("minutes.md", minutes.encode("utf-8"), "text/markdown"))]
    if extra_files is None:
        extra_files = [
            ("transcript.md", b"# transcript\n", "text/markdown"),
            ("transcript.txt", b"transcript\n", "text/plain"),
        ]
    files.extend(("files", item) for item in extra_files)
    data = {
        "local_id": local_id,
        "title": title,
        "content_type": "meeting",
        "topic": title,
        "summary": "讨论项目进度与分工",
        "duration_s": "1468.44",
        "created_at": created_at,
    }
    return client.post(
        "/api/v1/notes/import",
        data=data,
        files=files,
        headers=auth(token),
    )


def test_pc_can_import_local_note(client: TestClient, settings: Settings) -> None:
    phone = pair(client, settings, "phone")
    pc = pair(client, settings, "pc", "书桌电脑")

    response = import_note(client, pc["token"])
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["status"] == "done"
    assert body["duplicate"] is False
    assert {item["name"] for item in body["files"]} == {
        "minutes.md",
        "transcript.md",
        "transcript.txt",
    }

    listing = client.get("/api/v1/notes", headers=auth(phone["token"]))
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    item = listing.json()["items"][0]
    assert item["job_id"] == body["job_id"]
    assert item["topic"] == "项目周会"
    assert item["content_type"] == "meeting"
    assert item["duration_s"] == 1468.44
    assert item["created_at"] == "2026-10-23T17:01:00Z"
    assert item["audio_available"] is False
    assert item["files"]

    detail = client.get(f"/api/v1/notes/{body['job_id']}", headers=auth(phone["token"]))
    assert detail.status_code == 200
    assert "讨论项目进度与分工" in detail.json()["minutes_markdown"]

    download = client.get(
        f"/api/v1/notes/{body['job_id']}/files/minutes.md",
        headers=auth(phone["token"]),
    )
    assert download.status_code == 200
    assert "项目周会" in download.text


def test_reimport_is_idempotent_and_refreshes(client: TestClient, settings: Settings) -> None:
    phone = pair(client, settings, "phone")
    pc = pair(client, settings, "pc")

    first = import_note(client, pc["token"])
    assert first.status_code == 201
    job_id = first.json()["job_id"]

    second = import_note(
        client,
        pc["token"],
        title="项目周会（更新）",
        minutes="# 项目周会\n\n## 一句话概括\n补充了新的分工安排。\n",
    )
    assert second.status_code == 201, second.text
    assert second.json()["duplicate"] is True
    assert second.json()["job_id"] == job_id

    listing = client.get("/api/v1/notes", headers=auth(phone["token"]))
    assert listing.json()["total"] == 1
    item = listing.json()["items"][0]
    assert item["topic"] == "项目周会（更新）"

    detail = client.get(f"/api/v1/notes/{job_id}", headers=auth(phone["token"]))
    assert "补充了新的分工安排" in detail.json()["minutes_markdown"]


def test_phone_token_cannot_import(client: TestClient, settings: Settings) -> None:
    phone = pair(client, settings, "phone")
    response = import_note(client, phone["token"])
    assert response.status_code == 403


def test_import_requires_minutes(client: TestClient, settings: Settings) -> None:
    pc = pair(client, settings, "pc")
    response = client.post(
        "/api/v1/notes/import",
        data={"local_id": "job_without_minutes", "title": "无纪要"},
        files=[("files", ("transcript.txt", b"transcript\n", "text/plain"))],
        headers=auth(pc["token"]),
    )
    assert response.status_code == 400
    assert "minutes.md" in response.json()["detail"]


def test_import_rejects_unknown_files(client: TestClient, settings: Settings) -> None:
    pc = pair(client, settings, "pc")
    response = import_note(
        client,
        pc["token"],
        extra_files=[("evil.exe", b"MZ", "application/octet-stream")],
    )
    assert response.status_code == 400


def test_imports_are_scoped_per_device(client: TestClient, settings: Settings) -> None:
    phone = pair(client, settings, "phone")
    first_pc = pair(client, settings, "pc", "电脑甲")
    second_pc = pair(client, settings, "pc", "电脑乙")

    first = import_note(client, first_pc["token"], local_id="same-local-id")
    second = import_note(client, second_pc["token"], local_id="same-local-id")
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["job_id"] != second.json()["job_id"]
    assert second.json()["duplicate"] is False

    listing = client.get("/api/v1/notes", headers=auth(phone["token"]))
    assert listing.json()["total"] == 2
