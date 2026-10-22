from __future__ import annotations

import uvicorn

from .config import Settings
from .main import create_app


def main() -> None:
    settings = Settings.from_env()
    app = create_app(settings)
    uvicorn.run(
        app,
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=True,
        proxy_headers=False,
    )


if __name__ == "__main__":
    main()
