"""Manual smoke test against the REAL Anthropic API. Local use only: never run in CI.

It spends a small number of tokens. It needs Postgres and Redis (`make up`, `make migrate`)
and ANTHROPIC_API_KEY + CREW_MODEL. It creates a temporary user, runs two requests through
the real agent loop (a plain reply, then a fetch-and-write task) and deletes everything.

    cd services && uv run python scripts/smoke_live.py
"""

import asyncio
import shutil
import sys
import uuid
from pathlib import Path

import httpx
from redis.asyncio import Redis
from sqlalchemy import delete, select

from crew.agent.loop import run_agent
from crew.computer import create_provider
from crew.computer.provider import ComputerError
from crew.config import get_settings
from crew.db import create_engine, create_session_factory
from crew.llm import LLMError, create_llm
from crew.models import Bot, Chat, ChatMember, Message, Run, ToolCall, User
from crew.tools import default_registry

REQUESTS = [
    "Reply with exactly: Crew smoke test OK",
    "Fetch https://example.com and write a one-sentence summary of the page to smoke.md. "
    "Then tell me the file path.",
]


async def main() -> int:
    settings = get_settings()
    try:
        llm = create_llm(settings)
    except LLMError as error:
        print(f"Not configured: {error.message}")
        return 2
    print(f"Model: {settings.crew_model}")

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    http = httpx.AsyncClient(follow_redirects=False)
    registry = default_registry()
    provider = create_provider(settings)
    email = f"smoke-{uuid.uuid4().hex[:10]}@example.com"
    failed = False

    async with session_factory() as session:
        user = User(email=email)
        session.add(user)
        await session.flush()
        bot = Bot(user_id=user.id, name="Smoke Bot", job="Runs a quick self-test", is_primary=True)
        chat = Chat(user_id=user.id, kind="direct")
        session.add_all([bot, chat])
        await session.flush()
        session.add(ChatMember(chat_id=chat.id, bot_id=bot.id))
        await session.commit()
        user_id, bot_id, chat_id = user.id, bot.id, chat.id

    try:
        for request in REQUESTS:
            async with session_factory() as session:
                run = Run(user_id=user_id, bot_id=bot_id, chat_id=chat_id, status="queued")
                session.add(run)
                await session.flush()
                session.add(Message(chat_id=chat_id, role="user", content=request, run_id=run.id))
                await session.commit()
                run_id = run.id

            print(f"\n> {request}")
            status = await run_agent(
                run_id,
                session_factory=session_factory,
                redis=redis,
                settings=settings,
                llm=llm,
                registry=registry,
                http=http,
                provider=provider,
            )
            async with session_factory() as session:
                finished = await session.get(Run, run_id)
                reply = await session.scalar(
                    select(Message).where(Message.run_id == run_id, Message.role == "bot")
                )
                calls = (
                    await session.scalars(
                        select(ToolCall).where(ToolCall.run_id == run_id).order_by(ToolCall.id)
                    )
                ).all()
            assert finished is not None
            for call in calls:
                print(f"  [{call.status}] {call.summary} -> {call.result_summary}")
            print(f"  reply: {reply.content if reply else '(none)'}")
            print(
                f"  status={status} steps={finished.steps} "
                f"tokens={finished.input_tokens} in / {finished.output_tokens} out "
                f"error={finished.error}"
            )
            failed = failed or status != "completed" or finished.error is not None

        try:
            handle = await provider.ensure(user_id)
            written = (await provider.read_file(handle, "smoke.md")).decode()
        except ComputerError:
            written = None
        if written is not None:
            print(f"\nsmoke.md: {written.strip()}")
        else:
            print("\nsmoke.md was NOT written")
            failed = True
    finally:
        async with session_factory() as session:
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()
        shutil.rmtree(Path(settings.workspaces_dir) / str(user_id), ignore_errors=True)
        await provider.aclose()
        await http.aclose()
        await redis.aclose()
        await engine.dispose()

    print("\nFAILED" if failed else "\nOK")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
