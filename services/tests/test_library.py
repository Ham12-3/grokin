"""The Library: adding files, automatic pickup, search, signed downloads and ownership."""

import time
import uuid
from pathlib import Path
from typing import Any

import pytest

from crew.library import service
from crew.library.storage import LocalStorage, StorageError, make_key
from crew.llm.base import ToolUse
from crew.llm.fake import FakeLLM, Turn
from tests.conftest import Ctx
from tests.helpers import API, create_bot, run_worker, send, sign_in

REPORT = "# Q3 report\n\nRevenue is up.\n"


def _use(name: str, **args: Any) -> ToolUse:
    return ToolUse(f"toolu_{uuid.uuid4().hex[:8]}", name, args)


async def _run(ctx: Ctx, me: dict[str, str], bot: dict[str, Any], turns: list[Turn]) -> FakeLLM:
    sent = await send(ctx, me, bot["direct_chat_id"], "write the report")
    llm = FakeLLM(turns)
    assert await run_worker(ctx, sent["run_id"], llm) == "completed"
    return llm


async def _items(ctx: Ctx, me: dict[str, str], **params: str) -> list[dict[str, Any]]:
    resp = await ctx.client.get(f"{API}/library", headers=me, params=params)
    assert resp.status_code == 200, resp.text
    items: list[dict[str, Any]] = resp.json()
    return items


async def _download(ctx: Ctx, url: str) -> Any:
    return await ctx.client.get(url.split("http://localhost:8000", 1)[1])


async def test_library_add_stores_a_copy_and_posts_a_file_card(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    llm = await _run(
        ctx,
        me,
        bot,
        [
            Turn([], [_use("files_write", path="outputs/q3.md", content=REPORT)]),
            Turn([], [_use("library_add", path="/workspace/outputs/q3.md", title="Q3 report")]),
            Turn(["Done."]),
        ],
    )
    assert "Added to the user's Library" in llm.calls[2]["messages"][-1]["content"][0]["content"]

    (item,) = await _items(ctx, me)  # once: the end-of-run pickup does not add it again
    assert item["title"] == "Q3 report" and item["category"] == "document"
    assert item["path"] == "/workspace/outputs/q3.md" and item["bot_id"] == bot["id"]
    assert item["mime"] == "text/markdown" and item["size_bytes"] == len(REPORT)

    page = (
        await ctx.client.get(f"{API}/chats/{bot['direct_chat_id']}/messages", headers=me)
    ).json()
    (card,) = [m["card"] for m in page["items"] if m["card"]]
    assert card == {
        "type": "file",
        "library_id": item["id"],
        "title": "Q3 report",
        "mime": "text/markdown",
        "size_bytes": len(REPORT),
    }

    detail = (await ctx.client.get(f"{API}/library/{item['id']}", headers=me)).json()
    got = await _download(ctx, detail["download_url"])  # no sign-in header: the link is the key
    assert got.status_code == 200 and got.text == REPORT
    assert got.headers["content-type"].startswith("text/plain")  # never rendered as a page
    assert got.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in got.headers["content-security-policy"]


async def test_files_left_in_outputs_are_picked_up_when_the_run_ends(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    await _run(
        ctx,
        me,
        bot,
        [
            Turn(
                [],
                [
                    _use("files_write", path="outputs/summary.md", content="# Summary\n"),
                    _use("files_write", path="outputs/data/rows.csv", content="a,b\n1,2\n"),
                    _use("files_write", path="outputs/screenshots/shot.png", content="not really"),
                    _use("files_write", path="notes.md", content="scratch"),
                ],
            ),
            Turn(["Saved."]),
        ],
    )
    items = await _items(ctx, me)
    # Deliverables only: not the scratch file, not the Bot's own screenshots.
    assert sorted(item["path"] for item in items) == [
        "/workspace/outputs/data/rows.csv",
        "/workspace/outputs/summary.md",
    ]
    assert {item["title"] for item in items} == {"rows.csv", "summary.md"}

    # A later run that changes one file updates that item; nothing is duplicated.
    await _run(
        ctx,
        me,
        bot,
        [
            Turn([], [_use("files_write", path="outputs/summary.md", content="# Summary v2\n")]),
            Turn(["ok"]),
        ],
    )
    items = await _items(ctx, me)
    assert len(items) == 2
    summary = next(item for item in items if item["title"] == "summary.md")
    detail = (await ctx.client.get(f"{API}/library/{summary['id']}", headers=me)).json()
    assert (await _download(ctx, detail["download_url"])).text == "# Summary v2\n"


async def test_a_run_that_never_used_the_computer_adds_nothing(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    await _run(ctx, me, bot, [Turn(["Just a chat."])])
    assert await _items(ctx, me) == []


async def test_search_and_filters(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    writer = await create_bot(ctx, me, "Writer")
    artist = await create_bot(ctx, me, "Artist")
    await _run(
        ctx,
        me,
        writer,
        [
            Turn([], [_use("files_write", path="outputs/q3_report.md", content=REPORT)]),
            Turn(["ok"]),
        ],
    )
    await _run(
        ctx,
        me,
        artist,
        [
            Turn(
                [],
                [
                    _use("files_write", path="outputs/logo.png", content="png"),
                    _use("files_write", path="outputs/100%.pdf", content="pdf"),
                ],
            ),
            Turn(["ok"]),
        ],
    )

    assert len(await _items(ctx, me)) == 3
    assert [item["title"] for item in await _items(ctx, me, q="REPORT")] == ["q3_report.md"]
    assert [item["title"] for item in await _items(ctx, me, q="100%")] == [
        "100%.pdf"
    ]  # % is not a wildcard
    assert await _items(ctx, me, q="_") == [
        item for item in await _items(ctx, me) if "_" in item["title"]
    ]
    assert {item["title"] for item in await _items(ctx, me, bot_id=artist["id"])} == {
        "logo.png",
        "100%.pdf",
    }
    assert [item["title"] for item in await _items(ctx, me, category="image")] == ["logo.png"]
    assert [item["title"] for item in await _items(ctx, me, category="pdf")] == ["100%.pdf"]
    assert len(await _items(ctx, me, type="file")) == 3 and await _items(ctx, me, type="page") == []


async def test_download_links_expire_cannot_be_forged_and_belong_to_one_item(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    await _run(
        ctx,
        me,
        bot,
        [
            Turn(
                [],
                [
                    _use("files_write", path="outputs/a.md", content="A"),
                    _use("files_write", path="outputs/b.md", content="B"),
                ],
            ),
            Turn(["ok"]),
        ],
    )
    first, second = await _items(ctx, me)
    url = (await ctx.client.get(f"{API}/library/{first['id']}", headers=me)).json()["download_url"]
    path = url.split("http://localhost:8000", 1)[1]
    assert (await ctx.client.get(path)).status_code == 200

    assert (
        await ctx.client.get(path.replace(first["id"], second["id"]))
    ).status_code == 404  # another item
    assert (
        await ctx.client.get(path[:-1] + ("0" if path[-1] != "0" else "1"))
    ).status_code == 404  # changed signature
    expires = int(path.split("expires=")[1].split("&")[0])
    assert (
        await ctx.client.get(path.replace(str(expires), str(expires + 3600)))
    ).status_code == 404  # longer life
    item_id = uuid.UUID(first["id"])
    old = int(time.time()) - 10
    stale = service._signature(ctx.settings, item_id, old)
    assert service.check_signature(ctx.settings, item_id, old, stale) is False  # really expired
    assert (
        await ctx.client.get(f"{API}/library/{first['id']}/content")
    ).status_code == 422  # no signature at all


async def test_another_user_cannot_list_open_or_delete(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    await _run(
        ctx,
        me,
        bot,
        [Turn([], [_use("files_write", path="outputs/secret.md", content="mine")]), Turn(["ok"])],
    )
    (item,) = await _items(ctx, me)
    other = await sign_in(ctx, "mallory@example.com")
    assert await _items(ctx, other) == []
    assert (await ctx.client.get(f"{API}/library/{item['id']}", headers=other)).status_code == 404
    assert (
        await ctx.client.delete(f"{API}/library/{item['id']}", headers=other)
    ).status_code == 404
    assert (await ctx.client.get(f"{API}/library")).status_code == 401

    url = (await ctx.client.get(f"{API}/library/{item['id']}", headers=me)).json()["download_url"]
    assert (await ctx.client.delete(f"{API}/library/{item['id']}", headers=me)).status_code == 204
    assert await _items(ctx, me) == []
    assert (await _download(ctx, url)).status_code == 404  # the link dies with the item


async def test_library_add_errors_are_clear(ctx: Ctx) -> None:
    me = await sign_in(ctx, "a@example.com")
    bot = await create_bot(ctx, me)
    llm = await _run(
        ctx,
        me,
        bot,
        [
            Turn(
                [],
                [
                    _use("library_add", path="outputs/nope.md"),
                    _use("library_add", path="../../etc/passwd"),
                ],
            ),
            Turn(["hm"]),
        ],
    )
    results = llm.calls[1]["messages"][-1]["content"]
    assert all(block["is_error"] for block in results)
    assert await _items(ctx, me) == []


async def test_local_storage_keeps_each_user_in_their_folder(tmp_path: Path) -> None:
    storage = LocalStorage(str(tmp_path))
    user, item = uuid.uuid4(), uuid.uuid4()
    key = make_key(user, item, "../../evil name?.md")
    assert key == f"{user}/{item}/evil_name_.md"
    await storage.put(key, b"hello", "text/markdown")
    assert await storage.get(key) == b"hello"
    for escape in ("../outside.txt", f"{user}/../../outside.txt", "/etc/passwd"):
        with pytest.raises(StorageError):
            await storage.get(escape)
    await storage.delete(key)
    with pytest.raises(StorageError):
        await storage.get(key)
