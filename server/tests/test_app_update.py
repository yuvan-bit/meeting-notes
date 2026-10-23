from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.app_update import ReleaseError, publish_apk
from server.config import Settings

APK_BYTES = b"PK\x03\x04" + b"meeting-notes-apk" * 128


def _apk(tmp_path: Path, name: str = "app-release.apk") -> Path:
    path = tmp_path / name
    path.write_bytes(APK_BYTES)
    return path


def test_update_endpoints_404_before_publish(client: TestClient) -> None:
    assert client.get("/api/v1/app/latest").status_code == 404
    assert client.get("/api/v1/app/apk").status_code == 404


def test_publish_and_download_update(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    meta = publish_apk(settings, _apk(tmp_path), 2, "0.2.0", "支持应用内更新")

    response = client.get("/api/v1/app/latest")
    assert response.status_code == 200
    latest = response.json()
    assert latest["version_code"] == 2
    assert latest["version_name"] == "0.2.0"
    assert latest["changelog"] == "支持应用内更新"
    assert latest["sha256"] == hashlib.sha256(APK_BYTES).hexdigest()
    assert latest["size_bytes"] == len(APK_BYTES)
    assert latest["apk_url"] == "/api/v1/app/apk?v=2"

    download = client.get(latest["apk_url"])
    assert download.status_code == 200
    assert download.content == APK_BYTES
    assert download.headers["content-type"] == "application/vnd.android.package-archive"
    assert download.headers["x-apk-sha256"] == meta["sha256"]
    assert "meeting-notes-0.2.0.apk" in download.headers["content-disposition"]


def test_republish_replaces_previous_update(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    publish_apk(settings, _apk(tmp_path, "v2.apk"), 2, "0.2.0")
    publish_apk(settings, _apk(tmp_path, "v3.apk"), 3, "0.3.0", "修复问题")

    latest = client.get("/api/v1/app/latest").json()
    assert latest["version_code"] == 3
    assert latest["version_name"] == "0.3.0"
    assert latest["changelog"] == "修复问题"


def test_corrupt_metadata_returns_503(client: TestClient, settings: Settings) -> None:
    (settings.app_dir / "latest.json").write_text("{broken", encoding="utf-8")
    assert client.get("/api/v1/app/latest").status_code == 503
    assert client.get("/api/v1/app/apk").status_code == 503


def test_missing_apk_file_returns_404(
    client: TestClient, settings: Settings, tmp_path: Path
) -> None:
    publish_apk(settings, _apk(tmp_path), 2, "0.2.0")
    (settings.app_dir / "latest.apk").unlink()

    assert client.get("/api/v1/app/latest").status_code == 200
    assert client.get("/api/v1/app/apk").status_code == 404


def test_publish_rejects_non_apk(settings: Settings, tmp_path: Path) -> None:
    text = tmp_path / "notes.apk"
    text.write_text("not an apk", encoding="utf-8")
    with pytest.raises(ReleaseError):
        publish_apk(settings, text, 2, "0.2.0")

    wrong_suffix = tmp_path / "app.zip"
    wrong_suffix.write_bytes(APK_BYTES)
    with pytest.raises(ReleaseError):
        publish_apk(settings, wrong_suffix, 2, "0.2.0")
