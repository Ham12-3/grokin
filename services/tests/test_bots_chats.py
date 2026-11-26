"""Bots, chats and messages against real Postgres and Redis."""

import uuid

from sqlalchemy import text

from tests.conftest import Ctx
from tests.helpers import API, create_bot, send, sign_in

# --- Bots -------------------------------------------------------------------------------


async def test_first_bot_is_primary_and_gets_a_direct_chat(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    assert bot["is_primary"] is True
    assert bot["working"] is False
    assert bot["approval_mode"] == "ask_risky"

    chats = (await ctx.client.get(f"{API}/chats", headers=me)).json()
    assert [c["id"] for c in chats] == [bot["direct_chat_id"]]
    assert chats[0]["kind"] == "direct"
    assert chats[0]["bot_ids"] == [bot["id"]]


async def test_only_one_primary_bot(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    first = await create_bot(ctx, me, "First")
    second = await create_bot(ctx, me, "Second")
    assert second["is_primary"] is False

    resp = await ctx.client.post(f"{API}/bots/{second['id']}/primary", headers=me)
    assert resp.status_code == 200 and resp.json()["is_primary"] is True

    bots = (await ctx.client.get(f"{API}/bots", headers=me)).json()
    assert {b["id"]: b["is_primary"] for b in bots} == {first["id"]: False, second["id"]: True}
    assert bots[0]["id"] == second["id"]  # the Primary Bot is listed first


async def test_update_bot_and_clear_avatar(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    resp = await ctx.client.patch(
        f"{API}/bots/{bot['id']}",
        headers=me,
        json={"name": "  Mail Bot ", "approval_mode": "always_ask", "avatar": None},
    )
    assert resp.status_code == 200, resp.text
    updated = resp.json()
    assert updated["name"] == "Mail Bot"
    assert updated["approval_mode"] == "always_ask"
    assert updated["avatar"] is None
    assert updated["job"] == bot["job"]


async def test_bot_validation(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    blank = await ctx.client.post(f"{API}/bots", headers=me, json={"name": "   ", "job": "x"})
    assert blank.status_code == 422
    bad_mode = await ctx.client.post(
        f"{API}/bots", headers=me, json={"name": "A", "job": "x", "approval_mode": "yolo"}
    )
    assert bad_mode.status_code == 422


async def test_bot_limit(ctx: Ctx) -> None:
    ctx.app.state.settings = ctx.settings.model_copy(update={"max_bots_per_user": 2})
    me = await sign_in(ctx, "a@example.com")
    await create_bot(ctx, me, "One")
    await create_bot(ctx, me, "Two")
    third = await ctx.client.post(f"{API}/bots", headers=me, json={"name": "Three", "job": "x"})
    assert third.status_code == 409
    assert third.json()["error"]["code"] == "bot_limit_reached"


async def test_deleting_the_primary_bot_promotes_another_and_removes_its_chat(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    first = await create_bot(ctx, me, "First")
    second = await create_bot(ctx, me, "Second")
    await send(ctx, me, first["direct_chat_id"], "hello")

    assert (await ctx.client.delete(f"{API}/bots/{first['id']}", headers=me)).status_code == 204

    bots = (await ctx.client.get(f"{API}/bots", headers=me)).json()
    assert [(b["id"], b["is_primary"]) for b in bots] == [(second["id"], True)]
    chats = (await ctx.client.get(f"{API}/chats", headers=me)).json()
    assert [c["id"] for c in chats] == [second["direct_chat_id"]]
    async with ctx.engine.connect() as conn:
        assert (await conn.execute(text("SELECT count(*) FROM messages"))).scalar() == 0
        assert (await conn.execute(text("SELECT count(*) FROM runs"))).scalar() == 0


async def test_routes_need_sign_in(ctx: Ctx) -> None:
    for method, path in [
        ("GET", "/bots"),
        ("POST", "/bots"),
        ("GET", "/chats"),
        ("GET", f"/chats/{uuid.uuid4()}/messages"),
        ("POST", f"/chats/{uuid.uuid4()}/messages"),
    ]:
        resp = await ctx.client.request(method, f"{API}{path}", json={})
        assert resp.status_code == 401, (method, path)


# --- Cross-user access ------------------------------------------------------------------


async def test_another_user_cannot_reach_my_bots_or_chats(ctx: Ctx) -> None:
    alice = await sign_in(ctx, "alice@example.com")
    bob = await sign_in(ctx, "bob@example.com")
    bot = await create_bot(ctx, alice)
    chat_id = bot["direct_chat_id"]
    await send(ctx, alice, chat_id, "private")

    assert (await ctx.client.get(f"{API}/bots", headers=bob)).json() == []
    assert (await ctx.client.get(f"{API}/chats", headers=bob)).json() == []

    attempts = [
        ("GET", f"/bots/{bot['id']}", None),
        ("PATCH", f"/bots/{bot['id']}", {"name": "Hacked"}),
        ("DELETE", f"/bots/{bot['id']}", None),
        ("POST", f"/bots/{bot['id']}/primary", None),
        ("GET", f"/chats/{chat_id}/messages", None),
        ("POST", f"/chats/{chat_id}/messages", {"content": "hi"}),
        ("POST", "/chats", {"bot_ids": [bot["id"]]}),
    ]
    for method, path, body in attempts:
        resp = await ctx.client.request(method, f"{API}{path}", headers=bob, json=body)
        assert resp.status_code == 404, (method, path, resp.text)

    # Nothing changed for Alice.
    mine = (await ctx.client.get(f"{API}/bots/{bot['id']}", headers=alice)).json()
    assert mine["name"] == "Inbox Bot"
    page = (await ctx.client.get(f"{API}/chats/{chat_id}/messages", headers=alice)).json()
    assert [m["content"] for m in page["items"]] == ["private"]


# --- Chats and messages -----------------------------------------------------------------


async def test_send_message_queues_a_run(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    sent = await send(ctx, me, bot["direct_chat_id"], "What is on today?")

    assert sent["message"]["role"] == "user"
    assert sent["message"]["content"] == "What is on today?"
    assert ctx.queue.jobs == [("run_agent", (sent["run_id"],))]
    async with ctx.engine.connect() as conn:
        status = (await conn.execute(text("SELECT status FROM runs"))).scalar()
    assert status == "queued"

    bots = (await ctx.client.get(f"{API}/bots", headers=me)).json()
    assert bots[0]["working"] is True
    page = (
        await ctx.client.get(f"{API}/chats/{bot['direct_chat_id']}/messages", headers=me)
    ).json()
    assert page["active_run_id"] == sent["run_id"]


async def test_cannot_send_while_the_bot_is_replying(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    await send(ctx, me, bot["direct_chat_id"], "one")
    resp = await ctx.client.post(
        f"{API}/chats/{bot['direct_chat_id']}/messages", headers=me, json={"content": "two"}
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "bot_busy"


async def test_a_dead_run_does_not_block_the_chat_forever(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    await send(ctx, me, bot["direct_chat_id"], "one")
    async with ctx.engine.begin() as conn:
        await conn.execute(text("UPDATE runs SET updated_at = now() - interval '1 hour'"))
    await send(ctx, me, bot["direct_chat_id"], "two")
    bots = (await ctx.client.get(f"{API}/bots", headers=me)).json()
    assert bots[0]["working"] is True  # because of the new run only


async def test_empty_message_is_rejected(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    resp = await ctx.client.post(
        f"{API}/chats/{bot['direct_chat_id']}/messages", headers=me, json={"content": "  \n "}
    )
    assert resp.status_code == 422


async def test_open_chat_returns_the_direct_chat(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    first = await create_bot(ctx, me, "First")
    one = await ctx.client.post(f"{API}/chats", headers=me, json={"bot_ids": [first["id"]]})
    assert one.status_code == 200 and one.json()["id"] == first["direct_chat_id"]
    # The same Bot twice is still its own chat, not a group.
    twice = await ctx.client.post(
        f"{API}/chats", headers=me, json={"bot_ids": [first["id"], first["id"]]}
    )
    assert twice.json()["id"] == first["direct_chat_id"]


async def test_message_pagination_walks_backwards(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    chat_id = bot["direct_chat_id"]
    async with ctx.session_factory() as session:
        from crew.models import Message

        for index in range(7):
            session.add(Message(chat_id=uuid.UUID(chat_id), role="user", content=f"m{index}"))
            await session.flush()
        await session.commit()

    url = f"{API}/chats/{chat_id}/messages"
    newest = (await ctx.client.get(url, headers=me, params={"limit": 3})).json()
    assert [m["content"] for m in newest["items"]] == ["m4", "m5", "m6"]
    assert newest["has_more"] is True

    older = (
        await ctx.client.get(
            url, headers=me, params={"limit": 3, "before": newest["items"][0]["id"]}
        )
    ).json()
    assert [m["content"] for m in older["items"]] == ["m1", "m2", "m3"]

    oldest = (
        await ctx.client.get(
            url, headers=me, params={"limit": 3, "before": older["items"][0]["id"]}
        )
    ).json()
    assert [m["content"] for m in oldest["items"]] == ["m0"]
    assert oldest["has_more"] is False
