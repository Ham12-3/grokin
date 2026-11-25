"""Approvals: a risky call stops the run, and only the user's answer continues it."""

import dataclasses
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import select, text

from crew import events
from crew.approvals import gate
from crew.llm.base import ToolUse
from crew.llm.fake import FakeLLM, Turn
from crew.models import ConnectorLog, Run, ToolCall
from crew.tools import default_registry
from tests.conftest import Ctx
from tests.helpers import API, Listener, create_bot, run_worker, send, sign_in, tool_context

EMAIL = {"to": "sam@example.com", "subject": "Report", "body": "The report is ready."}


def _use(name: str, **args: Any) -> ToolUse:
    return ToolUse(f"toolu_{uuid.uuid4().hex[:8]}", name, args)


async def _setup(ctx: Ctx, **bot_fields: str) -> tuple[dict[str, str], dict[str, Any], str]:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me, **bot_fields)
    user_id = (await ctx.client.get(f"{API}/me", headers=me)).json()["id"]
    return me, bot, user_id


async def _pending(ctx: Ctx, me: dict[str, str]) -> list[dict[str, Any]]:
    resp = await ctx.client.get(f"{API}/approvals?status=pending", headers=me)
    assert resp.status_code == 200, resp.text
    items: list[dict[str, Any]] = resp.json()
    return items


async def _tool_calls(ctx: Ctx, me: dict[str, str], run_id: str) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = (
        await ctx.client.get(f"{API}/runs/{run_id}/tool-calls", headers=me)
    ).json()
    return calls


async def _log(ctx: Ctx) -> list[dict[str, Any]]:
    async with ctx.session_factory() as session:
        rows = await session.scalars(select(ConnectorLog).order_by(ConnectorLog.id))
        return [{"tool": row.tool, **row.payload} for row in rows.all()]


async def _email_run(ctx: Ctx, **bot_fields: str) -> tuple[dict[str, str], str, FakeLLM]:
    """A run that drafted an email and now waits for approval."""
    me, bot, _ = await _setup(ctx, **bot_fields)
    sent = await send(ctx, me, bot["direct_chat_id"], "Email Sam that the report is ready")
    llm = FakeLLM(
        [
            Turn(["Drafting the email."], [_use("email_send", **EMAIL)]),
            Turn(["All done."]),
        ]
    )
    assert await run_worker(ctx, sent["run_id"], llm) == "waiting_approval"
    return me, sent["run_id"], llm


# --- A risky call stops the run ---------------------------------------------------------


async def test_a_risky_call_stops_the_run_and_creates_an_approval(ctx: Ctx) -> None:
    me, bot, user_id = await _setup(ctx)
    sent = await send(ctx, me, bot["direct_chat_id"], "Email Sam")
    llm = FakeLLM([Turn(["Drafting."], [_use("email_send", **EMAIL)]), Turn(["Done."])])
    async with Listener(ctx, events.user_channel(user_id)) as seen:
        assert await run_worker(ctx, sent["run_id"], llm) == "waiting_approval"

    assert await _log(ctx) == []  # nothing was sent
    assert len(llm.calls) == 1  # and the model was not asked again
    run = (await ctx.client.get(f"{API}/runs/{sent['run_id']}", headers=me)).json()
    assert run["status"] == "waiting_approval" and run["finished_at"] is None
    calls = await _tool_calls(ctx, me, sent["run_id"])
    assert [(c["tool"], c["risk"], c["status"]) for c in calls] == [
        ("email_send", "risky", "waiting_approval")
    ]
    assert calls[0]["started_at"] is None

    (approval,) = await _pending(ctx, me)
    assert approval["title"] == "Send email to sam@example.com"
    assert approval["preview"] == {"kind": "email", "fields": EMAIL, "context": {}}
    assert approval["bot_id"] == bot["id"] and approval["chat_id"] == bot["direct_chat_id"]

    assert [e["approval"]["id"] for e in seen.of("approval.created")] == [approval["id"]]
    assert seen.of("run.status")[-1]["status"] == "waiting_approval"
    # The reply so far is saved, and the chat stays busy until the user answers.
    page = (
        await ctx.client.get(f"{API}/chats/{bot['direct_chat_id']}/messages", headers=me)
    ).json()
    assert page["items"][-1]["content"] == "Drafting."
    assert page["active_run_id"] == sent["run_id"]
    again = await ctx.client.post(
        f"{API}/chats/{bot['direct_chat_id']}/messages", headers=me, json={"content": "hello?"}
    )
    assert again.status_code == 409


async def test_never_ask_still_asks_for_email_send(ctx: Ctx) -> None:
    me, _, _ = await _email_run(ctx, approval_mode="never_ask")
    assert len(await _pending(ctx, me)) == 1
    assert await _log(ctx) == []


async def test_always_ask_asks_for_writes_but_not_reads(ctx: Ctx) -> None:
    me, bot, user_id = await _setup(ctx, approval_mode="always_ask")
    sent = await send(ctx, me, bot["direct_chat_id"], "list then write")
    llm = FakeLLM(
        [
            Turn([], [_use("files_list"), _use("files_write", path="a.md", content="x")]),
            Turn(["done"]),
        ]
    )
    assert await run_worker(ctx, sent["run_id"], llm) == "waiting_approval"
    target = Path(ctx.settings.workspaces_dir) / user_id / "a.md"
    assert not target.exists()
    calls = await _tool_calls(ctx, me, sent["run_id"])
    assert [(c["tool"], c["status"]) for c in calls] == [
        ("files_list", "ok"),
        ("files_write", "waiting_approval"),
    ]
    (approval,) = await _pending(ctx, me)
    assert approval["preview"]["kind"] == "generic"
    assert approval["preview"]["fields"] == {"path": "a.md", "content": "x"}

    await ctx.client.post(f"{API}/approvals/{approval['id']}/approve", headers=me)
    assert await run_worker(ctx, sent["run_id"], llm) == "completed"
    assert target.read_text(encoding="utf-8") == "x"
    # The read that already ran was not repeated, and the model got both results in order.
    calls = await _tool_calls(ctx, me, sent["run_id"])
    assert [(c["tool"], c["status"]) for c in calls] == [
        ("files_list", "ok"),
        ("files_write", "ok"),
    ]
    results = llm.calls[1]["messages"][-1]["content"]
    assert [block["tool_use_id"] for block in results] == [
        use["id"] for use in llm.calls[1]["messages"][-2]["content"] if use["type"] == "tool_use"
    ]


# --- Approve ----------------------------------------------------------------------------


async def test_approve_runs_the_call_once_and_the_run_continues(ctx: Ctx) -> None:
    me, run_id, llm = await _email_run(ctx)
    (approval,) = await _pending(ctx, me)
    ctx.queue.jobs.clear()

    resp = await ctx.client.post(f"{API}/approvals/{approval['id']}/approve", headers=me)
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "approved"
    assert ctx.queue.jobs == [("run_agent", (run_id,))]
    assert await _pending(ctx, me) == []

    assert await run_worker(ctx, run_id, llm) == "completed"
    assert await _log(ctx) == [{"tool": "email_send", **EMAIL}]
    calls = await _tool_calls(ctx, me, run_id)
    assert [(c["status"], c["result_summary"]) for c in calls] == [
        ("ok", "Sent an email to sam@example.com")
    ]
    result = llm.calls[1]["messages"][-1]["content"][0]
    assert "is_error" not in result and "was sent" in result["content"]
    # One reply, continued after the approval.
    run = (await ctx.client.get(f"{API}/runs/{run_id}", headers=me)).json()
    chat_id = run["chat_id"]
    page = (await ctx.client.get(f"{API}/chats/{chat_id}/messages", headers=me)).json()
    assert [m["role"] for m in page["items"]] == ["user", "bot"]
    assert page["items"][-1]["content"] == "Drafting the email.\n\nAll done."


async def test_approve_with_edits_runs_the_edited_args_exactly_once(ctx: Ctx) -> None:
    me, run_id, llm = await _email_run(ctx)
    (approval,) = await _pending(ctx, me)
    edited = {**EMAIL, "subject": "Q3 report is ready"}

    resp = await ctx.client.post(
        f"{API}/approvals/{approval['id']}/approve", headers=me, json={"edited_args": edited}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["preview"]["fields"] == edited
    assert await run_worker(ctx, run_id, llm) == "completed"
    assert await _log(ctx) == [{"tool": "email_send", **edited}]

    # Answering again, or the worker picking the job up again, changes nothing.
    second = await ctx.client.post(f"{API}/approvals/{approval['id']}/approve", headers=me)
    assert second.status_code == 409
    assert await run_worker(ctx, run_id, llm) == "skipped"
    assert len(await _log(ctx)) == 1


async def test_edits_are_checked_against_the_tool_schema(ctx: Ctx) -> None:
    me, run_id, _ = await _email_run(ctx)
    (approval,) = await _pending(ctx, me)
    for bad in ({"to": "not-an-address", "subject": "x", "body": "y"}, {"subject": "x"}, {}):
        resp = await ctx.client.post(
            f"{API}/approvals/{approval['id']}/approve", headers=me, json={"edited_args": bad}
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["error"]["code"] == "invalid_edit"
    # Still waiting, nothing queued or sent.
    assert len(await _pending(ctx, me)) == 1
    run = (await ctx.client.get(f"{API}/runs/{run_id}", headers=me)).json()
    assert run["status"] == "waiting_approval"
    assert await _log(ctx) == []


# --- Reject -----------------------------------------------------------------------------


async def test_reject_tells_the_bot_and_nothing_is_sent(ctx: Ctx) -> None:
    me, run_id, llm = await _email_run(ctx)
    (approval,) = await _pending(ctx, me)
    resp = await ctx.client.post(
        f"{API}/approvals/{approval['id']}/reject", headers=me, json={"reason": "not yet"}
    )
    assert resp.status_code == 200 and resp.json()["status"] == "rejected"

    assert await run_worker(ctx, run_id, llm) == "completed"
    assert await _log(ctx) == []
    result = llm.calls[1]["messages"][-1]["content"][0]
    assert result["is_error"] is True
    assert "The user rejected this action" in result["content"]
    calls = await _tool_calls(ctx, me, run_id)
    assert [(c["status"], c["result_summary"]) for c in calls] == [
        ("rejected", "You rejected this")
    ]
    assert calls[0]["started_at"] is None


# --- Only the owner, only through the endpoint -------------------------------------------


async def test_another_user_cannot_see_or_answer_an_approval(ctx: Ctx) -> None:
    me, _, _ = await _email_run(ctx)
    (approval,) = await _pending(ctx, me)
    other = await sign_in(ctx, "mallory@example.com")

    assert await _pending(ctx, other) == []
    for action in ("approve", "reject"):
        resp = await ctx.client.post(f"{API}/approvals/{approval['id']}/{action}", headers=other)
        assert resp.status_code == 404
    assert (await ctx.client.post(f"{API}/approvals/{approval['id']}/approve")).status_code == 401
    assert len(await _pending(ctx, me)) == 1
    assert await _log(ctx) == []


async def _risky_row(ctx: Ctx, run_id: str) -> ToolCall:
    async with ctx.session_factory() as session:
        row = await session.scalar(select(ToolCall).where(ToolCall.run_id == uuid.UUID(run_id)))
    assert row is not None
    return row


@pytest.mark.parametrize("state", ["pending", "rejected", "expired", "missing", "other_user"])
async def test_the_worker_refuses_a_risky_call_without_an_approved_row(
    ctx: Ctx, tmp_path: Path, state: str
) -> None:
    """Defence in depth: the gate decides from the database, not from what the loop thinks."""
    _, run_id, _ = await _email_run(ctx)
    row = await _risky_row(ctx, run_id)
    registry = default_registry()
    tool = registry.get("email_send")
    assert tool is not None
    async with ctx.session_factory() as session:
        if state == "missing":
            await session.execute(text("DELETE FROM approvals"))
        elif state == "other_user":
            # An approved row that belongs to someone else does not count.
            await sign_in(ctx, "mallory@example.com")
            await session.execute(
                text(
                    "UPDATE approvals SET status = 'approved', user_id = "
                    "(SELECT id FROM users WHERE email = 'mallory@example.com')"
                )
            )
        else:
            await session.execute(text("UPDATE approvals SET status = :s"), {"s": state})
        await session.commit()

    async with httpx.AsyncClient() as http, ctx.session_factory() as session:
        tool_ctx = dataclasses.replace(
            tool_context(http, tmp_path), session_factory=ctx.session_factory
        )
        row = await session.merge(row)
        # Even if a buggy or tricked loop says "never ask", or marks the row as running.
        row.status = "running"
        with pytest.raises(gate.NotApproved):
            await gate.execute(session, registry, row, tool, "never_ask", tool_ctx)
    assert await _log(ctx) == []


async def test_an_approved_row_is_good_for_one_execution(ctx: Ctx, tmp_path: Path) -> None:
    me, run_id, _ = await _email_run(ctx)
    (pending,) = await _pending(ctx, me)
    await ctx.client.post(f"{API}/approvals/{pending['id']}/approve", headers=me)
    row = await _risky_row(ctx, run_id)
    registry = default_registry()
    tool = registry.get("email_send")
    assert tool is not None

    async with httpx.AsyncClient() as http, ctx.session_factory() as session:
        tool_ctx = dataclasses.replace(
            tool_context(http, tmp_path),
            session_factory=ctx.session_factory,
            user_id=row.user_id,
            run_id=row.run_id,
        )
        row = await session.merge(row)
        result, used = await gate.execute(session, registry, row, tool, "ask_risky", tool_ctx)
        assert result.ok and used == EMAIL
        with pytest.raises(gate.NotApproved):
            await gate.execute(session, registry, row, tool, "ask_risky", tool_ctx)
    assert len(await _log(ctx)) == 1


async def test_the_model_cannot_approve_its_own_action(ctx: Ctx) -> None:
    """No tool reaches the approvals table: asking for one is just an unknown tool."""
    me, bot, _ = await _setup(ctx)
    sent = await send(ctx, me, bot["direct_chat_id"], "Email Sam")
    llm = FakeLLM(
        [
            Turn([], [_use("email_send", **EMAIL)]),
            Turn(["done"]),
        ]
    )
    assert await run_worker(ctx, sent["run_id"], llm) == "waiting_approval"
    names = {tool["name"] for tool in llm.calls[0]["tools"]}
    assert not any("approv" in name for name in names)
    # Running the worker again without an answer does not move it.
    assert await run_worker(ctx, sent["run_id"], llm) == "skipped"
    assert await _log(ctx) == []


# --- Stop while waiting -----------------------------------------------------------------


async def test_stop_while_waiting_cancels_the_run_and_expires_the_approval(ctx: Ctx) -> None:
    me, run_id, llm = await _email_run(ctx)
    (approval,) = await _pending(ctx, me)

    resp = await ctx.client.post(f"{API}/runs/{run_id}/cancel", headers=me)
    assert resp.status_code == 202 and resp.json()["status"] == "cancelled"
    assert await _pending(ctx, me) == []
    calls = await _tool_calls(ctx, me, run_id)
    assert [(c["status"], c["result_summary"]) for c in calls] == [("rejected", "Stopped")]

    late = await ctx.client.post(f"{API}/approvals/{approval['id']}/approve", headers=me)
    assert late.status_code == 409
    assert await run_worker(ctx, run_id, llm) == "skipped"
    assert await _log(ctx) == []
    # The chat is free again.
    async with ctx.session_factory() as session:
        run = await session.get(Run, uuid.UUID(run_id))
        assert run is not None and run.chat_id is not None
        chat_id = run.chat_id
    again = await ctx.client.post(
        f"{API}/chats/{chat_id}/messages", headers=me, json={"content": "never mind"}
    )
    assert again.status_code == 202


async def test_two_risky_calls_in_one_step_are_asked_one_at_a_time(ctx: Ctx) -> None:
    me, bot, _ = await _setup(ctx)
    sent = await send(ctx, me, bot["direct_chat_id"], "email and post")
    llm = FakeLLM(
        [
            Turn([], [_use("email_send", **EMAIL), _use("social_post", text="We shipped!")]),
            Turn(["done"]),
        ]
    )
    assert await run_worker(ctx, sent["run_id"], llm) == "waiting_approval"
    (first,) = await _pending(ctx, me)
    assert first["tool"] == "email_send"
    await ctx.client.post(f"{API}/approvals/{first['id']}/approve", headers=me)

    assert await run_worker(ctx, sent["run_id"], llm) == "waiting_approval"
    assert await _log(ctx) == [{"tool": "email_send", **EMAIL}]
    (second,) = await _pending(ctx, me)
    assert second["tool"] == "social_post"
    assert second["preview"] == {"kind": "post", "fields": {"text": "We shipped!"}, "context": {}}
    await ctx.client.post(f"{API}/approvals/{second['id']}/reject", headers=me)

    assert await run_worker(ctx, sent["run_id"], llm) == "completed"
    assert await _log(ctx) == [{"tool": "email_send", **EMAIL}]  # the email was not sent twice
    assert len(llm.calls) == 2
