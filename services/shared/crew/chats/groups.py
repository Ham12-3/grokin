"""Group chats: who answers, in what order, and when to stop.

- `@Name` in the user's message: those Bots answer, in the order they were mentioned.
- No mention: one cheap LLM call picks a Bot, or nobody.
- A Bot can `@mention` another Bot in its reply; that Bot answers next.
- At most 6 Bot turns per user message, so Bots cannot talk to each other forever.
"""

import re
import uuid
from typing import Any, Protocol

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crew import events
from crew.config import Settings
from crew.llm.base import LLM, LLMError
from crew.models import Bot, Chat, ChatMember, Message, Run
from crew.runs.state import active_run_id
from crew.schemas.chat import MessageOut

log = structlog.get_logger(__name__)

MAX_TURNS = 6
PICKER_MARK = "You decide which teammate should answer"
PICKER_SYSTEM = (
    f"{PICKER_MARK} a message in a group chat. Reply with exactly one teammate's name from "
    "the list, or the word none if the message needs no answer or fits nobody. "
    "Reply with the name only."
)
NOBODY = "No Bot picked this up. Mention one with @ to ask it directly."


class JobQueue(Protocol):
    async def enqueue_job(self, function: str, *args: object) -> object: ...


async def members(session: AsyncSession, chat_id: uuid.UUID) -> list[Bot]:
    rows = await session.scalars(
        select(Bot)
        .join(ChatMember, ChatMember.bot_id == Bot.id)
        .where(ChatMember.chat_id == chat_id)
        .order_by(Bot.id)
    )
    return list(rows.all())


def _handles(bot: Bot) -> list[str]:
    """What a person may type after @ for this Bot: its name, with or without spaces, or
    the first word of its name."""
    name = bot.name.strip().lower()
    return sorted({name, name.replace(" ", ""), name.split(" ")[0]} - {""}, key=len, reverse=True)


def mentioned(text: str, bots: list[Bot], exclude: uuid.UUID | None = None) -> list[uuid.UUID]:
    """The Bots mentioned with @ in `text`, in the order they first appear."""
    lowered = text.lower()
    found: list[tuple[int, uuid.UUID]] = []
    for bot in bots:
        if bot.id == exclude:
            continue
        positions = [
            match.start()
            for handle in _handles(bot)
            for match in re.finditer(rf"@{re.escape(handle)}(?![a-z0-9])", lowered)
        ]
        if positions:
            found.append((min(positions), bot.id))
    return [bot_id for _, bot_id in sorted(found)]


async def start_turn(
    session: AsyncSession,
    redis: Redis,
    queue: JobQueue,
    chat: Chat,
    bot_id: uuid.UUID,
    *,
    turn: int,
    waiting: list[uuid.UUID],
    message: Message | None = None,
) -> uuid.UUID:
    """Queues one Bot's turn. `waiting` are the Bots to answer after it."""
    run = Run(
        user_id=chat.user_id,
        bot_id=bot_id,
        chat_id=chat.id,
        status="queued",
        turn=turn,
        queue=waiting,
    )
    session.add(run)
    await session.flush()
    if message is not None:
        message.run_id = run.id
    await session.commit()
    await events.publish(
        redis,
        events.user_channel(chat.user_id),
        "run.status",
        {
            "run_id": str(run.id),
            "chat_id": str(chat.id),
            "bot_id": str(bot_id),
            "status": "queued",
        },
    )
    await queue.enqueue_job("run_agent", str(run.id))
    return run.id


async def after_turn(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    queue: JobQueue | None,
    run_id: uuid.UUID,
    reply: str,
) -> uuid.UUID | None:
    """Called when a Bot's turn in a group ends well: starts the next Bot's turn, if any."""
    if queue is None:
        return None
    async with session_factory() as session:
        run = await session.get(Run, run_id)
        chat = await session.get(Chat, run.chat_id) if run and run.chat_id else None
        if run is None or chat is None or chat.kind != "group" or run.turn < 1:
            return None
        bots = await members(session, chat.id)
        member_ids = {bot.id for bot in bots}
        waiting = [bot_id for bot_id in run.queue if bot_id in member_ids]
        # A Bot that was asked by name answers after the ones already waiting.
        for bot_id in mentioned(reply, bots, exclude=run.bot_id):
            if bot_id not in waiting:
                waiting.append(bot_id)
        if not waiting:
            return None
        if run.turn >= MAX_TURNS:
            log.info("group.turn_cap", chat_id=str(chat.id), turns=run.turn)
            await _note(
                session,
                redis,
                chat.id,
                f"The Bots stopped after {MAX_TURNS} turns. Send a message to continue.",
            )
            return None
        return await start_turn(
            session, redis, queue, chat, waiting[0], turn=run.turn + 1, waiting=waiting[1:]
        )


async def _note(session: AsyncSession, redis: Redis, chat_id: uuid.UUID, text: str) -> None:
    message = Message(chat_id=chat_id, role="system", content=text)
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


async def _noop(_: str) -> None:
    return None


async def pick_responder(
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    queue: JobQueue,
    settings: Settings,
    llm: LLM | None,
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
) -> str:
    """An unaddressed group message: one cheap call decides which Bot answers, or none."""
    async with session_factory() as session:
        chat = await session.get(Chat, chat_id)
        message = await session.get(Message, message_id)
        if chat is None or message is None or chat.kind != "group":
            return "skipped"
        if await active_run_id(session, settings, chat.id) is not None:
            return "busy"
        bots = await members(session, chat.id)
        if not bots:
            return "skipped"
        chosen: Bot | None = None
        if llm is not None:
            recent = (
                await session.scalars(
                    select(Message)
                    .where(Message.chat_id == chat.id, Message.role.in_(("user", "bot")))
                    .order_by(Message.id.desc())
                    .limit(6)
                )
            ).all()
            names = {bot.id: bot.name for bot in bots}
            lines = [
                (names.get(item.bot_id, "Bot") if item.bot_id and item.role == "bot" else "User")
                + f": {item.content[:400]}"
                for item in reversed(recent)
            ]
            team = "\n".join(f"- {bot.name}: {bot.job}" for bot in bots)
            prompt = (
                f"Teammates:\n{team}\n\n<conversation>\n" + "\n".join(lines) + "\n</conversation>"
            )
            try:
                result = await llm.stream(
                    system=PICKER_SYSTEM,
                    messages=[{"role": "user", "content": prompt}],
                    tools=[],
                    on_delta=_noop,
                )
            except LLMError as error:
                log.warning("group.picker_failed", code=error.code)
            else:
                answer = result.text.strip().strip(".\"'").lower()
                chosen = next((bot for bot in bots if bot.name.lower() == answer), None)
        if chosen is None:
            await _note(session, redis, chat.id, NOBODY)
            return "none"
        await start_turn(
            session, redis, queue, chat, chosen.id, turn=1, waiting=[], message=message
        )
        return str(chosen.id)


def group_prompt(bot: Bot, bots: list[Bot]) -> str:
    """Added to a Bot's system prompt when it answers in a group."""
    others: list[dict[str, Any]] = [
        {"name": other.name, "job": other.job} for other in bots if other.id != bot.id
    ]
    listing = "\n".join(f"- {other['name']}: {other['job']}" for other in others)
    return (
        "## Group chat\n"
        "You are in a group chat with the user and these Bots:\n"
        f"{listing}\n"
        "Answer only your own part, briefly. Messages from the other Bots are shown with "
        "their name in front. If another Bot should do something, ask it by writing "
        "@ and its name; otherwise do not mention them."
    )
