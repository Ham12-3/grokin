"""Bot memory: short lines a Bot keeps about its user. Every query filters by `user_id`.

All lines go into the system prompt, so the list is kept small: when it passes about 2k
tokens a background job asks the LLM to merge lines that say the same thing.
"""

import uuid

import structlog
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crew.errors import AppError
from crew.llm.base import LLM, LLMError
from crew.models import Bot, Memory

log = structlog.get_logger(__name__)

MAX_LINE_CHARS = 300
MAX_LINES = 200
# About 2k tokens.
COMPACT_OVER_CHARS = 8000

COMPACT_SYSTEM = (
    "You tidy a list of notes that an assistant keeps about one person. Merge notes that "
    "say the same thing into one. Keep the person's own wording. Do not add anything new "
    "and do not drop any fact. Reply with the notes only, one per line, no numbering."
)


def clean(text: str) -> str:
    """One line, trimmed. Angle brackets are dropped so a line cannot imitate prompt tags."""
    flat = " ".join(text.replace("<", " ").replace(">", " ").split())
    return flat[:MAX_LINE_CHARS].strip()


def short_id(memory_id: uuid.UUID) -> str:
    """What the Bot sees and passes back to `memory_remove`."""
    return memory_id.hex[-8:]


def not_found() -> AppError:
    return AppError(404, "memory_not_found", "That memory line does not exist.")


async def _own_bot(session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID) -> None:
    owned = await session.scalar(select(Bot.id).where(Bot.id == bot_id, Bot.user_id == user_id))
    if owned is None:
        raise AppError(404, "bot_not_found", "That Bot does not exist.")


async def list_memory(session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID) -> list[Memory]:
    await _own_bot(session, user_id, bot_id)
    rows = await session.scalars(
        select(Memory).where(Memory.bot_id == bot_id, Memory.user_id == user_id).order_by(Memory.id)
    )
    return list(rows.all())


async def add_memory(
    session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID, text: str
) -> tuple[Memory, bool]:
    """Adds a line. Returns it and whether it is new (a repeat returns the existing line)."""
    line = clean(text)
    if not line:
        raise AppError(422, "empty_memory", "The line is empty.")
    lines = await list_memory(session, user_id, bot_id)
    for existing in lines:
        if existing.text.casefold() == line.casefold():
            return existing, False
    if len(lines) >= MAX_LINES:
        raise AppError(409, "memory_full", "Memory is full. Delete some lines first.")
    memory = Memory(bot_id=bot_id, user_id=user_id, text=line)
    session.add(memory)
    await session.commit()
    await session.refresh(memory)
    return memory, True


async def _load(
    session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID, line_id: uuid.UUID
) -> Memory:
    memory = await session.scalar(
        select(Memory).where(
            Memory.id == line_id, Memory.bot_id == bot_id, Memory.user_id == user_id
        )
    )
    if memory is None:
        raise not_found()
    return memory


async def update_memory(
    session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID, line_id: uuid.UUID, text: str
) -> Memory:
    memory = await _load(session, user_id, bot_id, line_id)
    line = clean(text)
    if not line:
        raise AppError(422, "empty_memory", "The line is empty.")
    memory.text = line
    await session.commit()
    await session.refresh(memory)
    return memory


async def delete_memory(
    session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID, line_id: uuid.UUID
) -> None:
    memory = await _load(session, user_id, bot_id, line_id)
    await session.delete(memory)
    await session.commit()


async def remove_by_short_id(
    session: AsyncSession, user_id: uuid.UUID, bot_id: uuid.UUID, short: str
) -> Memory | None:
    """For the `memory_remove` tool: the Bot only knows the short id from its prompt."""
    wanted = short.strip().strip("[]").lower().replace("-", "")
    if len(wanted) < 6:
        return None
    for memory in await list_memory(session, user_id, bot_id):
        if memory.id.hex.endswith(wanted) or memory.id.hex == wanted:
            await session.delete(memory)
            await session.commit()
            return memory
    return None


async def needs_compaction(session: AsyncSession, bot_id: uuid.UUID) -> bool:
    total = await session.scalar(
        select(func.coalesce(func.sum(func.length(Memory.text)), 0)).where(Memory.bot_id == bot_id)
    )
    return int(total or 0) > COMPACT_OVER_CHARS


async def _noop(_: str) -> None:
    return None


async def compact_memory(
    session_factory: async_sessionmaker[AsyncSession], llm: LLM | None, bot_id: uuid.UUID
) -> str:
    """Asks the LLM to merge similar lines. Changes nothing unless the result is smaller."""
    if llm is None:
        return "skipped"
    async with session_factory() as session:
        if not await needs_compaction(session, bot_id):
            return "not_needed"
        rows = (
            await session.scalars(select(Memory).where(Memory.bot_id == bot_id).order_by(Memory.id))
        ).all()
        if not rows:
            return "not_needed"
        user_id = rows[0].user_id
        notes = "\n".join(row.text for row in rows)
        try:
            result = await llm.stream(
                system=COMPACT_SYSTEM,
                messages=[{"role": "user", "content": f"<notes>\n{notes}\n</notes>"}],
                tools=[],
                on_delta=_noop,
            )
        except LLMError as error:
            log.warning("memory.compact_failed", code=error.code)
            return "failed"
        merged: list[str] = []
        for raw in result.text.splitlines():
            line = clean(raw.lstrip("-*• ").strip())
            if line and line.casefold() not in {item.casefold() for item in merged}:
                merged.append(line)
        before = sum(len(row.text) for row in rows)
        if not merged or len(merged) >= len(rows) or sum(map(len, merged)) >= before:
            return "unchanged"
        # Only the lines that were read are replaced: anything added meanwhile stays.
        await session.execute(delete(Memory).where(Memory.id.in_([row.id for row in rows])))
        session.add_all(Memory(bot_id=bot_id, user_id=user_id, text=line) for line in merged)
        await session.commit()
        log.info("memory.compacted", bot_id=str(bot_id), before=len(rows), after=len(merged))
        return "compacted"
