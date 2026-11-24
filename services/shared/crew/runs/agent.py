"""One agent run: stream a reply from the LLM into a chat.

Runs inside the worker, never inside an API request. Phase 2 has no tools: one LLM call per
run. Each delta carries its character `offset` in the message, so a client that reconnects
mid-stream can tell whether it missed anything.
"""

import time
import uuid
from datetime import UTC, datetime
from typing import Literal

import structlog
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crew import events, usage
from crew.agent.prompts import build_system_prompt
from crew.config import Settings
from crew.llm.base import LLM, ChatTurn, LLMError
from crew.models import Bot, Chat, Message, Run
from crew.schemas.chat import MessageOut

log = structlog.get_logger(__name__)

GENERIC_ERROR = "Something went wrong while replying. Try again."


async def _history(session: AsyncSession, settings: Settings, chat_id: uuid.UUID) -> list[ChatTurn]:
    """The last N messages as alternating user/assistant turns, starting with a user turn."""
    rows = (
        await session.scalars(
            select(Message)
            .where(Message.chat_id == chat_id, Message.role.in_(("user", "bot")))
            .order_by(Message.id.desc())
            .limit(settings.chat_history_messages)
        )
    ).all()
    turns: list[ChatTurn] = []
    for message in reversed(rows):
        if not message.content.strip():
            continue
        role: Literal["user", "assistant"] = "user" if message.role == "user" else "assistant"
        if turns and turns[-1].role == role:
            # The API wants alternating roles: merge neighbours (for example after a failed run).
            turns[-1] = ChatTurn(role, f"{turns[-1].content}\n\n{message.content}")
        else:
            turns.append(ChatTurn(role, message.content))
    while turns and turns[0].role != "user":
        turns.pop(0)
    return turns


async def run_agent(
    run_id: uuid.UUID,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings,
    llm: LLM | None,
    llm_error: LLMError | None = None,
) -> str:
    """Returns the run's final status."""
    async with session_factory() as session:
        run = await session.get(Run, run_id)
        if run is None or run.status != "queued" or run.chat_id is None:
            log.warning("run.skipped", run_id=str(run_id))
            return "skipped"
        bot = await session.get(Bot, run.bot_id)
        chat = await session.get(Chat, run.chat_id)
        if bot is None or chat is None:
            return "skipped"

        chat_id, user_id, bot_id = chat.id, run.user_id, bot.id
        chat_channel = events.chat_channel(chat_id)

        async def publish_status(status: str, **extra: object) -> None:
            await events.publish(
                redis,
                events.user_channel(user_id),
                "run.status",
                {
                    "run_id": str(run_id),
                    "chat_id": str(chat_id),
                    "bot_id": str(bot_id),
                    "status": status,
                    **extra,
                },
            )

        history = await _history(session, settings, chat_id)
        system = build_system_prompt(bot)

        run.status = "running"
        run.started_at = datetime.now(UTC)
        message = Message(chat_id=chat_id, role="bot", bot_id=bot_id, content="", run_id=run_id)
        session.add(message)
        await session.commit()
        await session.refresh(message)
        message_id = message.id

        await publish_status("running")
        await events.publish(
            redis,
            chat_channel,
            "message.created",
            {
                "chat_id": str(chat_id),
                "message": MessageOut.model_validate(message).model_dump(mode="json"),
            },
        )

        parts: list[str] = []
        length = 0
        last_saved = time.monotonic()

        async def on_delta(text: str) -> None:
            nonlocal length, last_saved
            if not text:
                return
            await events.publish(
                redis,
                chat_channel,
                "message.delta",
                {
                    "chat_id": str(chat_id),
                    "message_id": str(message_id),
                    "offset": length,
                    "text": text,
                },
            )
            parts.append(text)
            length += len(text)
            # Save the partial text now and then, so a reconnecting client can catch up.
            if time.monotonic() - last_saved >= settings.partial_save_seconds:
                message.content = "".join(parts)
                await session.commit()
                last_saved = time.monotonic()

        error: LLMError | None = llm_error
        input_tokens = output_tokens = 0
        try:
            if error is None and llm is not None:
                if not history:
                    raise LLMError("empty_chat", "There is no message to reply to.")
                result = await llm.stream(system=system, messages=history, on_delta=on_delta)
                input_tokens, output_tokens = result.input_tokens, result.output_tokens
        except LLMError as exc:
            error = exc
        except Exception as exc:  # the run must always end in a final status
            log.exception("run.crashed", run_id=str(run_id), error=type(exc).__name__)
            error = LLMError("run_failed", GENERIC_ERROR)

        text = "".join(parts)
        run.finished_at = datetime.now(UTC)
        run.steps = 1
        run.input_tokens = input_tokens
        run.output_tokens = output_tokens
        chat.last_message_at = run.finished_at

        if error is not None:
            run.status = "failed"
            run.error = error.message
            if text:
                message.content = text
            else:
                await session.delete(message)
            await session.commit()
            await publish_status(
                "failed",
                error={"code": error.code, "message": error.message},
                message_id=str(message_id),
                message_kept=bool(text),
            )
            log.warning("run.failed", run_id=str(run_id), code=error.code)
            return "failed"

        run.status = "completed"
        message.content = text
        await usage.add_usage(
            session, user_id, input_tokens=input_tokens, output_tokens=output_tokens
        )
        await session.commit()
        await events.publish(
            redis,
            chat_channel,
            "message.completed",
            {"chat_id": str(chat_id), "message_id": str(message_id), "length": length},
        )
        await publish_status("completed")
        log.info("run.completed", run_id=str(run_id), output_tokens=output_tokens)
        return "completed"
