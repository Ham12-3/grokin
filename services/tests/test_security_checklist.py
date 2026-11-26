"""The release checklist in docs/09-security.md, as tests.

- Cross-user access: every router, one table. Another signed-in user gets 404 (never the
  data, never a 403 that confirms the thing exists) or an empty list.
- `web_fetch` blocks loopback, private ranges, cloud metadata and file://.
- The other items live with their feature: the approval bypass in `test_approvals.py`,
  secrets in `test_vault.py` (and `make check-secrets` for the whole suite), Tauri
  capabilities and CSP in the desktop tests.
"""

import uuid
from typing import Any

import httpx
import pytest

from crew.library import service as library
from crew.llm.base import ToolUse
from crew.llm.fake import FakeLLM, Turn
from crew.tools.net import check_url
from crew.tools.registry import ToolError
from tests.conftest import Ctx
from tests.helpers import API, connect_app, create_bot, public_resolver, run_worker, send, sign_in

EMAIL = {"to": "sam@example.com", "subject": "Hi", "body": "Hello"}
SKILL = {"name": "Brief", "steps": "1. Write it"}


async def _everything(ctx: Ctx, me: dict[str, str]) -> dict[str, str]:
    """One of each thing a user can own. Returns their ids."""
    bot = await create_bot(ctx, me, "Mine")
    other_bot = await create_bot(ctx, me, "Also mine")
    connector = await connect_app(ctx, me, bot, "gmail")
    sent = await send(ctx, me, bot["direct_chat_id"], "email Sam")
    llm = FakeLLM([Turn([], [ToolUse("toolu_1", "email_send", EMAIL)]), Turn(["ok"])])
    assert await run_worker(ctx, sent["run_id"], llm) == "waiting_approval"
    approval = (await ctx.client.get(f"{API}/approvals", headers=me)).json()[0]
    skill = (await ctx.client.post(f"{API}/bots/{bot['id']}/skills", headers=me, json=SKILL)).json()
    memory = (
        await ctx.client.post(
            f"{API}/bots/{bot['id']}/memory", headers=me, json={"text": "Likes tea"}
        )
    ).json()
    routine = (
        await ctx.client.post(
            f"{API}/bots/{bot['id']}/routines",
            headers=me,
            json={"skill_id": skill["id"], "trigger": {"type": "webhook"}},
        )
    ).json()
    vault = (
        await ctx.client.post(
            f"{API}/vault", headers=me, json={"name": "my_key", "type": "api_key", "value": "v"}
        )
    ).json()
    group = (
        await ctx.client.post(
            f"{API}/chats", headers=me, json={"bot_ids": [bot["id"], other_bot["id"]]}
        )
    ).json()
    computer = (await ctx.client.get(f"{API}/computer", headers=me)).json()
    user_id = uuid.UUID((await ctx.client.get(f"{API}/me", headers=me)).json()["id"])
    async with ctx.session_factory() as session:
        item = await library.add_file(
            session,
            ctx.app.state.storage,
            user_id=user_id,
            bot_id=None,
            run_id=None,
            path="/workspace/outputs/a.md",
            title="A",
            data=b"mine",
        )
    page = (
        await ctx.client.get(f"{API}/chats/{bot['direct_chat_id']}/messages", headers=me)
    ).json()
    return {
        "bot": bot["id"],
        "chat": bot["direct_chat_id"],
        "group": group["id"],
        "run": sent["run_id"],
        "approval": approval["id"],
        "skill": skill["id"],
        "memory": memory["id"],
        "routine": routine["id"],
        "vault": vault["id"],
        "connector": connector["id"],
        "computer": computer["id"],
        "library": str(item.id),
        "message": page["items"][0]["id"],
    }


def _requests(ids: dict[str, str]) -> list[tuple[str, str, Any]]:
    """(method, path, json body) for every route that names something by id."""
    i = ids
    return [
        # bots
        ("GET", f"/bots/{i['bot']}", None),
        ("PATCH", f"/bots/{i['bot']}", {"name": "Stolen"}),
        ("DELETE", f"/bots/{i['bot']}", None),
        ("POST", f"/bots/{i['bot']}/primary", None),
        # chats and groups
        ("POST", "/chats", {"bot_ids": [i["bot"]]}),
        ("GET", f"/chats/{i['chat']}/messages", None),
        ("POST", f"/chats/{i['chat']}/messages", {"content": "hi"}),
        ("GET", f"/chats/{i['group']}/messages", None),
        ("POST", f"/chats/{i['group']}/messages", {"content": "hi"}),
        ("DELETE", f"/chats/{i['group']}", None),
        ("POST", f"/chats/{i['chat']}/skill-drafts/{i['message']}/save", None),
        ("POST", f"/chats/{i['chat']}/skill-drafts/{i['message']}/cancel", None),
        # runs
        ("GET", f"/runs/{i['run']}", None),
        ("GET", f"/runs/{i['run']}/tool-calls", None),
        ("POST", f"/runs/{i['run']}/cancel", None),
        ("POST", f"/runs/{i['run']}/pause", None),
        ("POST", f"/runs/{i['run']}/resume", None),
        # approvals
        ("POST", f"/approvals/{i['approval']}/approve", None),
        ("POST", f"/approvals/{i['approval']}/reject", None),
        # memory and skills
        ("GET", f"/bots/{i['bot']}/memory", None),
        ("POST", f"/bots/{i['bot']}/memory", {"text": "planted"}),
        ("PATCH", f"/bots/{i['bot']}/memory/{i['memory']}", {"text": "changed"}),
        ("DELETE", f"/bots/{i['bot']}/memory/{i['memory']}", None),
        ("GET", f"/bots/{i['bot']}/skills", None),
        ("POST", f"/bots/{i['bot']}/skills", SKILL),
        ("PATCH", f"/skills/{i['skill']}", {"name": "x"}),
        ("DELETE", f"/skills/{i['skill']}", None),
        # routines
        ("GET", f"/bots/{i['bot']}/routines", None),
        (
            "POST",
            f"/bots/{i['bot']}/routines",
            {"skill_id": i["skill"], "trigger": {"type": "webhook"}},
        ),
        ("PATCH", f"/routines/{i['routine']}", {"notify": True}),
        ("DELETE", f"/routines/{i['routine']}", None),
        ("POST", f"/routines/{i['routine']}/pause", None),
        ("POST", f"/routines/{i['routine']}/resume", None),
        ("POST", f"/routines/{i['routine']}/test", None),
        ("GET", f"/routines/{i['routine']}/runs", None),
        # vault, connectors, apps
        ("DELETE", f"/vault/{i['vault']}", None),
        ("PATCH", f"/connectors/{i['connector']}", {"safe_tools": []}),
        ("DELETE", f"/connectors/{i['connector']}", None),
        ("GET", f"/bots/{i['bot']}/apps", None),
        ("PUT", f"/bots/{i['bot']}/apps", {"connector_ids": []}),
        # library
        ("GET", f"/library/{i['library']}", None),
        ("DELETE", f"/library/{i['library']}", None),
    ]


async def test_another_user_gets_nothing_from_any_router(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    ids = await _everything(ctx, me)
    mallory = await sign_in(ctx, "mallory@example.com")

    for method, path, body in _requests(ids):
        resp = await ctx.client.request(method, f"{API}{path}", headers=mallory, json=body)
        assert resp.status_code == 404, f"{method} {path} -> {resp.status_code}"
        assert resp.status_code != 403
        # And without signing in at all.
        anonymous = await ctx.client.request(method, f"{API}{path}", json=body)
        assert anonymous.status_code == 401, f"anonymous {method} {path}"

    # Lists are simply empty for her.
    for path in ("/bots", "/chats", "/approvals", "/vault", "/library"):
        assert (await ctx.client.get(f"{API}{path}", headers=mallory)).json() == [], path
    assert (await ctx.client.get(f"{API}/connectors", headers=mallory)).json()["connected"] == []
    # Her own computer is a different one.
    assert (await ctx.client.get(f"{API}/computer", headers=mallory)).json()["id"] != ids[
        "computer"
    ]

    # Nothing of the owner's changed.
    assert (await ctx.client.get(f"{API}/bots/{ids['bot']}", headers=me)).json()["name"] == "Mine"
    assert [
        m["text"]
        for m in (await ctx.client.get(f"{API}/bots/{ids['bot']}/memory", headers=me)).json()
    ] == ["Likes tea"]
    assert len((await ctx.client.get(f"{API}/approvals?status=pending", headers=me)).json()) == 1
    assert len((await ctx.client.get(f"{API}/vault", headers=me)).json()) == 1
    assert len((await ctx.client.get(f"{API}/library", headers=me)).json()) == 1
    async with ctx.session_factory() as session:
        from sqlalchemy import text

        assert (await session.execute(text("SELECT count(*) FROM connector_log"))).scalar_one() == 0


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/",
        "http://localhost/",
        "http://10.0.0.1/",
        "http://10.255.255.254:8000/admin",
        "http://172.16.0.1/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/",
        "file:///etc/passwd",
        "ftp://example.com/x",
    ],
)
async def test_web_fetch_blocks_internal_addresses_and_other_schemes(url: str) -> None:
    async def resolver(host: str, port: int) -> list[str]:
        return ["127.0.0.1"] if host == "localhost" else await public_resolver(host, port)

    with pytest.raises(ToolError):
        await check_url(url, resolver)
    # A public address still passes, so the guard is not just refusing everything.
    async with httpx.AsyncClient():
        assert (await check_url("https://example.com/", public_resolver)) is not None
