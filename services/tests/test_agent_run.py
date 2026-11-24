"""The worker's agent run with a FakeLLM: streaming, saving, usage, failures."""

import asyncio
import json
from typing import Any

from sqlalchemy import text

from crew import events
from crew.agent.prompts import build_system_prompt
from crew.llm.base import LLMError
from crew.llm.fake import FakeLLM
from crew.models import Bot
from tests.conftest import Ctx
from tests.helpers import API, create_bot, run_worker, send, sign_in


class Listener:
    """Collects the events published on some Redis channels."""

    def __init__(self, ctx: Ctx, *channels: str) -> None:
        self._pubsub = ctx.redis.pubsub()
        self._channels = channels
        self.events: list[dict[str, Any]] = []

    async def __aenter__(self) -> "Listener":
        await self._pubsub.subscribe(*self._channels)
        return self

    async def __aexit__(self, *_: object) -> None:
        await asyncio.sleep(0.05)
        while True:
            item = await self._pubsub.get_message(timeout=0.1)
            if item is None:
                break
            if item["type"] == "message":
                self.events.append(json.loads(item["data"]))
        await self._pubsub.aclose()  # type: ignore[no-untyped-call]

    def of(self, event_type: str) -> list[dict[str, Any]]:
        return [event for event in self.events if event["type"] == event_type]


async def _setup(ctx: Ctx) -> tuple[dict[str, str], dict[str, Any], str]:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    user_id = (await ctx.client.get(f"{API}/me", headers=me)).json()["id"]
    return me, bot, user_id


async def test_run_streams_deltas_saves_the_message_and_records_usage(ctx: Ctx) -> None:
    me, bot, user_id = await _setup(ctx)
    chat_id = bot["direct_chat_id"]
    sent = await send(ctx, me, chat_id, "Say hello")
    llm = FakeLLM(["Hel", "lo ", "world"])

    async with Listener(ctx, events.chat_channel(chat_id), events.user_channel(user_id)) as seen:
        assert await run_worker(ctx, sent["run_id"], llm) == "completed"

    created = seen.of("message.created")
    assert len(created) == 1 and created[0]["message"]["role"] == "bot"
    message_id = created[0]["message"]["id"]
    deltas = seen.of("message.delta")
    assert [(d["offset"], d["text"]) for d in deltas] == [(0, "Hel"), (3, "lo "), (6, "world")]
    assert {d["message_id"] for d in deltas} == {message_id}
    assert seen.of("message.completed") == [
        {**seen.of("message.completed")[0], "message_id": message_id, "length": 11}
    ]
    assert [e["status"] for e in seen.of("run.status")] == ["running", "completed"]
    assert all(e["bot_id"] == bot["id"] for e in seen.of("run.status"))

    page = (await ctx.client.get(f"{API}/chats/{chat_id}/messages", headers=me)).json()
    assert [(m["role"], m["content"]) for m in page["items"]] == [
        ("user", "Say hello"),
        ("bot", "Hello world"),
    ]
    assert page["active_run_id"] is None

    async with ctx.engine.connect() as conn:
        run = (
            await conn.execute(
                text("SELECT status, steps, input_tokens, output_tokens, error FROM runs")
            )
        ).one()
    assert run.status == "completed" and run.steps == 1 and run.error is None
    assert run.output_tokens > 0

    profile = (await ctx.client.get(f"{API}/me", headers=me)).json()
    assert profile["input_tokens_today"] == run.input_tokens
    assert profile["output_tokens_today"] == run.output_tokens
    bots = (await ctx.client.get(f"{API}/bots", headers=me)).json()
    assert bots[0]["working"] is False


async def test_usage_adds_up_across_runs(ctx: Ctx) -> None:
    me, bot, _ = await _setup(ctx)
    total = 0
    for prompt in ("one", "two"):
        sent = await send(ctx, me, bot["direct_chat_id"], prompt)
        await run_worker(ctx, sent["run_id"], FakeLLM(["reply to ", prompt]))
        async with ctx.engine.connect() as conn:
            total = (await conn.execute(text("SELECT sum(output_tokens) FROM runs"))).scalar() or 0
    profile = (await ctx.client.get(f"{API}/me", headers=me)).json()
    assert profile["output_tokens_today"] == total > 0


async def test_llm_gets_the_bot_prompt_and_the_chat_history(ctx: Ctx) -> None:
    me, bot, _ = await _setup(ctx)
    chat_id = bot["direct_chat_id"]
    first = await send(ctx, me, chat_id, "My name is Sam")
    await run_worker(ctx, first["run_id"], FakeLLM(["Hi Sam"]))
    second = await send(ctx, me, chat_id, "What is my name?")
    llm = FakeLLM(["Sam"])
    await run_worker(ctx, second["run_id"], llm)

    system, history = llm.calls[0]
    assert "You are Inbox Bot, a teammate in Crew. Your job: Sorts my inbox." in system
    assert "Be brief." in system
    assert [(turn.role, turn.content) for turn in history] == [
        ("user", "My name is Sam"),
        ("assistant", "Hi Sam"),
        ("user", "What is my name?"),
    ]


async def test_failure_before_any_text_removes_the_placeholder(ctx: Ctx) -> None:
    me, bot, user_id = await _setup(ctx)
    chat_id = bot["direct_chat_id"]
    sent = await send(ctx, me, chat_id, "hello")
    llm = FakeLLM(error=LLMError("llm_rate_limited", "Claude is busy right now."))

    async with Listener(ctx, events.user_channel(user_id)) as seen:
        assert await run_worker(ctx, sent["run_id"], llm) == "failed"

    failed = seen.of("run.status")[-1]
    assert failed["status"] == "failed"
    assert failed["error"] == {"code": "llm_rate_limited", "message": "Claude is busy right now."}
    assert failed["message_kept"] is False

    page = (await ctx.client.get(f"{API}/chats/{chat_id}/messages", headers=me)).json()
    assert [m["role"] for m in page["items"]] == ["user"]
    profile = (await ctx.client.get(f"{API}/me", headers=me)).json()
    assert profile["output_tokens_today"] == 0

    # The chat is usable again, and the two user messages reach the LLM as one turn.
    again = await send(ctx, me, chat_id, "are you there?")
    retry = FakeLLM(["yes"])
    assert await run_worker(ctx, again["run_id"], retry) == "completed"
    assert [(t.role, t.content) for t in retry.calls[0][1]] == [("user", "hello\n\nare you there?")]


async def test_failure_mid_stream_keeps_the_partial_text(ctx: Ctx) -> None:
    me, bot, _ = await _setup(ctx)
    chat_id = bot["direct_chat_id"]
    sent = await send(ctx, me, chat_id, "hello")
    llm = FakeLLM(["Half an ", "answer"], fail_after=1)
    assert await run_worker(ctx, sent["run_id"], llm) == "failed"
    page = (await ctx.client.get(f"{API}/chats/{chat_id}/messages", headers=me)).json()
    assert [m["content"] for m in page["items"]] == ["hello", "Half an "]


async def test_unexpected_crash_fails_the_run_with_a_safe_message(ctx: Ctx) -> None:
    me, bot, _ = await _setup(ctx)
    sent = await send(ctx, me, bot["direct_chat_id"], "hello")

    class Broken:
        async def stream(self, **_: object) -> Any:
            raise RuntimeError("secret-internal-detail")

    assert await run_worker(ctx, sent["run_id"], Broken()) == "failed"
    async with ctx.engine.connect() as conn:
        error = (await conn.execute(text("SELECT error FROM runs"))).scalar()
    assert error == "Something went wrong while replying. Try again."


async def test_missing_api_key_fails_runs_with_a_clear_message(ctx: Ctx) -> None:
    me, bot, _ = await _setup(ctx)
    sent = await send(ctx, me, bot["direct_chat_id"], "hello")
    not_set = LLMError("llm_not_configured", "ANTHROPIC_API_KEY is not set on the server.")
    assert await run_worker(ctx, sent["run_id"], None, not_set) == "failed"
    async with ctx.engine.connect() as conn:
        error = (await conn.execute(text("SELECT error FROM runs"))).scalar()
    assert error == "ANTHROPIC_API_KEY is not set on the server."


async def test_a_run_is_only_executed_once(ctx: Ctx) -> None:
    me, bot, _ = await _setup(ctx)
    sent = await send(ctx, me, bot["direct_chat_id"], "hello")
    assert await run_worker(ctx, sent["run_id"], FakeLLM(["one"])) == "completed"
    second = FakeLLM(["two"])
    assert await run_worker(ctx, sent["run_id"], second) == "skipped"
    assert second.calls == []


def test_system_prompt_shape() -> None:
    bot = Bot(name="Research Bot", job="Finds facts", instructions="  Cite sources.  ")
    prompt = build_system_prompt(bot)
    assert prompt.startswith("You are Research Bot, a teammate in Crew. Your job: Finds facts.")
    assert "Cite sources." in prompt
    assert "<untrusted>" in prompt
    assert "no tools yet" in prompt
