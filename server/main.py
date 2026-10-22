from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .config import Settings
from .db import init_db
from .routers import agent, auth, health, notes, recordings
from .security import AttemptLimiter


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.ensure_dirs()
    init_db(settings.db_path)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield

    app = FastAPI(
        title="会议记录云端控制面",
        version=settings.version,
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url=None,
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.pair_limiter = AttemptLimiter()

    app.include_router(health.router)
    app.include_router(auth.router, prefix="/api/v1")
    app.include_router(recordings.router, prefix="/api/v1")
    app.include_router(agent.router, prefix="/api/v1")
    app.include_router(notes.router, prefix="/api/v1")

    @app.get("/")
    def root():
        return {"name": "meeting-notes-cloud", "version": settings.version}

    return app
