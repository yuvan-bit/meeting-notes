from __future__ import annotations

from fastapi.testclient import TestClient

from server.config import Settings

from .conftest import auth, make_pairing_code, pair


def test_pair_and_me(client: TestClient, settings: Settings) -> None:
    provider = pair(client, settings, "phone", "我的手机")
    assert provider["token"].startswith("mn_")
    response = client.get("/api/v1/me", headers=auth(provider["token"]))
    assert response.status_code == 200
    assert response.json()["role"] == "phone"
    assert response.json()["name"] == "我的手机"


def test_pairing_code_is_one_time(client: TestClient, settings: Settings) -> None:
    code = make_pairing_code(settings, "phone")
    first = client.post(
        "/api/v1/pair",
        json={"code": code, "device_name": "手机", "role": "phone"},
    )
    assert first.status_code == 201
    second = client.post(
        "/api/v1/pair",
        json={"code": code, "device_name": "另一台", "role": "phone"},
    )
    assert second.status_code == 400


def test_invalid_token_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/notes", headers=auth("mn_not_a_real_token"))
    assert response.status_code == 401


def test_phone_cannot_use_agent_api(client: TestClient, settings: Settings) -> None:
    phone = pair(client, settings, "phone")
    response = client.get("/api/v1/agent/jobs/next", headers=auth(phone["token"]))
    assert response.status_code == 403
