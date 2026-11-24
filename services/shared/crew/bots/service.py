"""Bot logic. Every query filters by `user_id`."""

import uuid
from dataclasses import dataclass

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from crew import audit
from crew.config import Settings
from crew.errors import AppError
from crew.models import Bot, Chat, ChatMember
from crew.runs.state import active_bot_ids
from crew.schemas.chat import BotCreate, BotUpdate


@dataclass(frozen=True)
class BotView:
    """A Bot plus the things the sidebar needs."""

    bot: Bot
    direct_chat_id: uuid.UUID | None
    working: bool


def not_found() -> AppError:
    return AppError(404, "bot_not_found", "That Bot does not exist.")


async def _direct_chats(session: AsyncSession, user_id: uuid.UUID) -> dict[uuid.UUID, uuid.UUID]:
    rows = await session.execute(
        select(ChatMember.bot_id, Chat.id)
        .join(Chat, Chat.id == ChatMember.chat_id)
        .where(Chat.user_id == user_id, Chat.kind == "direct")
    )
    return {bot_id: chat_id for bot_id, chat_id in rows}


async def _view(session: AsyncSession, settings: Settings, bot: Bot) -> BotView:
    chats = await _direct_chats(session, bot.user_id)
    working = await active_bot_ids(session, settings, bot.user_id)
    return BotView(bot, chats.get(bot.id), bot.id in working)


async def list_bots(session: AsyncSession, settings: Settings, user_id: uuid.UUID) -> list[BotView]:
    bots = (
        await session.scalars(
            select(Bot).where(Bot.user_id == user_id).order_by(Bot.is_primary.desc(), Bot.id)
        )
    ).all()
    chats = await _direct_chats(session, user_id)
    working = await active_bot_ids(session, settings, user_id)
    return [BotView(bot, chats.get(bot.id), bot.id in working) for bot in bots]


async def load_bot(session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID) -> Bot:
    bot = await session.scalar(select(Bot).where(Bot.id == bot_id, Bot.user_id == user_id))
    if bot is None:
        raise not_found()
    return bot


async def get_bot(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID, bot_id: uuid.UUID
) -> BotView:
    return await _view(session, settings, await load_bot(session, user_id, bot_id))


async def create_bot(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID, data: BotCreate
) -> BotView:
    count = await session.scalar(
        select(func.count()).select_from(Bot).where(Bot.user_id == user_id)
    )
    if (count or 0) >= settings.max_bots_per_user:
        raise AppError(
            409, "bot_limit_reached", f"You can have up to {settings.max_bots_per_user} Bots."
        )
    bot = Bot(
        user_id=user_id,
        name=data.name,
        avatar=data.avatar,
        job=data.job,
        instructions=data.instructions,
        approval_mode=data.approval_mode,
        is_primary=count == 0,  # the first Bot becomes the Primary Bot
    )
    session.add(bot)
    chat = Chat(user_id=user_id, kind="direct")
    session.add(chat)
    await session.flush()
    session.add(ChatMember(chat_id=chat.id, bot_id=bot.id))
    audit.record(session, user_id=user_id, actor="user", action="bot.create", target=str(bot.id))
    await session.commit()
    await session.refresh(bot)
    return BotView(bot, chat.id, False)


async def update_bot(
    session: AsyncSession,
    settings: Settings,
    user_id: uuid.UUID,
    bot_id: uuid.UUID,
    data: BotUpdate,
) -> BotView:
    bot = await load_bot(session, user_id, bot_id)
    for field in data.model_fields_set:
        value = getattr(data, field)
        # The avatar may be cleared; the other fields may not be set to null.
        if value is None and field != "avatar":
            continue
        setattr(bot, field, value)
    await session.commit()
    await session.refresh(bot)
    return await _view(session, settings, bot)


async def set_primary(
    session: AsyncSession, settings: Settings, user_id: uuid.UUID, bot_id: uuid.UUID
) -> BotView:
    bot = await load_bot(session, user_id, bot_id)
    if not bot.is_primary:
        # Clear first, then set: the partial unique index allows one Primary per user.
        await session.execute(
            update(Bot).where(Bot.user_id == user_id, Bot.is_primary).values(is_primary=False)
        )
        await session.flush()
        bot.is_primary = True
        await session.commit()
        await session.refresh(bot)
    return await _view(session, settings, bot)


async def delete_bot(session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID) -> None:
    bot = await load_bot(session, user_id, bot_id)
    was_primary = bot.is_primary
    # A direct chat belongs to its Bot: remove it (and its messages) with the Bot.
    direct_chat_ids = (
        await session.scalars(
            select(Chat.id)
            .join(ChatMember, ChatMember.chat_id == Chat.id)
            .where(Chat.user_id == user_id, Chat.kind == "direct", ChatMember.bot_id == bot.id)
        )
    ).all()
    if direct_chat_ids:
        await session.execute(
            delete(Chat).where(Chat.id.in_(direct_chat_ids), Chat.user_id == user_id)
        )
    await session.delete(bot)
    await session.flush()
    if was_primary:
        oldest = await session.scalar(
            select(Bot).where(Bot.user_id == user_id).order_by(Bot.id).limit(1)
        )
        if oldest is not None:
            oldest.is_primary = True
    audit.record(session, user_id=user_id, actor="user", action="bot.delete", target=str(bot_id))
    await session.commit()
