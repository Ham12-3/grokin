"""Crew API entry point: `uv run uvicorn api.main:app --reload --port 8000`."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from arq import create_pool
from arq.connections import RedisSettings
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from redis.asyncio import Redis
from starlette.exceptions import HTTPException as StarletteHTTPException

from api import ws
from api.routers import auth, bots, chats, computer, runs
from crew import __version__
from crew.auth.mailer import create_mailer
from crew.auth.tokens import require_jwt_secret
from crew.computer import create_provider
from crew.config import Settings, get_settings
from crew.db import create_engine, create_session_factory
from crew.errors import AppError
from crew.health import get_health
from crew.schemas.health import HealthResponse

API_PREFIX = get_settings().api_prefix

router = APIRouter(prefix=API_PREFIX)


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health(request: Request) -> HealthResponse:
    state = request.app.state
    settings: Settings = state.settings
    return await get_health(state.engine, state.redis, settings.health_check_timeout_seconds)


router.include_router(auth.router)
router.include_router(bots.router)
router.include_router(chats.router)
router.include_router(runs.router)
router.include_router(computer.router)
router.include_router(ws.router)


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status_code)


async def _app_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return _error(exc.status_code, exc.code, exc.message)


async def _http_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    return _error(exc.status_code, "http_error", str(exc.detail))


async def _validation_error(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Field names only: never echo submitted values back (they can hold tokens).
    fields = sorted(
        {".".join(str(p) for p in e["loc"][1:]) or str(e["loc"][0]) for e in exc.errors()}
    )
    return _error(422, "validation_error", f"Invalid request: {', '.join(fields)}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    require_jwt_secret(settings)
    app.state.settings = settings
    app.state.engine = create_engine(settings)
    app.state.session_factory = create_session_factory(app.state.engine)
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)
    app.state.http = httpx.AsyncClient(timeout=settings.http_timeout_seconds)
    app.state.mailer = create_mailer(settings)
    app.state.provider = create_provider(settings)
    app.state.queue = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    try:
        yield
    finally:
        await app.state.queue.aclose()
        await app.state.provider.aclose()
        await app.state.http.aclose()
        await app.state.redis.aclose()
        await app.state.engine.dispose()


def create_app() -> FastAPI:
    app = FastAPI(title="Crew API", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["GET", "POST", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.add_exception_handler(AppError, _app_error)
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.include_router(router)
    return app


app = create_app()
