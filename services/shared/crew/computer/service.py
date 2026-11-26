"""The user's computer: its database row, start and stop, screens, idle pause.

Screens: a machine has six displays. A run takes the lowest free one for its whole life and
gives it back at the end, so two Bots can work at once without sharing a screen.
"""

import uuid
from datetime import UTC, datetime, timedelta

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crew import audit, events
from crew.computer.provider import (
    DISPLAYS,
    ComputerError,
    ComputerHandle,
    ComputerProvider,
    control_token,
)
from crew.config import Settings
from crew.models import Bot, Computer, Run
from crew.runs.state import is_active

log = structlog.get_logger(__name__)

BOT_DISPLAY_TTL_SECONDS = 7 * 24 * 3600


def _display_key(user_id: uuid.UUID, display: int) -> str:
    return f"computer:{user_id}:display:{display}"


def _bot_key(user_id: uuid.UUID, bot_id: uuid.UUID) -> str:
    return f"computer:{user_id}:bot:{bot_id}"


async def allocate_display(
    redis: Redis, settings: Settings, user_id: uuid.UUID, run_id: uuid.UUID, bot_id: uuid.UUID
) -> int:
    """Takes the lowest free screen for this run. The claim expires if the worker dies."""
    for display in DISPLAYS:
        claimed = await redis.set(
            _display_key(user_id, display), str(run_id), nx=True, ex=settings.display_claim_seconds
        )
        if claimed:
            await redis.set(_bot_key(user_id, bot_id), display, ex=BOT_DISPLAY_TTL_SECONDS)
            return display
    raise ComputerError("All six screens on your computer are busy. Wait for a Bot to finish.")


async def release_display(redis: Redis, user_id: uuid.UUID, run_id: uuid.UUID) -> None:
    for display in DISPLAYS:
        key = _display_key(user_id, display)
        if await redis.get(key) == str(run_id):
            await redis.delete(key)


async def display_for_bot(redis: Redis, user_id: uuid.UUID, bot_id: uuid.UUID) -> int:
    """The screen this Bot is using, or used last. Screen 1 if it has never had one."""
    stored = await redis.get(_bot_key(user_id, bot_id))
    try:
        display = int(stored) if stored is not None else 1
    except ValueError:
        display = 1
    return display if display in DISPLAYS else 1


async def get_computer(session: AsyncSession, settings: Settings, user_id: uuid.UUID) -> Computer:
    """The user's one computer row, created on first use."""
    computer = await session.scalar(select(Computer).where(Computer.user_id == user_id))
    if computer is None:
        computer = Computer(
            user_id=user_id,
            provider=settings.computer_provider,
            status="stopped",
            control_token_hash=_token_hash(settings, user_id),
        )
        session.add(computer)
        await session.commit()
        await session.refresh(computer)
    return computer


def _token_hash(settings: Settings, user_id: uuid.UUID) -> str:
    import hashlib

    return hashlib.sha256(control_token(settings, user_id).encode()).hexdigest()


async def _set_status(
    session: AsyncSession, redis: Redis, computer: Computer, status: str, *, active: bool = False
) -> None:
    computer.status = status
    if active:
        computer.last_active_at = datetime.now(UTC)
    await session.commit()
    await events.publish(
        redis,
        events.user_channel(computer.user_id),
        "computer.status",
        {"computer_id": str(computer.id), "status": status},
    )


async def start_computer(
    session: AsyncSession,
    redis: Redis,
    provider: ComputerProvider,
    settings: Settings,
    user_id: uuid.UUID,
    *,
    by_user: bool = False,
) -> tuple[Computer, ComputerHandle]:
    """Starts (or resumes) the machine and reports each state change to the app."""
    computer = await get_computer(session, settings, user_id)
    if computer.status != "running" or await provider.state(user_id) != "running":
        await _set_status(session, redis, computer, "starting")
    try:
        handle = await provider.ensure(user_id)
    except ComputerError:
        await _set_status(session, redis, computer, "error")
        raise
    computer.provider = provider.name
    if by_user:
        audit.record(session, user_id=user_id, actor="user", action="computer.start")
    await _set_status(session, redis, computer, "running", active=True)
    return computer, handle


async def stop_computer(
    session: AsyncSession,
    redis: Redis,
    provider: ComputerProvider,
    settings: Settings,
    user_id: uuid.UUID,
    *,
    actor: str = "user",
) -> Computer:
    computer = await get_computer(session, settings, user_id)
    await provider.stop(user_id)
    audit.record(session, user_id=user_id, actor=actor, action="computer.stop")
    await _set_status(session, redis, computer, "stopped")
    return computer


async def refresh_status(
    session: AsyncSession, redis: Redis, provider: ComputerProvider, computer: Computer
) -> Computer:
    """Fixes the row if the machine went away behind our back (Docker restart, crash)."""
    if computer.status == "running":
        try:
            running = await provider.state(computer.user_id) == "running"
        except ComputerError:
            running = False
        if not running:
            await _set_status(session, redis, computer, "stopped")
    return computer


async def touch(session_factory: async_sessionmaker[AsyncSession], user_id: uuid.UUID) -> None:
    async with session_factory() as session:
        computer = await session.scalar(select(Computer).where(Computer.user_id == user_id))
        if computer is not None:
            computer.last_active_at = datetime.now(UTC)
            await session.commit()


async def stop_idle_computers(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    provider: ComputerProvider,
    settings: Settings,
) -> int:
    """Pauses machines with no run in progress and no activity for COMPUTER_IDLE_MINUTES."""
    cutoff = datetime.now(UTC) - timedelta(minutes=settings.computer_idle_minutes)
    stopped = 0
    async with session_factory() as session:
        busy = select(Run.user_id).where(is_active(settings))
        idle = (
            await session.scalars(
                select(Computer).where(
                    Computer.status == "running",
                    Computer.last_active_at < cutoff,
                    Computer.user_id.not_in(busy),
                )
            )
        ).all()
        for computer in idle:
            try:
                await stop_computer(
                    session, redis, provider, settings, computer.user_id, actor="system"
                )
                stopped += 1
            except ComputerError:
                log.warning("computer.idle_stop_failed", computer_id=str(computer.id))
    return stopped


async def owned_bot(session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID) -> bool:
    found = await session.scalar(select(Bot.id).where(Bot.id == bot_id, Bot.user_id == user_id))
    return found is not None


class RunComputer:
    """The computer as one run sees it: started on first use, one screen for the whole run."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        redis: Redis,
        provider: ComputerProvider,
        settings: Settings,
        user_id: uuid.UUID,
        run_id: uuid.UUID,
        bot_id: uuid.UUID,
    ) -> None:
        self.provider = provider
        self._session_factory = session_factory
        self._redis = redis
        self._settings = settings
        self._user_id = user_id
        self._run_id = run_id
        self._bot_id = bot_id
        self._handle: ComputerHandle | None = None
        self._display: int | None = None
        # Labels of the elements on the page the Bot last read, by id (for risk checks).
        self.element_labels: dict[int, str] = {}
        self.page_url = ""
        self.page_text = ""

    @property
    def started(self) -> bool:
        return self._handle is not None

    async def handle(self) -> ComputerHandle:
        if self._handle is None:
            async with self._session_factory() as session:
                _, self._handle = await start_computer(
                    session, self._redis, self.provider, self._settings, self._user_id
                )
        return self._handle

    async def display(self) -> int:
        """This run's screen, with its browser running."""
        handle = await self.handle()
        if self._display is None:
            display = await allocate_display(
                self._redis, self._settings, self._user_id, self._run_id, self._bot_id
            )
            try:
                await self.provider.start_display(handle, display)
            except ComputerError:
                await release_display(self._redis, self._user_id, self._run_id)
                raise
            self._display = display
        return self._display

    async def close(self) -> None:
        if self._display is not None:
            await release_display(self._redis, self._user_id, self._run_id)
        if self._handle is not None:
            await touch(self._session_factory, self._user_id)
