"""Routines: schedule maths, firing once, webhooks, needs_review and cleanup."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import select, text

from crew import events
from crew.errors import AppError
from crew.llm.base import ToolUse
from crew.llm.fake import FakeLLM, Turn
from crew.models import Message, Routine, Run
from crew.routines import schedule, service
from tests.conftest import Ctx
from tests.helpers import API, Listener, connect_app, create_bot, run_worker, sign_in

SKILL = {"name": "Morning brief", "steps": "1. Write the brief", "description": "", "rules": ""}
EMAIL = {"to": "sam@example.com", "subject": "Brief", "body": "Here it is."}


def _utc(
    year: int, month: int, day: int, hour: int = 0, minute: int = 0, second: int = 0
) -> datetime:
    return datetime(year, month, day, hour, minute, second, tzinfo=UTC)


async def _setup(
    ctx: Ctx, email: str = "a@example.com"
) -> tuple[dict[str, str], dict[str, Any], str]:
    me = await sign_in(ctx, email)
    bot = await create_bot(ctx, me)
    await connect_app(ctx, me, bot, "gmail")
    skill = (await ctx.client.post(f"{API}/bots/{bot['id']}/skills", headers=me, json=SKILL)).json()
    return me, bot, skill["id"]


async def _routine(
    ctx: Ctx,
    me: dict[str, str],
    bot: dict[str, Any],
    skill_id: str,
    trigger: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    resp = await ctx.client.post(
        f"{API}/bots/{bot['id']}/routines",
        headers=me,
        json={"skill_id": skill_id, "trigger": trigger, **extra},
    )
    assert resp.status_code == 201, resp.text
    routine: dict[str, Any] = resp.json()
    return routine


async def _make_due(ctx: Ctx, routine_id: str, when: datetime) -> None:
    async with ctx.session_factory() as session:
        await session.execute(
            text("UPDATE routines SET next_run_at = :when WHERE id = :id"),
            {"when": when, "id": uuid.UUID(routine_id)},
        )
        await session.commit()


async def _fire(ctx: Ctx, now: datetime | None = None) -> int:
    return await service.fire_due(ctx.session_factory, ctx.redis, ctx.queue, ctx.settings, now)


def _queued(ctx: Ctx) -> list[str]:
    return [str(args[0]) for name, args in ctx.queue.jobs if name == "run_agent"]


# --- Next-run maths ---------------------------------------------------------------------


def test_daily_time_follows_the_wall_clock_across_dst() -> None:
    nine = "0 9 * * *"
    # New York: clocks go forward on 2026-03-08, back on 2026-11-01.
    assert schedule.next_run(nine, "America/New_York", _utc(2026, 3, 7, 15)) == _utc(2026, 3, 8, 13)
    assert schedule.next_run(nine, "America/New_York", _utc(2026, 3, 6, 15)) == _utc(2026, 3, 7, 14)
    assert schedule.next_run(nine, "America/New_York", _utc(2026, 10, 31, 14)) == _utc(
        2026, 11, 1, 14
    )
    assert schedule.next_run(nine, "America/New_York", _utc(2026, 10, 30, 14)) == _utc(
        2026, 10, 31, 13
    )
    # A zone without daylight saving never moves.
    assert schedule.next_run(nine, "Africa/Lagos", _utc(2026, 3, 28, 9)) == _utc(2026, 3, 29, 8)


def test_a_skipped_hour_is_passed_over_and_a_repeated_hour_runs_once() -> None:
    # London, 2026-03-29: 01:30 does not exist. The next 01:30 is the day after.
    assert schedule.next_run("30 1 * * *", "Europe/London", _utc(2026, 3, 28, 12)) == _utc(
        2026, 3, 30, 0, 30
    )
    # London, 2026-10-25: 01:30 happens twice. It runs once, then next day.
    first = schedule.next_run("30 1 * * *", "Europe/London", _utc(2026, 10, 24, 12))
    assert first == _utc(2026, 10, 25, 0, 30)
    assert schedule.next_run("30 1 * * *", "Europe/London", first) == _utc(2026, 10, 26, 1, 30)


def test_weekdays_and_strictly_after() -> None:
    weekdays = "0 9 * * 1-5"
    friday_nine = _utc(2026, 11, 27, 9)
    assert schedule.next_run(weekdays, "UTC", _utc(2026, 11, 27, 8, 59)) == friday_nine
    assert schedule.next_run(weekdays, "UTC", friday_nine) == _utc(2026, 11, 30, 9)  # Monday


@pytest.mark.parametrize(
    ("cron", "zone"),
    [
        ("nonsense", "UTC"),
        ("* * * *", "UTC"),
        ("0 9 * * *", "Mars/Olympus"),
        ("61 9 * * *", "UTC"),
        ("0 0 0 9 * * *", "UTC"),
    ],
)
def test_bad_schedules_are_refused(cron: str, zone: str) -> None:
    with pytest.raises(AppError) as caught:
        schedule.next_run(cron, zone, _utc(2026, 1, 1))
    assert caught.value.code == "invalid_schedule"


# --- API --------------------------------------------------------------------------------


async def test_create_list_pause_resume_and_delete(ctx: Ctx) -> None:
    me, bot, skill_id = await _setup(ctx)
    routine = await _routine(
        ctx,
        me,
        bot,
        skill_id,
        {"type": "cron", "cron": "0 9 * * *", "timezone": "Africa/Lagos"},
        notify=True,
    )
    assert routine["skill_name"] == "Morning brief" and routine["notify"] is True
    assert routine["next_run_at"].endswith("T08:00:00Z") and routine["last_run"] is None
    assert routine["webhook_url"] is None

    paused = (await ctx.client.post(f"{API}/routines/{routine['id']}/pause", headers=me)).json()
    assert paused["paused"] is True and paused["next_run_at"] is None
    resumed = (await ctx.client.post(f"{API}/routines/{routine['id']}/resume", headers=me)).json()
    assert resumed["paused"] is False and resumed["next_run_at"] is not None

    edited = await ctx.client.patch(
        f"{API}/routines/{routine['id']}",
        headers=me,
        json={
            "trigger": {"type": "cron", "cron": "30 7 * * 1-5", "timezone": "UTC"},
            "notify": False,
        },
    )
    assert edited.json()["trigger"]["cron"] == "30 7 * * 1-5" and edited.json()["notify"] is False

    listed = (await ctx.client.get(f"{API}/bots/{bot['id']}/routines", headers=me)).json()
    assert [item["id"] for item in listed] == [routine["id"]]
    assert (
        await ctx.client.delete(f"{API}/routines/{routine['id']}", headers=me)
    ).status_code == 204
    assert (await ctx.client.get(f"{API}/bots/{bot['id']}/routines", headers=me)).json() == []


async def test_bad_schedules_too_frequent_ones_and_foreign_skills_are_refused(ctx: Ctx) -> None:
    me, bot, skill_id = await _setup(ctx)
    url = f"{API}/bots/{bot['id']}/routines"
    for cron, code in (
        ("every day", "invalid_schedule"),
        ("* * * * *", "too_often"),
        ("*/2 * * * *", "too_often"),
    ):
        resp = await ctx.client.post(
            url,
            headers=me,
            json={
                "skill_id": skill_id,
                "trigger": {"type": "cron", "cron": cron, "timezone": "UTC"},
            },
        )
        assert resp.status_code == 422 and resp.json()["error"]["code"] == code
    ok = await ctx.client.post(
        url,
        headers=me,
        json={
            "skill_id": skill_id,
            "trigger": {"type": "cron", "cron": "*/5 * * * *", "timezone": "UTC"},
        },
    )
    assert ok.status_code == 201

    other, _other_bot, other_skill = await _setup(ctx, "mallory@example.com")
    stolen = await ctx.client.post(
        url, headers=me, json={"skill_id": other_skill, "trigger": {"type": "webhook"}}
    )
    assert stolen.status_code == 404
    # Another user cannot see, change, run or delete it.
    routine_id = ok.json()["id"]
    assert (await ctx.client.get(url, headers=other)).status_code == 404
    for method, path in (
        ("patch", ""),
        ("delete", ""),
        ("post", "/pause"),
        ("post", "/test"),
        ("get", "/runs"),
    ):
        resp = await getattr(ctx.client, method)(
            f"{API}/routines/{routine_id}{path}",
            headers=other,
            **({"json": {"notify": True}} if method == "patch" else {}),
        )
        assert resp.status_code == 404, (method, path)


async def test_fifty_routines_per_bot(ctx: Ctx) -> None:
    me, bot, skill_id = await _setup(ctx)
    user_id = (await ctx.client.get(f"{API}/me", headers=me)).json()["id"]
    async with ctx.session_factory() as session:
        session.add_all(
            Routine(
                bot_id=uuid.UUID(bot["id"]),
                user_id=uuid.UUID(user_id),
                skill_id=uuid.UUID(skill_id),
                trigger={"type": "webhook"},
            )
            for _ in range(50)
        )
        await session.commit()
    resp = await ctx.client.post(
        f"{API}/bots/{bot['id']}/routines",
        headers=me,
        json={"skill_id": skill_id, "trigger": {"type": "webhook"}},
    )
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "too_many_routines"


async def test_preview_shows_the_next_runs(ctx: Ctx) -> None:
    me, _, _ = await _setup(ctx)
    resp = await ctx.client.post(
        f"{API}/routines/preview",
        headers=me,
        json={"cron": "0 9 * * *", "timezone": "Africa/Lagos"},
    )
    runs = resp.json()["next_runs"]
    assert len(runs) == 3 and all(run.endswith("T08:00:00Z") for run in runs)
    bad = await ctx.client.post(
        f"{API}/routines/preview", headers=me, json={"cron": "soon", "timezone": "UTC"}
    )
    assert bad.status_code == 422


# --- Firing -----------------------------------------------------------------------------


async def test_a_due_routine_fires_once_runs_its_skill_and_is_rescheduled(ctx: Ctx) -> None:
    me, bot, skill_id = await _setup(ctx)
    user_id = (await ctx.client.get(f"{API}/me", headers=me)).json()["id"]
    routine = await _routine(
        ctx, me, bot, skill_id, {"type": "cron", "cron": "0 9 * * *", "timezone": "UTC"}
    )
    not_yet = await _routine(
        ctx, me, bot, skill_id, {"type": "cron", "cron": "0 10 * * *", "timezone": "UTC"}
    )
    now = _utc(2026, 11, 27, 9, 0, 5)
    await _make_due(ctx, routine["id"], _utc(2026, 11, 27, 9))
    await _make_due(ctx, not_yet["id"], _utc(2026, 11, 27, 10))
    ctx.queue.jobs.clear()

    assert await _fire(ctx, now) == 1
    assert await _fire(ctx, now) == 0  # the next minute's tick does not fire it again
    (run_id,) = _queued(ctx)

    llm = FakeLLM(["Here is the brief."])
    async with Listener(ctx, events.user_channel(user_id)) as seen:
        assert await run_worker(ctx, run_id, llm) == "completed"
    assert "## Skill to run now: Morning brief" in llm.calls[0]["system"]
    assert llm.calls[0]["messages"][-1]["content"] == "/morning-brief"
    assert [(e["routine_id"], e["status"]) for e in seen.of("routine.completed")] == [
        (routine["id"], "completed")
    ]

    listed = {
        item["id"]: item
        for item in (await ctx.client.get(f"{API}/bots/{bot['id']}/routines", headers=me)).json()
    }
    assert listed[routine["id"]]["next_run_at"] == "2026-11-28T09:00:00Z"
    assert listed[routine["id"]]["last_run"]["status"] == "completed"
    assert listed[not_yet["id"]]["last_run"] is None

    (history,) = (await ctx.client.get(f"{API}/routines/{routine['id']}/runs", headers=me)).json()
    assert history["reply"] == "Here is the brief." and history["source"] == "schedule"
    # The routine's chat is its own: the user's chat and chat list are untouched.
    mine = (
        await ctx.client.get(f"{API}/chats/{bot['direct_chat_id']}/messages", headers=me)
    ).json()
    assert mine["items"] == [] and mine["active_run_id"] is None
    assert all(
        chat["kind"] == "direct"
        for chat in (await ctx.client.get(f"{API}/chats", headers=me)).json()
    )


async def test_two_workers_at_the_same_moment_fire_a_routine_once(ctx: Ctx) -> None:
    me, bot, skill_id = await _setup(ctx)
    routine = await _routine(
        ctx, me, bot, skill_id, {"type": "cron", "cron": "0 9 * * *", "timezone": "UTC"}
    )
    await _make_due(ctx, routine["id"], _utc(2026, 11, 27, 9))
    ctx.queue.jobs.clear()
    now = _utc(2026, 11, 27, 9, 0, 5)

    started = await asyncio.gather(*(_fire(ctx, now) for _ in range(5)))

    assert sum(started) == 1 and len(_queued(ctx)) == 1
    async with ctx.session_factory() as session:
        assert len((await session.scalars(select(Run))).all()) == 1


async def test_the_redis_lock_alone_stops_a_second_worker(ctx: Ctx) -> None:
    me, bot, skill_id = await _setup(ctx)
    routine = await _routine(
        ctx, me, bot, skill_id, {"type": "cron", "cron": "0 9 * * *", "timezone": "UTC"}
    )
    due = _utc(2026, 11, 27, 9)
    await _make_due(ctx, routine["id"], due)
    await ctx.redis.set(
        f"routine:{routine['id']}:fire:{int(due.timestamp())}", "1"
    )  # held elsewhere
    ctx.queue.jobs.clear()
    assert await _fire(ctx, due + timedelta(seconds=5)) == 0
    assert _queued(ctx) == []


async def test_paused_routines_and_ones_still_running_do_not_fire(ctx: Ctx) -> None:
    me, bot, skill_id = await _setup(ctx)
    routine = await _routine(
        ctx, me, bot, skill_id, {"type": "cron", "cron": "*/5 * * * *", "timezone": "UTC"}
    )
    ctx.queue.jobs.clear()
    await _make_due(ctx, routine["id"], _utc(2026, 11, 27, 9))
    assert await _fire(ctx, _utc(2026, 11, 27, 9, 0, 5)) == 1
    # Five minutes later the first run has not finished: this firing is skipped, not queued up.
    await _make_due(ctx, routine["id"], _utc(2026, 11, 27, 9, 5))
    assert await _fire(ctx, datetime.now(UTC)) == 0
    assert len(_queued(ctx)) == 1

    await ctx.client.post(f"{API}/routines/{routine['id']}/pause", headers=me)
    await _make_due(ctx, routine["id"], _utc(2026, 11, 27, 9, 10))
    assert await _fire(ctx, datetime.now(UTC)) == 0


async def test_test_run_works_and_reports_a_busy_routine(ctx: Ctx) -> None:
    me, bot, skill_id = await _setup(ctx)
    routine = await _routine(ctx, me, bot, skill_id, {"type": "webhook"})
    ctx.queue.jobs.clear()
    first = await ctx.client.post(f"{API}/routines/{routine['id']}/test", headers=me)
    assert first.status_code == 202 and _queued(ctx) == [first.json()["run_id"]]
    second = await ctx.client.post(f"{API}/routines/{routine['id']}/test", headers=me)
    assert second.status_code == 409 and second.json()["error"]["code"] == "still_running"
    assert await run_worker(ctx, first.json()["run_id"], FakeLLM(["done"])) == "completed"
    (history,) = (await ctx.client.get(f"{API}/routines/{routine['id']}/runs", headers=me)).json()
    assert history["source"] == "test"


async def test_hourly_limit_and_daily_budget_stop_routine_runs(ctx: Ctx) -> None:
    me, bot, skill_id = await _setup(ctx)
    user_id = (await ctx.client.get(f"{API}/me", headers=me)).json()["id"]
    routine = await _routine(ctx, me, bot, skill_id, {"type": "webhook"})
    await ctx.redis.set(
        f"routine_runs:{user_id}:{datetime.now(UTC):%Y%m%d%H}", service.MAX_RUNS_PER_HOUR
    )
    limited = await ctx.client.post(f"{API}/routines/{routine['id']}/test", headers=me)
    assert limited.status_code == 409 and limited.json()["error"]["code"] == "hourly_limit"

    await ctx.redis.flushdb()
    async with ctx.session_factory() as session:
        await session.execute(text("UPDATE users SET daily_token_budget = 0"))
        await session.commit()
    broke = await ctx.client.post(f"{API}/routines/{routine['id']}/test", headers=me)
    assert broke.status_code == 409 and broke.json()["error"]["code"] == "daily_token_limit"


# --- Webhook ----------------------------------------------------------------------------


async def test_webhook_fires_with_the_right_secret_only(ctx: Ctx) -> None:
    me, bot, skill_id = await _setup(ctx)
    routine = await _routine(ctx, me, bot, skill_id, {"type": "webhook"})
    url = routine["webhook_url"]
    assert url.startswith(f"{ctx.settings.api_base_url}/api/v1/webhooks/routines/{routine['id']}/")
    secret = url.rsplit("/", 1)[1]
    assert len(secret) >= 40
    # Only a hash is stored, and the URL is never shown again.
    async with ctx.session_factory() as session:
        stored = await session.get(Routine, uuid.UUID(routine["id"]))
        assert stored is not None and secret not in str(stored.webhook_secret_hash)
    listed = (await ctx.client.get(f"{API}/bots/{bot['id']}/routines", headers=me)).json()
    assert listed[0]["webhook_url"] is None

    base = f"{API}/webhooks/routines"
    ctx.queue.jobs.clear()
    assert (await ctx.client.post(f"{base}/{routine['id']}/wrong-secret")).status_code == 404
    assert (await ctx.client.post(f"{base}/{uuid.uuid4()}/{secret}")).status_code == 404
    cron = await _routine(
        ctx, me, bot, skill_id, {"type": "cron", "cron": "0 9 * * *", "timezone": "UTC"}
    )
    assert (await ctx.client.post(f"{base}/{cron['id']}/{secret}")).status_code == 404
    assert _queued(ctx) == []

    fired = await ctx.client.post(
        f"{base}/{routine['id']}/{secret}", json={"ignored": "body"}
    )  # no sign-in
    assert fired.status_code == 202 and _queued(ctx) == [fired.json()["run_id"]]
    assert await run_worker(ctx, fired.json()["run_id"], FakeLLM(["done"])) == "completed"
    (history,) = (await ctx.client.get(f"{API}/routines/{routine['id']}/runs", headers=me)).json()
    assert history["source"] == "webhook"


async def test_webhook_is_rate_limited_and_respects_pause(ctx: Ctx) -> None:
    me, bot, skill_id = await _setup(ctx)
    routine = await _routine(ctx, me, bot, skill_id, {"type": "webhook"})
    path = routine["webhook_url"].split("/api/v1", 1)[1]
    await ctx.client.post(f"{API}/routines/{routine['id']}/pause", headers=me)
    assert (await ctx.client.post(f"{API}{path}")).status_code == 409
    await ctx.client.post(f"{API}/routines/{routine['id']}/resume", headers=me)
    codes = [
        (await ctx.client.post(f"{API}{path}")).status_code
        for _ in range(service.WEBHOOK_PER_MINUTE + 1)
    ]
    assert codes[0] == 202 and codes[-1] == 429


# --- Risky actions in a routine ---------------------------------------------------------


async def test_a_routine_that_drafts_an_email_ends_needs_review_with_a_pending_approval(
    ctx: Ctx,
) -> None:
    me, bot, skill_id = await _setup(ctx)
    user_id = (await ctx.client.get(f"{API}/me", headers=me)).json()["id"]
    routine = await _routine(ctx, me, bot, skill_id, {"type": "webhook"}, notify=True)
    run_id = (await ctx.client.post(f"{API}/routines/{routine['id']}/test", headers=me)).json()[
        "run_id"
    ]
    llm = FakeLLM([Turn(["Drafted."], [ToolUse("toolu_1", "email_send", EMAIL)]), Turn(["Sent."])])
    async with Listener(ctx, events.user_channel(user_id)) as seen:
        assert await run_worker(ctx, run_id, llm) == "needs_review"

    assert [
        (e["routine_id"], e["status"], e["notify"], e["title"])
        for e in seen.of("routine.completed")
    ] == [(routine["id"], "needs_review", True, "Morning brief")]
    (approval,) = (await ctx.client.get(f"{API}/approvals?status=pending", headers=me)).json()
    assert approval["from_routine"] is True and approval["bot_id"] == bot["id"]
    (history,) = (await ctx.client.get(f"{API}/routines/{routine['id']}/runs", headers=me)).json()
    assert history["status"] == "needs_review"
    assert [call["status"] for call in history["tool_calls"]] == ["waiting_approval"]
    # It does not hold the routine up: the next run can start.
    again = await ctx.client.post(f"{API}/routines/{routine['id']}/test", headers=me)
    assert again.status_code == 202
    assert (
        await run_worker(ctx, again.json()["run_id"], FakeLLM(["nothing to send"])) == "completed"
    )

    # Approving later sends it, once, and finishes that run.
    ok = await ctx.client.post(f"{API}/approvals/{approval['id']}/approve", headers=me)
    assert ok.status_code == 200, ok.text
    assert await run_worker(ctx, run_id, llm) == "completed"
    async with ctx.session_factory() as session:
        sent = (await session.execute(text("SELECT payload FROM connector_log"))).scalars().all()
    assert sent == [EMAIL]


# --- Housekeeping -----------------------------------------------------------------------


async def test_cleanup_keeps_the_last_twenty_runs_of_each_routine(ctx: Ctx) -> None:
    me, bot, skill_id = await _setup(ctx)
    routine = await _routine(ctx, me, bot, skill_id, {"type": "webhook"})
    other = await _routine(ctx, me, bot, skill_id, {"type": "webhook"})
    run_ids = []
    for target, count in ((routine, 23), (other, 3)):
        for _ in range(count):
            run_id = (
                await ctx.client.post(f"{API}/routines/{target['id']}/test", headers=me)
            ).json()["run_id"]
            assert await run_worker(ctx, run_id, FakeLLM(["ok"])) == "completed"
            run_ids.append(run_id)

    assert await service.cleanup_runs(ctx.session_factory) == 3
    assert await service.cleanup_runs(ctx.session_factory) == 0
    kept = (await ctx.client.get(f"{API}/routines/{routine['id']}/runs", headers=me)).json()
    assert [item["run_id"] for item in kept] == list(reversed(run_ids[3:23]))
    assert len((await ctx.client.get(f"{API}/routines/{other['id']}/runs", headers=me)).json()) == 3
    async with ctx.session_factory() as session:
        gone = [uuid.UUID(run_id) for run_id in run_ids[:3]]
        assert (await session.scalars(select(Message).where(Message.run_id.in_(gone)))).all() == []


async def test_pause_all_and_deleting_a_routine_removes_its_history(ctx: Ctx) -> None:
    me, bot, skill_id = await _setup(ctx)
    first = await _routine(
        ctx, me, bot, skill_id, {"type": "cron", "cron": "0 9 * * *", "timezone": "UTC"}
    )
    await _routine(ctx, me, bot, skill_id, {"type": "webhook"})
    run_id = (await ctx.client.post(f"{API}/routines/{first['id']}/test", headers=me)).json()[
        "run_id"
    ]
    await run_worker(ctx, run_id, FakeLLM(["ok"]))

    assert (await ctx.client.post(f"{API}/routines/pause-all", headers=me)).json() == {"paused": 2}
    listed = (await ctx.client.get(f"{API}/bots/{bot['id']}/routines", headers=me)).json()
    assert all(item["paused"] and item["next_run_at"] is None for item in listed)

    assert (await ctx.client.delete(f"{API}/routines/{first['id']}", headers=me)).status_code == 204
    async with ctx.session_factory() as session:
        assert (await session.scalars(select(Run))).all() == []
        assert (await session.scalars(select(Message))).all() == []
        kinds = (await session.execute(text("SELECT kind FROM chats"))).scalars().all()
    assert kinds == ["direct"]
