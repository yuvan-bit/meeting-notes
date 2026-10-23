from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

from ..app_update import APK_FILENAME, ReleaseError, read_release
from ..config import Settings
from ..deps import get_settings

router = APIRouter(tags=["app-update"])


def _release(settings: Settings) -> dict:
    try:
        release = read_release(settings)
    except ReleaseError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if release is None:
        raise HTTPException(status_code=404, detail="尚未发布安卓更新")
    return release


@router.get("/app/latest")
def latest_app(settings: Settings = Depends(get_settings)):
    release = _release(settings)
    return {
        **release,
        "apk_url": f"/api/v1/app/apk?v={release['version_code']}",
    }


@router.get("/app/apk")
def download_app(settings: Settings = Depends(get_settings)):
    release = _release(settings)
    path = settings.app_dir / APK_FILENAME
    if not path.is_file():
        raise HTTPException(status_code=404, detail="安装包不存在")
    safe_name = re.sub(r"[^0-9A-Za-z._-]+", "-", release["version_name"]).strip("-")
    return FileResponse(
        path,
        media_type="application/vnd.android.package-archive",
        filename=f"meeting-notes-{safe_name or 'release'}.apk",
        headers={
            "X-APK-SHA256": release["sha256"],
            "Cache-Control": "public, max-age=3600",
        },
    )
