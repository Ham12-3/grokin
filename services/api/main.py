"""Crew API entry point: `uv run uvicorn api.main:app --reload --port 8000`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, Request
from redis.asyncio import Redis

from crew import __version__
from crew.config import Settings, get_settings
from crew.db import create_engine
from crew.health import get_health
from crew.schemas.health import HealthResponse

API_PREFIX = "/api/v1"

router = APIRouter(prefix=API_PREFIX)


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health(request: Request) -> HealthResponse:
    state = request.app.state
    settings: Settings = state.settings
    return await get_health(state.engine, state.redis, settings.health_check_timeout_seconds)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    app.state.settings = settings
    app.state.engine = create_engine(settings)
    app.state.redis = Redis.from_url(settings.redis_url)
    try:
        yield
    finally:
        await app.state.redis.aclose()
        await app.state.engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Crew API", version=__version__, lifespan=lifespan)
    app.include_router(router)
    return app


app = create_app()
