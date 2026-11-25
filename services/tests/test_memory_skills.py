"""Memory, skills and Primary Bot handoff."""

import uuid
from typing import Any

from sqlalchemy import select

from crew.llm.base import ToolUse
from crew.llm.fake import FakeLLM, Turn
from crew.memory import service as memory_service
from crew.models import Memory, Run
from tests.conftest import Ctx
from tests.helpers import API, create_bot, run_worker, send, sign_in


def _use(name: str, **args: Any) -> ToolUse:
    return ToolUse(f"toolu_{uuid.uuid4().hex[:8]}", name, args)


async def _setup(ctx: Ctx, **bot_fields: str) -> tuple[dict[str, str], dict[str, Any]]:
    me = await sign_in(ctx, "a@example.com")
    return me, await create_bot(ctx, me, **bot_fields)


async def _reply(ctx: Ctx, me: dict[str, str], bot: dict[str, Any], text: str, llm: FakeLLM) -> str:
    sent = await send(ctx, me, bot["direct_chat_id"], text)
    assert await run_worker(ctx, sent["run_id"], llm) == "completed"
    run_id: str = sent["run_id"]
    return run_id


async def _memory(ctx: Ctx, me: dict[str, str], bot: dict[str, Any]) -> list[dict[str, Any]]:
    lines: list[dict[str, Any]] = (
        await ctx.client.get(f"{API}/bots/{bot['id']}/memory", headers=me)
    ).json()
    return lines


# --- Memory -----------------------------------------------------------------------------


async def test_a_remembered_line_is_in_the_next_prompt_and_a_deleted_one_is_not(ctx: Ctx) -> None:
    me, bot = await _setup(ctx)
    llm = FakeLLM(
        [
            Turn([], [_use("memory_add", text="Prefers short  bullet\nsummaries")]),
            Turn(["Noted."]),
            Turn(["Here you go."]),
            Turn(["Sure."]),
        ]
    )
    await _reply(ctx, me, bot, "I prefer short bullet summaries", llm)
    assert "What you remember" not in llm.calls[0]["system"]

    (line,) = await _memory(ctx, me, bot)
    assert line["text"] == "Prefers short bullet summaries"  # one clean line

    # A later message: the line is in the prompt, with the id the Bot can remove it by.
    await _reply(ctx, me, bot, "Summarise the news", llm)
    system = llm.calls[2]["system"]
    assert "## What you remember about this user" in system
    assert f"- [{line['id'].replace('-', '')[-8:]}] Prefers short bullet summaries" in system

    # The user deletes it: gone from the next prompt.
    gone = await ctx.client.delete(f"{API}/bots/{bot['id']}/memory/{line['id']}", headers=me)
    assert gone.status_code == 204
    await _reply(ctx, me, bot, "And again", llm)
    assert "Prefers short bullet summaries" not in llm.calls[3]["system"]


async def test_the_bot_can_forget_a_line_and_repeats_are_not_stored_twice(ctx: Ctx) -> None:
    me, bot = await _setup(ctx)
    llm = FakeLLM(
        [
            Turn(
                [],
                [
                    _use("memory_add", text="Lives in Lagos"),
                    _use("memory_add", text="lives in lagos"),
                ],
            ),
            Turn(["ok"]),
        ]
    )
    await _reply(ctx, me, bot, "I live in Lagos", llm)
    (line,) = await _memory(ctx, me, bot)

    short = line["id"].replace("-", "")[-8:]
    forget = FakeLLM(
        [
            Turn([], [_use("memory_remove", id=short), _use("memory_remove", id="nope1234")]),
            Turn(["ok"]),
        ]
    )
    await _reply(ctx, me, bot, "Forget where I live", forget)
    assert await _memory(ctx, me, bot) == []
    results = forget.calls[1]["messages"][-1]["content"]
    assert "is_error" not in results[0] and results[1]["is_error"] is True


async def test_the_user_can_add_edit_and_delete_lines_and_nobody_else_can(ctx: Ctx) -> None:
    me, bot = await _setup(ctx)
    base = f"{API}/bots/{bot['id']}/memory"
    added = await ctx.client.post(base, headers=me, json={"text": " Works at <Acme> "})
    assert added.status_code == 201 and added.json()["text"] == "Works at Acme"
    line_id = added.json()["id"]
    edited = await ctx.client.patch(
        f"{base}/{line_id}", headers=me, json={"text": "Works at Initech"}
    )
    assert edited.json()["text"] == "Works at Initech"
    assert (await ctx.client.post(base, headers=me, json={"text": "   "})).status_code == 422

    other = await sign_in(ctx, "mallory@example.com")
    assert (await ctx.client.get(base, headers=other)).status_code == 404
    assert (await ctx.client.post(base, headers=other, json={"text": "x y z"})).status_code == 404
    for method in ("patch", "delete"):
        resp = await getattr(ctx.client, method)(
            f"{base}/{line_id}",
            headers=other,
            **({"json": {"text": "hacked"}} if method == "patch" else {}),
        )
        assert resp.status_code == 404
    assert [line["text"] for line in await _memory(ctx, me, bot)] == ["Works at Initech"]


async def test_long_memory_is_merged_in_the_background(ctx: Ctx) -> None:
    me, bot = await _setup(ctx)
    bot_id = uuid.UUID(bot["id"])
    user_id = uuid.UUID((await ctx.client.get(f"{API}/me", headers=me)).json()["id"])
    async with ctx.session_factory() as session:
        session.add_all(
            Memory(bot_id=bot_id, user_id=user_id, text=f"Likes tea, note {n} " + "x" * 250)
            for n in range(31)
        )
        await session.commit()

    # One more line tips it over about 2k tokens: the tool queues the tidy-up job.
    llm = FakeLLM([Turn([], [_use("memory_add", text="Prefers mornings")]), Turn(["ok"])])
    ctx.queue.jobs.clear()
    await _reply(ctx, me, bot, "I prefer mornings", llm)
    assert ("compact_memory", (bot["id"],)) in ctx.queue.jobs

    merger = FakeLLM(["- Likes tea\n", "2. Prefers mornings\n", "Likes tea\n"])
    assert await memory_service.compact_memory(ctx.session_factory, merger, bot_id) == "compacted"
    assert "Likes tea, note 3" in merger.calls[0]["messages"][0]["content"]
    assert sorted(line["text"] for line in await _memory(ctx, me, bot)) == [
        "2. Prefers mornings",
        "Likes tea",
    ]
    # Short again: nothing to do, and a useless answer never wipes memory.
    assert await memory_service.compact_memory(ctx.session_factory, merger, bot_id) == "not_needed"


async def test_a_merge_that_does_not_shrink_memory_changes_nothing(ctx: Ctx) -> None:
    me, bot = await _setup(ctx)
    bot_id = uuid.UUID(bot["id"])
    user_id = uuid.UUID((await ctx.client.get(f"{API}/me", headers=me)).json()["id"])
    async with ctx.session_factory() as session:
        session.add_all(
            Memory(bot_id=bot_id, user_id=user_id, text=f"Fact {n} " + "y" * 280) for n in range(30)
        )
        await session.commit()
    for answer in ([""], ["\n".join(f"line {n}" for n in range(40))]):
        assert (
            await memory_service.compact_memory(ctx.session_factory, FakeLLM(answer), bot_id)
            == "unchanged"
        )
    assert len(await _memory(ctx, me, bot)) == 30


# --- Skills -----------------------------------------------------------------------------

SKILL = {
    "name": "Weekly Report",
    "description": "Summarise the week",
    "steps": "1. Read notes.md\n2. Write a summary to report.md",
    "rules": "Never email it.",
}


async def test_skill_crud_and_slugs(ctx: Ctx) -> None:
    me, bot = await _setup(ctx)
    base = f"{API}/bots/{bot['id']}/skills"
    first = await ctx.client.post(base, headers=me, json=SKILL)
    assert first.status_code == 201, first.text
    assert first.json()["slug"] == "weekly-report"
    second = await ctx.client.post(base, headers=me, json=SKILL)
    assert second.json()["slug"] == "weekly-report-2"
    assert (
        await ctx.client.post(base, headers=me, json={**SKILL, "steps": "  "})
    ).status_code == 422

    skill_id = first.json()["id"]
    edited = await ctx.client.patch(
        f"{API}/skills/{skill_id}", headers=me, json={"steps": "1. Just do it"}
    )
    assert edited.json()["steps"] == "1. Just do it" and edited.json()["slug"] == "weekly-report"

    other = await sign_in(ctx, "mallory@example.com")
    assert (await ctx.client.get(base, headers=other)).status_code == 404
    assert (
        await ctx.client.patch(f"{API}/skills/{skill_id}", headers=other, json={"name": "x"})
    ).status_code == 404
    assert (await ctx.client.delete(f"{API}/skills/{skill_id}", headers=other)).status_code == 404

    assert (await ctx.client.delete(f"{API}/skills/{skill_id}", headers=me)).status_code == 204
    assert [skill["slug"] for skill in (await ctx.client.get(base, headers=me)).json()] == [
        "weekly-report-2"
    ]


async def test_a_run_started_with_a_skill_has_its_steps_in_the_prompt(ctx: Ctx) -> None:
    me, bot = await _setup(ctx)
    skill = (await ctx.client.post(f"{API}/bots/{bot['id']}/skills", headers=me, json=SKILL)).json()
    llm = FakeLLM([Turn(["Done."]), Turn(["Hi."])])

    resp = await ctx.client.post(
        f"{API}/chats/{bot['direct_chat_id']}/messages",
        headers=me,
        json={"content": "/weekly-report", "skill_id": skill["id"]},
    )
    assert resp.status_code == 202, resp.text
    assert await run_worker(ctx, resp.json()["run_id"], llm) == "completed"
    system = llm.calls[0]["system"]
    assert "## Skill to run now: Weekly Report" in system
    assert "2. Write a summary to report.md" in system and "Never email it." in system

    # A normal message lists the skill but does not include its steps.
    await _reply(ctx, me, bot, "hello", llm)
    system = llm.calls[1]["system"]
    assert "- /weekly-report: Weekly Report (Summarise the week)" in system
    assert "Write a summary to report.md" not in system


async def test_a_skill_of_another_bot_or_user_cannot_be_run(ctx: Ctx) -> None:
    me, bot = await _setup(ctx)
    other_bot = await create_bot(ctx, me, name="Other Bot")
    foreign = (
        await ctx.client.post(f"{API}/bots/{other_bot['id']}/skills", headers=me, json=SKILL)
    ).json()
    mallory = await sign_in(ctx, "mallory@example.com")
    mallory_bot = await create_bot(ctx, mallory)
    theirs = (
        await ctx.client.post(f"{API}/bots/{mallory_bot['id']}/skills", headers=mallory, json=SKILL)
    ).json()
    for skill_id in (foreign["id"], theirs["id"], str(uuid.uuid4())):
        resp = await ctx.client.post(
            f"{API}/chats/{bot['direct_chat_id']}/messages",
            headers=me,
            json={"content": "/x", "skill_id": skill_id},
        )
        assert resp.status_code == 404
    async with ctx.session_factory() as session:
        assert (await session.scalars(select(Run))).all() == []


async def test_skill_save_makes_a_draft_and_only_save_creates_the_skill(ctx: Ctx) -> None:
    me, bot = await _setup(ctx)
    chat = bot["direct_chat_id"]
    llm = FakeLLM(
        [
            Turn(["Drafted."], [ToolUse("toolu_skill", "skill_save", dict(SKILL))]),
            Turn(["Check the draft."]),
        ]
    )
    await _reply(ctx, me, bot, "save that as a skill", llm)

    skills_url = f"{API}/bots/{bot['id']}/skills"
    assert (await ctx.client.get(skills_url, headers=me)).json() == []  # nothing saved yet
    page = (await ctx.client.get(f"{API}/chats/{chat}/messages", headers=me)).json()
    (draft,) = [m for m in page["items"] if m["card"]]
    assert draft["role"] == "system"
    assert draft["card"] == {"type": "skill_draft", "status": "draft", **SKILL}

    other = await sign_in(ctx, "mallory@example.com")
    stolen = await ctx.client.post(
        f"{API}/chats/{chat}/skill-drafts/{draft['id']}/save", headers=other
    )
    assert stolen.status_code == 404

    saved = await ctx.client.post(f"{API}/chats/{chat}/skill-drafts/{draft['id']}/save", headers=me)
    assert saved.status_code == 200, saved.text
    assert (
        saved.json()["card"]["status"] == "saved"
        and saved.json()["card"]["slug"] == "weekly-report"
    )
    (skill,) = (await ctx.client.get(skills_url, headers=me)).json()
    assert skill["steps"] == SKILL["steps"] and skill["id"] == saved.json()["card"]["skill_id"]
    # Saving twice does not make two skills; the card is not part of what the model reads.
    again = await ctx.client.post(f"{API}/chats/{chat}/skill-drafts/{draft['id']}/save", headers=me)
    assert again.status_code == 409
    follow = FakeLLM(["ok"])
    await _reply(ctx, me, bot, "thanks", follow)
    assert all(isinstance(m["content"], str) for m in follow.calls[0]["messages"])
    assert not any("skill_draft" in str(m["content"]) for m in follow.calls[0]["messages"])


async def test_a_cancelled_draft_saves_nothing(ctx: Ctx) -> None:
    me, bot = await _setup(ctx)
    chat = bot["direct_chat_id"]
    llm = FakeLLM([Turn([], [ToolUse("toolu_skill", "skill_save", dict(SKILL))]), Turn(["ok"])])
    await _reply(ctx, me, bot, "save that as a skill", llm)
    page = (await ctx.client.get(f"{API}/chats/{chat}/messages", headers=me)).json()
    (draft,) = [m for m in page["items"] if m["card"]]
    cancelled = await ctx.client.post(
        f"{API}/chats/{chat}/skill-drafts/{draft['id']}/cancel", headers=me
    )
    assert cancelled.json()["card"]["status"] == "cancelled"
    late = await ctx.client.post(f"{API}/chats/{chat}/skill-drafts/{draft['id']}/save", headers=me)
    assert late.status_code == 409
    assert (await ctx.client.get(f"{API}/bots/{bot['id']}/skills", headers=me)).json() == []


# --- Handoff ----------------------------------------------------------------------------


async def test_the_primary_bot_hands_a_task_to_the_right_bot(ctx: Ctx) -> None:
    me, primary = await _setup(ctx, name="Primary Bot", job="Routes requests")
    research = await create_bot(ctx, me, name="Research Bot", job="Researches topics")
    await create_bot(ctx, me, name="Inbox Bot", job="Sorts email")
    ref = research["id"].replace("-", "")[-8:]
    llm = FakeLLM(
        [
            Turn([], [_use("handoff", bot_id=ref, task="Research the history of Tauri")]),
            Turn(["I've passed this to Research Bot."]),
        ]
    )
    ctx.queue.jobs.clear()
    await _reply(ctx, me, primary, "Research the history of Tauri", llm)

    # The Primary Bot was told who is on the team and was offered the tool.
    system = llm.calls[0]["system"]
    assert (
        f"- [{ref}] Research Bot: Researches topics" in system
        and "Inbox Bot: Sorts email" in system
    )
    assert "handoff" in {tool["name"] for tool in llm.calls[0]["tools"]}

    # A run was queued for Research Bot, in its own chat, with the task as the message.
    async with ctx.session_factory() as session:
        runs = (
            await session.scalars(select(Run).where(Run.bot_id == uuid.UUID(research["id"])))
        ).all()
    assert [(str(run.chat_id), run.status) for run in runs] == [
        (research["direct_chat_id"], "queued")
    ]
    assert ("run_agent", (str(runs[0].id),)) in ctx.queue.jobs
    theirs = (
        await ctx.client.get(f"{API}/chats/{research['direct_chat_id']}/messages", headers=me)
    ).json()["items"]
    assert [(m["role"], m["content"]) for m in theirs] == [
        ("user", "Research the history of Tauri")
    ]
    assert theirs[0]["card"] == {
        "type": "handoff_from",
        "bot_id": primary["id"],
        "bot_name": "Primary Bot",
        "chat_id": primary["direct_chat_id"],
    }
    # The Primary Bot's chat links to it.
    mine = (
        await ctx.client.get(f"{API}/chats/{primary['direct_chat_id']}/messages", headers=me)
    ).json()["items"]
    (card,) = [m["card"] for m in mine if m["card"]]
    assert card == {
        "type": "handoff",
        "bot_id": research["id"],
        "bot_name": "Research Bot",
        "chat_id": research["direct_chat_id"],
    }

    # Research Bot does the work; it is not offered handoff and sees no Bot list.
    worker = FakeLLM(["Tauri began in 2019."])
    assert await run_worker(ctx, str(runs[0].id), worker) == "completed"
    assert "handoff" not in {tool["name"] for tool in worker.calls[0]["tools"]}
    assert "## Other Bots" not in worker.calls[0]["system"]
    assert worker.calls[0]["messages"][-1]["content"] == "Research the history of Tauri"


async def test_handoff_is_refused_for_other_bots_unknown_targets_and_busy_bots(ctx: Ctx) -> None:
    me, primary = await _setup(ctx, name="Primary Bot")
    research = await create_bot(ctx, me, name="Research Bot")
    mallory = await sign_in(ctx, "mallory@example.com")
    theirs = await create_bot(ctx, mallory, name="Their Bot")

    async def result(bot: dict[str, Any], target: str) -> dict[str, Any]:
        llm = FakeLLM(
            [Turn([], [_use("handoff", bot_id=target, task="do the thing")]), Turn(["ok"])]
        )
        await _reply(ctx, me, bot, "go", llm)
        block: dict[str, Any] = llm.calls[1]["messages"][-1]["content"][0]
        return block

    # A Bot that is not the Primary Bot cannot hand off, even if it asks for the tool.
    refused = await result(research, primary["id"])
    assert refused["is_error"] is True and "Only the Primary Bot" in refused["content"]
    # Another user's Bot is not a target.
    unknown = await result(primary, theirs["id"])
    assert unknown["is_error"] is True and "no other Bot" in unknown["content"]
    # By name works; a second task while that Bot is still busy is refused clearly.
    assert "is_error" not in await result(primary, "research bot")
    busy = await result(primary, "Research Bot")
    assert busy["is_error"] is True and "busy" in busy["content"]
    async with ctx.session_factory() as session:
        runs = (
            await session.scalars(select(Run).where(Run.bot_id == uuid.UUID(research["id"])))
        ).all()
    assert len([run for run in runs if run.status == "queued"]) == 1
