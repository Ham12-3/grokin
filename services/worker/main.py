"""ARQ worker entry point: `uv run arq worker.main.WorkerSettings`."""

import uuid
from typing import Any, ClassVar

import structlog
from arq.connections import RedisSettings
from redis.asyncio import Redis

from crew.config import get_settings
from crew.db import create_engine, create_session_factory
from crew.llm import LLMError, create_llm
from crew.runs.agent import run_agent as run_agent_impl

log = structlog.get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    ctx["settings"] = settings
    ctx["engine"] = create_engine(settings)
    ctx["session_factory"] = create_session_factory(ctx["engine"])
    ctx["pubsub_redis"] = Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        ctx["llm"] = create_llm(settings)
        ctx["llm_error"] = None
    except LLMError as error:
        # Keep the worker up: each run then fails with a clear message in the chat.
        log.warning("worker.llm_not_configured", code=error.code)
        ctx["llm"] = None
        ctx["llm_error"] = error


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["pubsub_redis"].aclose()
    await ctx["engine"].dispose()


async def run_agent(ctx: dict[str, Any], run_id: str) -> str:
    return await run_agent_impl(
        uuid.UUID(run_id),
        session_factory=ctx["session_factory"],
        redis=ctx["pubsub_redis"],
        settings=ctx["settings"],
        llm=ctx["llm"],
        llm_error=ctx["llm_error"],
    )


class WorkerSettings:
    functions: ClassVar[list[Any]] = [run_agent]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    job_timeout = get_settings().run_timeout_seconds
    max_tries = 1  # a run is not safe to repeat blindly
