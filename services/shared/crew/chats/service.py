"""Chat and message logic. Every query filters by `user_id`."""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crew import events
from crew.bots.service import load_bot
from crew.config import Settings
from crew.errors import AppError
from crew.models import Chat, ChatMember, Message, Run, ToolCall
from crew.runs.state import active_run_id
from crew.runs.tool_calls import tool_calls_for_runs
from crew.schemas.chat import ChatOut, MessageOut


class JobQueue(Protocol):
    """The part of ARQ the API uses. Tests pass a recorder."""

    async def enqueue_job(self, function: str, *args: object) -> object: ...


@dataclass(frozen=True)
class MessagePageData:
    items: list[Message]
    has_more: bool
    active_run_id: uuid.UUID | None
    tool_calls: list[ToolCall]


def not_found() -> AppError:
    return AppError(404, "chat_not_found", "That chat does not exist.")


async def load_chat(session: AsyncSession, user_id: uuid.UUID, chat_id: uuid.UUID) -> Chat:
    chat = await session.scalar(select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id))
    if chat is None:
        raise not_found()
    return chat


async def user_owns_chat(session: AsyncSession, user_id: uuid.UUID, chat_id: uuid.UUID) -> bool:
    found = await session.scalar(select(Chat.id).where(Chat.id == chat_id, Chat.user_id == user_id))
    return found is not None


async def _members(
    session: AsyncSession, chat_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    members: dict[uuid.UUID, list[uuid.UUID]] = {chat_id: [] for chat_id in chat_ids}
    if chat_ids:
        rows = await session.execute(
            select(ChatMember.chat_id, ChatMember.bot_id)
            .where(ChatMember.chat_id.in_(chat_ids))
            .order_by(ChatMember.bot_id)
        )
        for chat_id, bot_id in rows:
            members[chat_id].append(bot_id)
    return members


def _chat_out(chat: Chat, bot_ids: list[uuid.UUID]) -> ChatOut:
    return ChatOut(
        id=chat.id,
        kind="group" if chat.kind == "group" else "direct",
        title=chat.title,
        bot_ids=bot_ids,
        last_message_at=chat.last_message_at,
    )


async def list_chats(session: AsyncSession, user_id: uuid.UUID) -> list[ChatOut]:
    chats = (
        await session.scalars(
            select(Chat)
            .where(Chat.user_id == user_id)
            .order_by(Chat.last_message_at.desc().nulls_last(), Chat.id.desc())
        )
    ).all()
    members = await _members(session, [chat.id for chat in chats])
    return [_chat_out(chat, members[chat.id]) for chat in chats]


async def open_chat(session: AsyncSession, user_id: uuid.UUID, bot_ids: list[uuid.UUID]) -> ChatOut:
    """One Bot: returns its direct chat. Group chats arrive in phase 9."""
    if len(set(bot_ids)) != 1:
        raise AppError(400, "groups_not_available", "Group chats are not available yet.")
    bot = await load_bot(session, user_id, bot_ids[0])
    chat = await session.scalar(
        select(Chat)
        .join(ChatMember, ChatMember.chat_id == Chat.id)
        .where(Chat.user_id == user_id, Chat.kind == "direct", ChatMember.bot_id == bot.id)
    )
    if chat is None:
        chat = Chat(user_id=user_id, kind="direct")
        session.add(chat)
        await session.flush()
        session.add(ChatMember(chat_id=chat.id, bot_id=bot.id))
        await session.commit()
    return _chat_out(chat, [bot.id])


async def list_messages(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    chat_id: uuid.UUID,
    *,
    before: uuid.UUID | None,
    limit: int,
) -> MessagePageData:
    chat = await load_chat(session, user_id, chat_id)
    query = select(Message).where(Message.chat_id == chat.id)
    if before is not None:
        query = query.where(Message.id < before)
    rows = (await session.scalars(query.order_by(Message.id.desc()).limit(limit + 1))).all()
    has_more = len(rows) > limit
    items = list(reversed(rows[:limit]))
    run_ids = {message.run_id for message in items if message.role == "bot" and message.run_id}
    tool_calls = await tool_calls_for_runs(session, user_id, run_ids)
    return MessagePageData(
        items, has_more, await active_run_id(session, settings, chat.id), tool_calls
    )


async def send_message(
    session: AsyncSession,
    redis: Redis,
    queue: JobQueue,
    settings: Settings,
    user_id: uuid.UUID,
    chat_id: uuid.UUID,
    *,
    content: str,
) -> tuple[Message, uuid.UUID]:
    """Saves the user's message, creates a queued run and hands it to the worker."""
    chat = await session.scalar(
        select(Chat).where(Chat.id == chat_id, Chat.user_id == user_id).with_for_update()
    )
    if chat is None:
        raise not_found()
    if await active_run_id(session, settings, chat.id) is not None:
        raise AppError(409, "bot_busy", "Wait for the Bot to finish its reply.")
    bot_id = await session.scalar(
        select(ChatMember.bot_id).where(ChatMember.chat_id == chat.id).limit(1)
    )
    if bot_id is None:
        raise not_found()

    run = Run(user_id=user_id, bot_id=bot_id, chat_id=chat.id, status="queued")
    session.add(run)
    await session.flush()
    message = Message(chat_id=chat.id, role="user", content=content, run_id=run.id)
    session.add(message)
    chat.last_message_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(message)

    # Only after the commit, so the worker and other windows can see the rows.
    await events.publish(
        redis,
        events.chat_channel(chat.id),
        "message.created",
        {
            "chat_id": str(chat.id),
            "message": MessageOut.model_validate(message).model_dump(mode="json"),
        },
    )
    await events.publish(
        redis,
        events.user_channel(user_id),
        "run.status",
        {"run_id": str(run.id), "chat_id": str(chat.id), "bot_id": str(bot_id), "status": "queued"},
    )
    await queue.enqueue_job("run_agent", str(run.id))
    return message, run.id
