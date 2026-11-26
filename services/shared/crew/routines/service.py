"""Routines: create, schedule, fire, history. Every user-facing query filters by `user_id`.

A routine run lives in the routine's own chat, so it never waits behind the user's chat and
never blocks it. Risky actions in a routine run do not wait for anyone: they become pending
approvals and the run ends `needs_review` (see `crew.agent.loop`).
"""

import hashlib
import hmac
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import structlog
from redis.asyncio import Redis
from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crew import audit, events, usage
from crew.config import Settings
from crew.errors import AppError
from crew.models import Bot, Chat, ChatMember, Message, Routine, Run, Skill, ToolCall, User
from crew.routines import schedule
from crew.runs.state import is_active
from crew.schemas.chat import MessageOut
from crew.schemas.routine import (
    LastRun,
    RoutineCreate,
    RoutineOut,
    RoutineRunOut,
    RoutineUpdate,
)
from crew.schemas.run import ToolCallOut

log = structlog.get_logger(__name__)

MAX_ROUTINES_PER_BOT = 50
MAX_RUNS_PER_HOUR = 300
KEEP_RUNS = 20
MIN_GAP = timedelta(minutes=5)
WEBHOOK_PER_MINUTE = 10
FIRE_LOCK_SECONDS = 120


class JobQueue(Protocol):
    async def enqueue_job(self, function: str, *args: object) -> object: ...


class NotStarted(Exception):
    """A routine did not start a run this time. `reason` is safe to log and show."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def not_found() -> AppError:
    return AppError(404, "routine_not_found", "That routine does not exist.")


def hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _webhook_url(settings: Settings, routine_id: uuid.UUID, secret: str) -> str:
    return f"{settings.api_base_url.rstrip('/')}/api/v1/webhooks/routines/{routine_id}/{secret}"


def _next_run(trigger: dict[str, Any], after: datetime) -> datetime | None:
    if trigger.get("type") != "cron":
        return None
    return schedule.next_run(str(trigger["cron"]), str(trigger.get("timezone", "UTC")), after)


def _check_trigger(trigger: dict[str, Any], now: datetime) -> None:
    if trigger.get("type") != "cron":
        return
    cron, zone = str(trigger["cron"]), str(trigger.get("timezone", "UTC"))
    schedule.validate(cron, zone)
    if schedule.shortest_gap(cron, zone, now) < MIN_GAP:
        raise AppError(422, "too_often", "A routine can run at most every 5 minutes.")


async def _own_skill(
    session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID, skill_id: uuid.UUID
) -> Skill:
    skill = await session.scalar(
        select(Skill).where(Skill.id == skill_id, Skill.user_id == user_id, Skill.bot_id == bot_id)
    )
    if skill is None:
        raise AppError(404, "skill_not_found", "That skill does not exist.")
    return skill


async def _outs(
    session: AsyncSession, routines: list[Routine], webhook_url: str | None = None
) -> list[RoutineOut]:
    if not routines:
        return []
    skills = {
        skill.id: skill
        for skill in (
            await session.scalars(
                select(Skill).where(Skill.id.in_({routine.skill_id for routine in routines}))
            )
        ).all()
    }
    # The newest run of each routine (at most 20 or so are kept per routine).
    rows = (
        await session.execute(
            select(Run.routine_id, Run.id, Run.status, Run.created_at, Run.finished_at)
            .where(Run.routine_id.in_([routine.id for routine in routines]))
            .order_by(Run.id.desc())
        )
    ).all()
    last: dict[uuid.UUID, LastRun] = {}
    for row in rows:
        last.setdefault(
            row.routine_id,
            LastRun(run_id=row.id, status=row.status, at=row.finished_at or row.created_at),
        )
    return [
        RoutineOut(
            id=routine.id,
            bot_id=routine.bot_id,
            skill_id=routine.skill_id,
            skill_name=skills[routine.skill_id].name,
            skill_slug=skills[routine.skill_id].slug,
            trigger=routine.trigger,
            notify=routine.notify,
            paused=routine.paused,
            next_run_at=routine.next_run_at,
            last_run=last.get(routine.id),
            webhook_url=webhook_url,
        )
        for routine in routines
    ]


async def list_routines(
    session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID
) -> list[RoutineOut]:
    owned = await session.scalar(select(Bot.id).where(Bot.id == bot_id, Bot.user_id == user_id))
    if owned is None:
        raise AppError(404, "bot_not_found", "That Bot does not exist.")
    rows = await session.scalars(
        select(Routine)
        .where(Routine.bot_id == bot_id, Routine.user_id == user_id)
        .order_by(Routine.id)
    )
    return await _outs(session, list(rows.all()))


async def load(session: AsyncSession, user_id: uuid.UUID, routine_id: uuid.UUID) -> Routine:
    routine = await session.scalar(
        select(Routine).where(Routine.id == routine_id, Routine.user_id == user_id)
    )
    if routine is None:
        raise not_found()
    return routine


async def create_routine(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    bot_id: uuid.UUID,
    body: RoutineCreate,
) -> RoutineOut:
    await _own_skill(session, user_id, bot_id, body.skill_id)
    count = await session.scalar(
        select(func.count()).select_from(Routine).where(Routine.bot_id == bot_id)
    )
    if (count or 0) >= MAX_ROUTINES_PER_BOT:
        raise AppError(409, "too_many_routines", "This Bot has 50 routines. Delete one first.")
    now = datetime.now(UTC)
    trigger = body.trigger.model_dump()
    _check_trigger(trigger, now)
    secret = secrets.token_urlsafe(32) if trigger["type"] == "webhook" else None
    routine = Routine(
        bot_id=bot_id,
        user_id=user_id,
        skill_id=body.skill_id,
        trigger=trigger,
        webhook_secret_hash=hash_secret(secret) if secret else None,
        notify=body.notify,
        next_run_at=_next_run(trigger, now),
    )
    session.add(routine)
    await session.flush()
    audit.record(
        session, user_id=user_id, actor="user", action="routine.create", target=str(routine.id)
    )
    await session.commit()
    await session.refresh(routine)
    url = _webhook_url(settings, routine.id, secret) if secret else None
    return (await _outs(session, [routine], url))[0]


async def update_routine(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    routine_id: uuid.UUID,
    body: RoutineUpdate,
) -> RoutineOut:
    routine = await load(session, user_id, routine_id)
    url: str | None = None
    if body.skill_id is not None:
        await _own_skill(session, user_id, routine.bot_id, body.skill_id)
        routine.skill_id = body.skill_id
    if body.notify is not None:
        routine.notify = body.notify
    if body.trigger is not None:
        now = datetime.now(UTC)
        trigger = body.trigger.model_dump()
        _check_trigger(trigger, now)
        was_webhook = routine.trigger.get("type") == "webhook"
        routine.trigger = trigger
        routine.next_run_at = None if routine.paused else _next_run(trigger, now)
        if trigger["type"] != "webhook":
            routine.webhook_secret_hash = None
        elif not was_webhook:
            secret = secrets.token_urlsafe(32)
            routine.webhook_secret_hash = hash_secret(secret)
            url = _webhook_url(settings, routine.id, secret)
    await session.commit()
    await session.refresh(routine)
    return (await _outs(session, [routine], url))[0]


async def set_paused(
    session: AsyncSession, user_id: uuid.UUID, routine_id: uuid.UUID, paused: bool
) -> RoutineOut:
    routine = await load(session, user_id, routine_id)
    routine.paused = paused
    # A resumed routine waits for its next time; it does not catch up on missed ones.
    routine.next_run_at = None if paused else _next_run(routine.trigger, datetime.now(UTC))
    audit.record(
        session,
        user_id=user_id,
        actor="user",
        action="routine.pause" if paused else "routine.resume",
        target=str(routine.id),
    )
    await session.commit()
    await session.refresh(routine)
    return (await _outs(session, [routine]))[0]


async def pause_all(session: AsyncSession, user_id: uuid.UUID) -> int:
    rows = await session.execute(
        update(Routine)
        .where(Routine.user_id == user_id, Routine.paused.is_(False))
        .values(paused=True, next_run_at=None)
        .returning(Routine.id)
    )
    count = len(rows.all())
    audit.record(
        session, user_id=user_id, actor="user", action="routine.pause_all", detail={"count": count}
    )
    await session.commit()
    return count


async def delete_routine(session: AsyncSession, user_id: uuid.UUID, routine_id: uuid.UUID) -> None:
    routine = await load(session, user_id, routine_id)
    chat_id = routine.chat_id
    audit.record(
        session, user_id=user_id, actor="user", action="routine.delete", target=str(routine.id)
    )
    await session.delete(routine)  # its runs go with it
    await session.flush()
    if chat_id is not None:
        await session.execute(delete(Chat).where(Chat.id == chat_id, Chat.kind == "routine"))
    await session.commit()


# --- Starting a run ---------------------------------------------------------------------


async def _routine_chat(session: AsyncSession, routine: Routine) -> uuid.UUID:
    if routine.chat_id is not None:
        return routine.chat_id
    chat = Chat(user_id=routine.user_id, kind="routine", title="Routine")
    session.add(chat)
    await session.flush()
    session.add(ChatMember(chat_id=chat.id, bot_id=routine.bot_id))
    routine.chat_id = chat.id
    return chat.id


async def start_run(
    session: AsyncSession,
    redis: Redis,
    queue: JobQueue,
    settings: Settings,
    routine: Routine,
    source: str,
) -> uuid.UUID:
    """Queues one run of a routine. Raises `NotStarted` when a limit says no."""
    skill = await session.get(Skill, routine.skill_id)
    if skill is None:
        raise NotStarted("skill_missing")
    # Over the daily budget, routines wait until it resets.
    user = await session.get(User, routine.user_id)
    today = await usage.usage_today(session, routine.user_id)
    if user is None or today.input_tokens + today.output_tokens >= user.daily_token_budget:
        raise NotStarted("daily_token_limit")
    chat_id = await _routine_chat(session, routine)
    busy = await session.scalar(
        select(Run.id).where(Run.chat_id == chat_id, is_active(settings)).limit(1)
    )
    if busy is not None:
        raise NotStarted("still_running")
    # At most 300 routine runs an hour per user, whatever starts them.
    bucket = f"routine_runs:{routine.user_id}:{datetime.now(UTC):%Y%m%d%H}"
    used = await redis.incr(bucket)
    if used == 1:
        await redis.expire(bucket, 3700)
    if used > MAX_RUNS_PER_HOUR:
        raise NotStarted("hourly_limit")

    run = Run(
        user_id=routine.user_id,
        bot_id=routine.bot_id,
        chat_id=chat_id,
        routine_id=routine.id,
        skill_id=routine.skill_id,
        status="queued",
    )
    session.add(run)
    await session.flush()
    message = Message(
        chat_id=chat_id,
        role="user",
        content=f"/{skill.slug}",
        run_id=run.id,
        card={"type": "routine", "routine_id": str(routine.id), "source": source},
    )
    session.add(message)
    await session.commit()
    await session.refresh(message)
    await events.publish(
        redis,
        events.chat_channel(chat_id),
        "message.created",
        {
            "chat_id": str(chat_id),
            "message": MessageOut.model_validate(message).model_dump(mode="json"),
        },
    )
    await queue.enqueue_job("run_agent", str(run.id))
    log.info("routine.started", routine_id=str(routine.id), run_id=str(run.id), source=source)
    return run.id


async def test_run(
    session: AsyncSession,
    redis: Redis,
    queue: JobQueue,
    settings: Settings,
    user_id: uuid.UUID,
    routine_id: uuid.UUID,
) -> uuid.UUID:
    """ "Run now" from the app. Works for a paused routine too."""
    routine = await load(session, user_id, routine_id)
    try:
        return await start_run(session, redis, queue, settings, routine, "test")
    except NotStarted as error:
        await session.rollback()
        messages = {
            "still_running": "This routine is still running. Try again when it has finished.",
            "daily_token_limit": "Today's token limit is used up. Routines wait until it resets.",
            "hourly_limit": "Too many routine runs this hour. Try again later.",
            "skill_missing": "This routine's skill no longer exists.",
        }
        raise AppError(409, error.reason, messages[error.reason]) from error


async def fire_webhook(
    session: AsyncSession,
    redis: Redis,
    queue: JobQueue,
    settings: Settings,
    routine_id: uuid.UUID,
    secret: str,
) -> uuid.UUID:
    """Public. An unknown routine, a wrong secret and a non-webhook routine all look the same."""
    routine = await session.get(Routine, routine_id)
    stored = routine.webhook_secret_hash if routine is not None else None
    # Always compare, so the answer takes the same time whether or not the routine exists.
    matches = hmac.compare_digest(hash_secret(secret), stored or hash_secret("no such routine"))
    if routine is None or stored is None or not matches or routine.trigger.get("type") != "webhook":
        raise not_found()
    bucket = f"webhook:{routine.id}:{datetime.now(UTC):%Y%m%d%H%M}"
    hits = await redis.incr(bucket)
    if hits == 1:
        await redis.expire(bucket, 120)
    if hits > WEBHOOK_PER_MINUTE:
        raise AppError(429, "rate_limited", "Too many requests. Try again in a minute.")
    if routine.paused:
        raise AppError(409, "routine_paused", "This routine is paused.")
    try:
        return await start_run(session, redis, queue, settings, routine, "webhook")
    except NotStarted as error:
        await session.rollback()
        raise AppError(409, error.reason, "The routine could not start now.") from error


async def fire_due(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    queue: JobQueue,
    settings: Settings,
    now: datetime | None = None,
) -> int:
    """Every minute: starts each routine whose time has come. Returns how many started.

    Two workers can run this at once. A Redis lock per routine and time, and a guarded
    UPDATE of `next_run_at`, make sure each firing happens once.
    """
    now = now or datetime.now(UTC)
    async with session_factory() as session:
        due = (
            await session.scalars(
                select(Routine)
                .where(Routine.paused.is_(False), Routine.next_run_at <= now)
                .order_by(Routine.next_run_at)
                .limit(200)
            )
        ).all()
        started = 0
        for routine in due:
            planned = routine.next_run_at
            assert planned is not None
            lock = f"routine:{routine.id}:fire:{int(planned.timestamp())}"
            if not await redis.set(lock, "1", nx=True, ex=FIRE_LOCK_SECONDS):
                continue  # another worker has this one
            claimed = await session.execute(
                update(Routine)
                .where(Routine.id == routine.id, Routine.next_run_at == planned)
                .values(next_run_at=_next_run(routine.trigger, now))
                .returning(Routine.id)
            )
            if claimed.first() is None:
                await session.rollback()
                continue
            await session.commit()
            await session.refresh(routine)
            try:
                await start_run(session, redis, queue, settings, routine, "schedule")
                started += 1
            except NotStarted as error:
                await session.rollback()
                log.info("routine.skipped", routine_id=str(routine.id), reason=error.reason)
        return started


# --- History ----------------------------------------------------------------------------


async def list_runs(
    session: AsyncSession, user_id: uuid.UUID, routine_id: uuid.UUID
) -> list[RoutineRunOut]:
    routine = await load(session, user_id, routine_id)
    runs = (
        await session.scalars(
            select(Run)
            .where(Run.routine_id == routine.id, Run.user_id == user_id)
            .order_by(Run.id.desc())
            .limit(KEEP_RUNS)
        )
    ).all()
    if not runs:
        return []
    run_ids = [run.id for run in runs]
    messages = (await session.scalars(select(Message).where(Message.run_id.in_(run_ids)))).all()
    replies = {m.run_id: m.content for m in messages if m.role == "bot"}
    sources = {
        m.run_id: str((m.card or {}).get("source", "schedule"))
        for m in messages
        if m.role == "user"
    }
    calls: dict[uuid.UUID, list[ToolCallOut]] = {}
    for call in (
        await session.scalars(
            select(ToolCall).where(ToolCall.run_id.in_(run_ids)).order_by(ToolCall.id)
        )
    ).all():
        calls.setdefault(call.run_id, []).append(ToolCallOut.model_validate(call))
    return [
        RoutineRunOut(
            run_id=run.id,
            status=run.status,
            source=sources.get(run.id, "schedule"),
            created_at=run.created_at,
            finished_at=run.finished_at,
            error=run.error,
            reply=replies.get(run.id, ""),
            tool_calls=calls.get(run.id, []),
        )
        for run in runs
    ]


async def cleanup_runs(session_factory: async_sessionmaker[AsyncSession]) -> int:
    """Hourly: keeps the newest 20 runs of each routine, with their messages."""
    async with session_factory() as session:
        old = (
            (
                await session.execute(
                    text(
                        "SELECT id FROM (SELECT id, status, row_number() OVER "
                        "(PARTITION BY routine_id ORDER BY id DESC) AS position FROM runs "
                        "WHERE routine_id IS NOT NULL) ranked "
                        "WHERE position > :keep AND status NOT IN "
                        "('queued', 'running', 'paused', 'waiting_approval', 'needs_review')"
                    ),
                    {"keep": KEEP_RUNS},
                )
            )
            .scalars()
            .all()
        )
        if not old:
            return 0
        await session.execute(delete(Message).where(Message.run_id.in_(old)))
        await session.execute(delete(Run).where(Run.id.in_(old)))
        await session.commit()
        return len(old)
