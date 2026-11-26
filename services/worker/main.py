"""ARQ worker entry point: `uv run arq worker.main.WorkerSettings`."""

import uuid
from typing import Any, ClassVar

import httpx
import structlog
from arq import cron
from arq.connections import RedisSettings
from redis.asyncio import Redis

from crew.agent.loop import run_agent as run_agent_impl
from crew.chats import groups
from crew.computer import create_provider
from crew.computer.service import stop_idle_computers
from crew.config import get_settings
from crew.connectors import events as connector_events
from crew.connectors.backend import create_backend
from crew.db import create_engine, create_session_factory
from crew.library.storage import create_storage
from crew.llm import LLMError, create_llm, create_small_llm
from crew.logs import configure as configure_logging
from crew.memory.service import compact_memory as compact_memory_impl
from crew.routines import service as routines
from crew.tools import default_registry
from crew.vault.crypto import VaultError, create_wrapper

log = structlog.get_logger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    ctx["settings"] = settings
    ctx["engine"] = create_engine(settings)
    ctx["session_factory"] = create_session_factory(ctx["engine"])
    ctx["pubsub_redis"] = Redis.from_url(settings.redis_url, decode_responses=True)
    ctx["http"] = httpx.AsyncClient(follow_redirects=False)
    ctx["registry"] = default_registry()
    ctx["provider"] = create_provider(settings)
    configure_logging(settings.log_level)
    ctx["storage"] = create_storage(settings)
    ctx["connectors"] = create_backend(settings, ctx["session_factory"], ctx["http"])
    try:
        ctx["vault"] = create_wrapper(settings)
    except VaultError as error:
        log.warning("worker.vault_not_configured", reason=str(error))
        ctx["vault"] = None
    try:
        ctx["llm"] = create_llm(settings)
        ctx["small_llm"] = create_small_llm(settings)
        ctx["llm_error"] = None
    except LLMError as error:
        # Keep the worker up: each run then fails with a clear message in the chat.
        log.warning("worker.llm_not_configured", code=error.code)
        ctx["llm"] = None
        ctx["small_llm"] = None
        ctx["llm_error"] = error


async def shutdown(ctx: dict[str, Any]) -> None:
    await ctx["provider"].aclose()
    await ctx["http"].aclose()
    await ctx["pubsub_redis"].aclose()
    await ctx["engine"].dispose()


async def run_agent(ctx: dict[str, Any], run_id: str) -> str:
    return await run_agent_impl(
        uuid.UUID(run_id),
        session_factory=ctx["session_factory"],
        redis=ctx["pubsub_redis"],
        settings=ctx["settings"],
        llm=ctx["llm"],
        registry=ctx["registry"],
        http=ctx["http"],
        provider=ctx["provider"],
        llm_error=ctx["llm_error"],
        queue=ctx["redis"],  # ARQ's own pool: it can enqueue jobs
        vault=ctx["vault"],
        connectors=ctx["connectors"],
        storage=ctx["storage"],
    )


async def pick_responder(ctx: dict[str, Any], chat_id: str, message_id: str) -> str:
    """A group message that names nobody: decides which Bot answers, or none."""
    return await groups.pick_responder(
        ctx["session_factory"],
        ctx["pubsub_redis"],
        ctx["redis"],
        ctx["settings"],
        ctx["small_llm"],
        uuid.UUID(chat_id),
        uuid.UUID(message_id),
    )


async def compact_memory(ctx: dict[str, Any], bot_id: str) -> str:
    """Merges similar memory lines once a Bot's memory has grown long."""
    return await compact_memory_impl(ctx["session_factory"], ctx["llm"], uuid.UUID(bot_id))


async def stop_idle(ctx: dict[str, Any]) -> int:
    """Every minute: pause computers nobody has used for COMPUTER_IDLE_MINUTES."""
    return await stop_idle_computers(
        ctx["session_factory"], ctx["pubsub_redis"], ctx["provider"], ctx["settings"]
    )


async def fire_routines(ctx: dict[str, Any]) -> int:
    """Every minute: starts the routines whose time has come."""
    return await routines.fire_due(
        ctx["session_factory"], ctx["pubsub_redis"], ctx["redis"], ctx["settings"]
    )


async def poll_connector_events(ctx: dict[str, Any]) -> int:
    """Every minute: starts routines that wait for new email or messages."""
    return await connector_events.poll(
        ctx["session_factory"],
        ctx["pubsub_redis"],
        ctx["redis"],
        ctx["settings"],
        ctx["connectors"],
    )


async def cleanup_routine_runs(ctx: dict[str, Any]) -> int:
    """Every hour: keeps the last 20 runs of each routine."""
    return await routines.cleanup_runs(ctx["session_factory"])


class WorkerSettings:
    functions: ClassVar[list[Any]] = [run_agent, compact_memory, pick_responder]
    cron_jobs: ClassVar[list[Any]] = [
        cron(stop_idle, second=0),
        cron(fire_routines, second=5),
        cron(poll_connector_events, second=35),
        cron(cleanup_routine_runs, minute=17, second=30),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    # A run can wait a long time for the user during Take over.
    job_timeout = get_settings().takeover_timeout_seconds + 1800
    max_tries = 1  # a run is not safe to repeat blindly
