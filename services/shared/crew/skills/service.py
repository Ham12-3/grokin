"""Skills: saved procedures a Bot can run again. Every query filters by `user_id`.

A Bot cannot save a skill by itself: `skill_save` posts a draft card in the chat and the
skill exists only after the user clicks Save.
"""

import re
import uuid
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from crew import events
from crew.errors import AppError
from crew.models import Bot, Chat, Message, Skill
from crew.schemas.chat import MessageOut
from crew.schemas.memory import SkillCreate, SkillUpdate

MAX_SKILLS_PER_BOT = 100
DRAFT_CARD = "skill_draft"


def not_found() -> AppError:
    return AppError(404, "skill_not_found", "That skill does not exist.")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:40].strip("-")
    return slug or "skill"


async def _own_bot(session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID) -> None:
    owned = await session.scalar(select(Bot.id).where(Bot.id == bot_id, Bot.user_id == user_id))
    if owned is None:
        raise AppError(404, "bot_not_found", "That Bot does not exist.")


async def list_skills(session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID) -> list[Skill]:
    await _own_bot(session, user_id, bot_id)
    rows = await session.scalars(
        select(Skill).where(Skill.bot_id == bot_id, Skill.user_id == user_id).order_by(Skill.name)
    )
    return list(rows.all())


async def _free_slug(session: AsyncSession, bot_id: uuid.UUID, name: str) -> str:
    base = slugify(name)
    taken = set(
        (
            await session.scalars(
                select(Skill.slug).where(Skill.bot_id == bot_id, Skill.slug.like(f"{base}%"))
            )
        ).all()
    )
    if base not in taken:
        return base
    number = 2
    while f"{base}-{number}" in taken:
        number += 1
    return f"{base}-{number}"


async def create_skill(
    session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID, body: SkillCreate
) -> Skill:
    existing = await list_skills(session, user_id, bot_id)
    if len(existing) >= MAX_SKILLS_PER_BOT:
        raise AppError(409, "too_many_skills", "This Bot has too many skills. Delete one first.")
    skill = Skill(
        bot_id=bot_id,
        user_id=user_id,
        slug=await _free_slug(session, bot_id, body.name),
        name=body.name,
        description=body.description,
        steps=body.steps.strip(),
        rules=body.rules.strip(),
    )
    session.add(skill)
    await session.commit()
    await session.refresh(skill)
    return skill


async def load_skill(session: AsyncSession, user_id: uuid.UUID, skill_id: uuid.UUID) -> Skill:
    skill = await session.scalar(
        select(Skill).where(Skill.id == skill_id, Skill.user_id == user_id)
    )
    if skill is None:
        raise not_found()
    return skill


async def update_skill(
    session: AsyncSession, user_id: uuid.UUID, skill_id: uuid.UUID, body: SkillUpdate
) -> Skill:
    skill = await load_skill(session, user_id, skill_id)
    for name, value in body.model_dump(exclude_unset=True).items():
        if value is not None:
            # The slug stays: routines and habits point at it.
            setattr(skill, name, value.strip())
    await session.commit()
    await session.refresh(skill)
    return skill


async def delete_skill(session: AsyncSession, user_id: uuid.UUID, skill_id: uuid.UUID) -> None:
    skill = await load_skill(session, user_id, skill_id)
    await session.delete(skill)
    await session.commit()


# --- Draft cards ------------------------------------------------------------------------


async def _announce(redis: Redis, message: Message) -> None:
    await events.publish(
        redis,
        events.chat_channel(message.chat_id),
        "message.created",
        {
            "chat_id": str(message.chat_id),
            "message": MessageOut.model_validate(message).model_dump(mode="json"),
        },
    )


async def post_card(
    session: AsyncSession,
    redis: Redis,
    chat_id: uuid.UUID,
    bot_id: uuid.UUID,
    content: str,
    card: dict[str, Any],
) -> Message:
    """A card in the chat (a skill draft, a handoff note). Not part of what the LLM reads."""
    message = Message(chat_id=chat_id, role="system", bot_id=bot_id, content=content, card=card)
    session.add(message)
    await session.commit()
    await session.refresh(message)
    await _announce(redis, message)
    return message


async def _load_draft(
    session: AsyncSession, user_id: uuid.UUID, chat_id: uuid.UUID, message_id: uuid.UUID
) -> Message:
    message = await session.scalar(
        select(Message)
        .join(Chat, Chat.id == Message.chat_id)
        .where(Message.id == message_id, Message.chat_id == chat_id, Chat.user_id == user_id)
        .with_for_update(of=Message)
    )
    card = message.card if message is not None else None
    if message is None or card is None or card.get("type") != DRAFT_CARD or not message.bot_id:
        raise AppError(404, "draft_not_found", "That skill draft does not exist.")
    if card.get("status") != "draft":
        raise AppError(409, "draft_resolved", "This draft was already saved or cancelled.")
    return message


async def save_draft(
    session: AsyncSession,
    redis: Redis,
    user_id: uuid.UUID,
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
) -> Message:
    """The user clicked Save on a draft card: only now does the skill exist."""
    message = await _load_draft(session, user_id, chat_id, message_id)
    card = dict(message.card or {})
    assert message.bot_id is not None
    body = SkillCreate(
        name=str(card.get("name", "")),
        description=str(card.get("description", "")),
        steps=str(card.get("steps", "")),
        rules=str(card.get("rules", "")),
    )
    skill = await create_skill(session, user_id, message.bot_id, body)
    message.card = {**card, "status": "saved", "skill_id": str(skill.id), "slug": skill.slug}
    await session.commit()
    await session.refresh(message)
    await _announce(redis, message)
    return message


async def cancel_draft(
    session: AsyncSession,
    redis: Redis,
    user_id: uuid.UUID,
    chat_id: uuid.UUID,
    message_id: uuid.UUID,
) -> Message:
    message = await _load_draft(session, user_id, chat_id, message_id)
    message.card = {**(message.card or {}), "status": "cancelled"}
    await session.commit()
    await session.refresh(message)
    await _announce(redis, message)
    return message
