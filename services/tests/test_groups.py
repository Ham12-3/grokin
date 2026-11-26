"""Group chats: mention routing, the picker, Bots asking each other, the turn cap, approvals."""

import uuid
from typing import Any

from sqlalchemy import select

from crew.chats import groups
from crew.llm.base import ToolUse
from crew.llm.fake import FakeLLM, Turn
from crew.models import Run
from tests.conftest import Ctx
from tests.helpers import API, connect_app, create_bot, run_worker, sign_in

EMAIL = {"to": "sam@example.com", "subject": "Hi", "body": "Hello"}


async def _group(ctx: Ctx) -> tuple[dict[str, str], dict[str, dict[str, Any]], str]:
    me = await sign_in(ctx, "a@example.com")
    bots = {
        "research": await create_bot(ctx, me, "Research Bot", job="Researches topics"),
        "writer": await create_bot(ctx, me, "Writer Bot", job="Writes and edits text"),
        "inbox": await create_bot(ctx, me, "Inbox Bot", job="Handles email"),
    }
    resp = await ctx.client.post(
        f"{API}/chats", headers=me, json={"bot_ids": [bot["id"] for bot in bots.values()]}
    )
    assert resp.status_code == 200, resp.text
    chat = resp.json()
    assert chat["kind"] == "group" and len(chat["bot_ids"]) == 3
    assert chat["title"] == "Research Bot, Writer Bot, Inbox Bot"
    return me, bots, chat["id"]


async def _say(ctx: Ctx, me: dict[str, str], chat_id: str, text: str) -> dict[str, Any]:
    ctx.queue.jobs.clear()
    resp = await ctx.client.post(
        f"{API}/chats/{chat_id}/messages", headers=me, json={"content": text}
    )
    assert resp.status_code == 202, resp.text
    body: dict[str, Any] = resp.json()
    return body


def _jobs(ctx: Ctx, name: str = "run_agent") -> list[tuple[object, ...]]:
    return [args for job, args in ctx.queue.jobs if job == name]


async def _next_run(ctx: Ctx) -> Run:
    """The run the queue was last asked to start."""
    (run_id,) = _jobs(ctx)[-1]
    async with ctx.session_factory() as session:
        run = await session.get(Run, uuid.UUID(str(run_id)))
    assert run is not None
    return run


async def _turn(ctx: Ctx, llm: FakeLLM) -> Run:
    run = await _next_run(ctx)
    ctx.queue.jobs.clear()
    assert await run_worker(ctx, str(run.id), llm) == "completed"
    return run


async def _messages(ctx: Ctx, me: dict[str, str], chat_id: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = (
        await ctx.client.get(f"{API}/chats/{chat_id}/messages", headers=me)
    ).json()["items"]
    return items


# --- Who answers ------------------------------------------------------------------------


async def test_a_mentioned_bot_answers_alone(ctx: Ctx) -> None:
    me, bots, chat_id = await _group(ctx)
    sent = await _say(ctx, me, chat_id, "@Research what is Tauri?")
    assert sent["run_id"] is not None and _jobs(ctx, "pick_responder") == []
    llm = FakeLLM(["Tauri is a desktop app toolkit."])
    run = await _turn(ctx, llm)

    assert str(run.bot_id) == bots["research"]["id"] and run.turn == 1
    assert _jobs(ctx) == []  # nobody else was asked: nobody else answers
    replies = [m for m in await _messages(ctx, me, chat_id) if m["role"] == "bot"]
    assert [(m["bot_id"], m["content"]) for m in replies] == [
        (bots["research"]["id"], "Tauri is a desktop app toolkit.")
    ]
    system = llm.calls[0]["system"]
    assert "## Group chat" in system and "- Writer Bot: Writes and edits text" in system
    assert "- Research Bot" not in system.split("## Group chat")[1]  # not listed to itself


async def test_several_mentions_answer_in_the_order_they_were_written(ctx: Ctx) -> None:
    me, bots, chat_id = await _group(ctx)
    await _say(ctx, me, chat_id, "@writer bot and @Research: introduce yourselves, @InboxBot too")
    order = []
    seen: list[FakeLLM] = []
    for reply in ("I write.", "I research.", "I handle mail."):
        llm = FakeLLM([reply])
        order.append(str((await _turn(ctx, llm)).bot_id))
        seen.append(llm)
    assert order == [bots["writer"]["id"], bots["research"]["id"], bots["inbox"]["id"]]
    assert _jobs(ctx) == []
    # The second Bot saw what the first one said, with its name, as something said to it.
    said = seen[1].calls[0]["messages"][-1]
    assert said["role"] == "user" and "Writer Bot: I write." in said["content"]
    # Its own earlier words are its own turns.
    await _say(ctx, me, chat_id, "@Research again please")
    again = FakeLLM(["Still researching."])
    await _turn(ctx, again)
    roles = [(m["role"], m["content"][:22]) for m in again.calls[0]["messages"]]
    assert ("assistant", "I research.") in roles


def test_mention_matching() -> None:
    class B:
        def __init__(self, name: str) -> None:
            self.id = uuid.uuid4()
            self.name = name

    research, writer = B("Research Bot"), B("Writer")
    bots: Any = [research, writer]
    assert groups.mentioned("@research, thoughts?", bots) == [research.id]
    assert groups.mentioned("hi @Writer and @Research Bot", bots) == [writer.id, research.id]
    assert groups.mentioned("@researchbot!", bots) == [research.id]
    assert groups.mentioned("email me at sam@writers.example", bots) == []  # not a mention
    assert groups.mentioned("research this, writer", bots) == []  # no @
    assert groups.mentioned("@Writer and @research", bots, exclude=writer.id) == [research.id]


async def test_an_unaddressed_message_gets_one_bot_from_the_picker(ctx: Ctx) -> None:
    me, bots, chat_id = await _group(ctx)
    sent = await _say(ctx, me, chat_id, "Can someone tidy up this paragraph?")
    assert sent["run_id"] is None and _jobs(ctx) == []
    ((picked_chat, message_id),) = _jobs(ctx, "pick_responder")
    assert picked_chat == chat_id

    picker = FakeLLM(["Writer Bot"])
    chosen = await groups.pick_responder(
        ctx.session_factory,
        ctx.redis,
        ctx.queue,
        ctx.settings,
        picker,
        uuid.UUID(chat_id),
        uuid.UUID(str(message_id)),
    )
    assert chosen == bots["writer"]["id"]
    prompt = picker.calls[0]["messages"][0]["content"]
    assert "- Inbox Bot: Handles email" in prompt and "User: Can someone tidy up" in prompt
    assert picker.calls[0]["tools"] == []
    run = await _turn(ctx, FakeLLM(["Here is a tidier version."]))
    assert str(run.bot_id) == bots["writer"]["id"]
    assert _jobs(ctx) == []  # one answer, not three


async def test_the_picker_may_choose_nobody(ctx: Ctx) -> None:
    me, _, chat_id = await _group(ctx)
    for answer in ("none", "Somebody Else", ""):
        sent = await _say(ctx, me, chat_id, "thanks all")
        (_, message_id) = _jobs(ctx, "pick_responder")[0]
        picked = await groups.pick_responder(
            ctx.session_factory,
            ctx.redis,
            ctx.queue,
            ctx.settings,
            FakeLLM([answer]),
            uuid.UUID(chat_id),
            uuid.UUID(str(message_id)),
        )
        assert picked == "none" and sent["run_id"] is None
    assert _jobs(ctx) == []
    notes = [m["content"] for m in await _messages(ctx, me, chat_id) if m["role"] == "system"]
    assert notes == [groups.NOBODY] * 3


# --- Bots talking to each other ---------------------------------------------------------


async def test_a_bot_can_ask_another_bot_which_answers_next(ctx: Ctx) -> None:
    me, bots, chat_id = await _group(ctx)
    await _say(ctx, me, chat_id, "@Research find the facts and get them written up")
    await _turn(ctx, FakeLLM(["Facts found. @Writer Bot please write them up."]))
    second = await _next_run(ctx)
    assert str(second.bot_id) == bots["writer"]["id"] and second.turn == 2
    await _turn(ctx, FakeLLM(["Written up."]))
    assert _jobs(ctx) == []  # the writer asked nobody


async def test_bots_stop_after_six_turns(ctx: Ctx) -> None:
    me, bots, chat_id = await _group(ctx)
    await _say(ctx, me, chat_id, "@Research and @Writer, debate this")
    speakers = []
    for _ in range(groups.MAX_TURNS):
        run = await _next_run(ctx)
        speakers.append(str(run.bot_id))
        other = "Writer Bot" if str(run.bot_id) == bots["research"]["id"] else "Research Bot"
        ctx.queue.jobs.clear()
        assert (
            await run_worker(ctx, str(run.id), FakeLLM([f"I disagree, @{other}."])) == "completed"
        )
    assert len(speakers) == 6 and _jobs(ctx) == []  # the seventh turn never starts
    async with ctx.session_factory() as session:
        runs = (await session.scalars(select(Run).order_by(Run.id))).all()
    assert [run.turn for run in runs] == [1, 2, 3, 4, 5, 6]
    notes = [m["content"] for m in await _messages(ctx, me, chat_id) if m["role"] == "system"]
    assert notes == ["The Bots stopped after 6 turns. Send a message to continue."]
    # A new message from the user starts a fresh count.
    await _say(ctx, me, chat_id, "@Writer sum it up")
    assert (await _next_run(ctx)).turn == 1


# --- Approvals --------------------------------------------------------------------------


async def test_an_approval_in_a_group_goes_to_the_bots_own_chat(ctx: Ctx) -> None:
    me, bots, chat_id = await _group(ctx)
    inbox = bots["inbox"]
    await connect_app(ctx, me, inbox, "gmail")
    await _say(ctx, me, chat_id, "@Inbox email Sam hello")
    run = await _next_run(ctx)
    llm = FakeLLM([Turn(["Drafting."], [ToolUse("toolu_1", "email_send", EMAIL)]), Turn(["Sent."])])
    ctx.queue.jobs.clear()
    assert await run_worker(ctx, str(run.id), llm) == "waiting_approval"

    # The group only gets a pointer; the card belongs to the Bot's direct chat.
    group_messages = await _messages(ctx, me, chat_id)
    assert (
        group_messages[-1]["content"]
        == "Drafting.\n\nI need your approval for this. Check your Approvals."
    )
    assert "sam@example.com" not in str(group_messages[-1])
    (approval,) = (await ctx.client.get(f"{API}/approvals?status=pending", headers=me)).json()
    assert approval["chat_id"] == inbox["direct_chat_id"] != chat_id

    # Approving continues the reply in the group.
    await ctx.client.post(f"{API}/approvals/{approval['id']}/approve", headers=me)
    assert await run_worker(ctx, str(run.id), llm) == "completed"
    last = (await _messages(ctx, me, chat_id))[-1]
    assert last["content"].endswith("Sent.") and last["bot_id"] == inbox["id"]


# --- Rules ------------------------------------------------------------------------------


async def test_group_limits_ownership_and_delete(ctx: Ctx) -> None:
    me, bots, chat_id = await _group(ctx)
    ids = [bot["id"] for bot in bots.values()]
    extra = [(await create_bot(ctx, me, f"Bot {n}"))["id"] for n in range(4)]
    too_many = await ctx.client.post(f"{API}/chats", headers=me, json={"bot_ids": ids + extra})
    assert too_many.status_code == 422  # more than 6

    other = await sign_in(ctx, "mallory@example.com")
    theirs = await create_bot(ctx, other)
    mixed = await ctx.client.post(
        f"{API}/chats", headers=me, json={"bot_ids": [ids[0], theirs["id"]]}
    )
    assert mixed.status_code == 404  # cannot add someone else's Bot
    assert (
        await ctx.client.get(f"{API}/chats/{chat_id}/messages", headers=other)
    ).status_code == 404
    assert (await ctx.client.delete(f"{API}/chats/{chat_id}", headers=other)).status_code == 404

    listed = (await ctx.client.get(f"{API}/chats", headers=me)).json()
    assert [chat["id"] for chat in listed if chat["kind"] == "group"] == [chat_id]
    direct = bots["research"]["direct_chat_id"]
    assert (await ctx.client.delete(f"{API}/chats/{direct}", headers=me)).status_code == 400
    assert (await ctx.client.delete(f"{API}/chats/{chat_id}", headers=me)).status_code == 204
    assert (await ctx.client.get(f"{API}/chats/{chat_id}/messages", headers=me)).status_code == 404
