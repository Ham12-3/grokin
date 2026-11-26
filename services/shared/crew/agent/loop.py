"""The agent loop: call the LLM, run the tools it asks for, repeat until it is done.

Runs inside the worker, never inside an API request. See docs/06-agent-loop.md.

- Every tool call is written to `tool_calls` before it runs and updated after.
- A call that needs approval becomes an `approvals` row and the run stops as
  `waiting_approval`. The approve / reject endpoint queues it again and the loop picks up
  where it stopped, from the database. Execution always goes through `crew.approvals.gate`.
- Tool output from outside is wrapped in <untrusted> tags by the registry.
- The loop stops at the step limit, the token budgets, on cancel, or when the LLM is done.
- Each text delta carries its character `offset`, so a reconnecting client can tell whether
  it missed anything.
"""

import asyncio
import contextlib
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
import structlog
from redis.asyncio import Redis
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from crew import events, usage
from crew.agent.prompts import build_system_prompt
from crew.approvals import gate, policy
from crew.approvals.service import approval_out
from crew.budget import BudgetStop, check_budget, step_limit_stop
from crew.chats import groups
from crew.computer.provider import ComputerProvider
from crew.computer.service import RunComputer
from crew.config import Settings
from crew.connectors import service as connector_service
from crew.llm.base import LLM, LLMError, MessageDict, ToolUse
from crew.models import (
    Approval,
    Bot,
    Chat,
    ChatMember,
    Memory,
    Message,
    Routine,
    Run,
    Skill,
    ToolCall,
)
from crew.schemas.chat import MessageOut
from crew.schemas.run import ToolCallOut
from crew.tools.connectors import registry_for_bot
from crew.tools.handoff import NAME as HANDOFF
from crew.tools.library import collect_outputs, run_paths
from crew.tools.registry import (
    Tool,
    ToolContext,
    ToolRegistry,
    ToolResult,
    preview_for,
    validation_message,
)
from crew.vault import inject

log = structlog.get_logger(__name__)

GENERIC_ERROR = "Something went wrong while replying. Try again."
OUTPUT_LIMIT = BudgetStop(
    "output_limit", "My reply was cut off because it reached the length limit."
)
REJECTED = (
    "The user rejected this action, so it was not done. Do not try it again or find another "
    "way to do it unless they ask. Tell them it was not done."
)
GROUP_APPROVAL_NOTE = "I need your approval for this. Check your Approvals."
NOT_APPROVED = "This action needs the user's approval and does not have it. It was not done."
INTERRUPTED = "This step was interrupted before it finished. It may not have happened."


def cancel_key(run_id: uuid.UUID | str) -> str:
    return f"run:{run_id}:cancel"


async def request_cancel(redis: Redis, run_id: uuid.UUID) -> None:
    """Asks the worker to stop a run. It notices within `cancel_poll_seconds`."""
    await redis.set(cancel_key(run_id), "1", ex=3600)


def pause_key(run_id: uuid.UUID | str) -> str:
    return f"run:{run_id}:pause"


async def request_pause(redis: Redis, run_id: uuid.UUID, reason: str, ttl_seconds: int) -> None:
    """Asks the worker to wait. It pauses before its next step or tool."""
    await redis.set(pause_key(run_id), reason[:300], ex=ttl_seconds)


async def request_resume(redis: Redis, run_id: uuid.UUID) -> None:
    await redis.delete(pause_key(run_id))


@dataclass
class Outcome:
    status: str  # completed | failed | cancelled | waiting_approval | needs_review
    stop: BudgetStop | None = None
    error: LLMError | None = None


@dataclass
class _State:
    """Everything the loop needs, kept in plain values so a cancel cannot corrupt it."""

    run_id: uuid.UUID
    chat_id: uuid.UUID
    user_id: uuid.UUID
    bot_id: uuid.UUID
    message_id: uuid.UUID
    approval_mode: str
    redis: Redis
    settings: Settings
    parts: list[str] = field(default_factory=list)
    length: int = 0
    need_separator: bool = False
    routine_id: uuid.UUID | None = None
    # A group chat: approvals go to the Bot's own chat, and other Bots may answer next.
    group: bool = False
    direct_chat_id: uuid.UUID | None = None
    job_queue: Any = None
    routine_notify: bool = False
    routine_title: str = ""
    # waiting_approval (someone is at the chat) or needs_review (a routine run).
    parked_status: str = "waiting_approval"
    cancel_requested: bool = False
    last_saved: float = field(default_factory=time.monotonic)

    @property
    def text(self) -> str:
        return "".join(self.parts)

    async def publish_chat(self, event_type: str, **payload: object) -> None:
        await events.publish(
            self.redis,
            events.chat_channel(self.chat_id),
            event_type,
            {"chat_id": str(self.chat_id), **payload},
        )

    async def publish_status(self, status: str, **extra: object) -> None:
        await events.publish(
            self.redis,
            events.user_channel(self.user_id),
            "run.status",
            {
                "run_id": str(self.run_id),
                "chat_id": str(self.chat_id),
                "bot_id": str(self.bot_id),
                "status": status,
                **extra,
            },
        )

    async def publish_routine(self, status: str) -> None:
        """Tells the app a routine run ended (or needs a look). The app decides to notify."""
        if self.routine_id is None:
            return
        await events.publish(
            self.redis,
            events.user_channel(self.user_id),
            "routine.completed",
            {
                "routine_id": str(self.routine_id),
                "run_id": str(self.run_id),
                "bot_id": str(self.bot_id),
                "status": status,
                # The app shows a notification only when the user asked for one.
                "notify": self.routine_notify,
                "title": self.routine_title,
            },
        )

    async def emit(self, text: str) -> None:
        """Adds text to the reply and streams it to the chat."""
        if not text:
            return
        await self.publish_chat(
            "message.delta", message_id=str(self.message_id), offset=self.length, text=text
        )
        self.parts.append(text)
        self.length += len(text)


async def _history(
    session: AsyncSession,
    settings: Settings,
    chat_id: uuid.UUID,
    skip: uuid.UUID,
    *,
    me: uuid.UUID | None = None,
    names: dict[uuid.UUID, str] | None = None,
) -> list[MessageDict]:
    """Earlier messages as alternating user/assistant text turns, starting with a user turn.

    In a group (`names` given) only this Bot's own messages are its turns: what the other
    Bots said is shown to it with their name in front, on the user's side.
    """
    rows = (
        await session.scalars(
            select(Message)
            .where(
                Message.chat_id == chat_id,
                Message.role.in_(("user", "bot")),
                Message.id != skip,
            )
            .order_by(Message.id.desc())
            .limit(settings.chat_history_messages)
        )
    ).all()
    turns: list[MessageDict] = []
    for message in reversed(rows):
        if not message.content.strip():
            continue
        role = "user" if message.role == "user" else "assistant"
        content = message.content
        if names is not None and message.role == "bot" and message.bot_id != me:
            speaker = names.get(message.bot_id, "Another Bot") if message.bot_id else "Another Bot"
            role, content = "user", f"{speaker}: {content}"
        if turns and turns[-1]["role"] == role:
            # The API wants alternating roles: merge neighbours (for example after a failed run).
            turns[-1] = {"role": role, "content": f"{turns[-1]['content']}\n\n{content}"}
        else:
            turns.append({"role": role, "content": content})
    while turns and turns[0]["role"] != "user":
        turns.pop(0)
    return turns


async def _watch_cancel(state: _State, task: asyncio.Task[Any]) -> None:
    """Interrupts the loop, wherever it is, soon after the user presses Stop."""
    while True:
        if await state.redis.exists(cancel_key(state.run_id)):
            state.cancel_requested = True
            task.cancel()
            return
        await asyncio.sleep(state.settings.cancel_poll_seconds)


async def _wait_shielded(task: asyncio.Task[None], state: _State) -> None:
    """Waits for the final write. Our own Stop interrupt may arrive late; it must not skip it."""
    while True:
        try:
            await asyncio.shield(task)
            return
        except asyncio.CancelledError:
            if not state.cancel_requested:
                raise  # the worker itself is shutting down
            if task.done():
                return


TAKEOVER_PREFIX = "takeover:"
HEARTBEAT_SECONDS = 20.0


async def _wait_while_paused(state: _State, session: AsyncSession, run: Run) -> None:
    """Holds the run while a pause is in place (Take over, or the Bot asking for help)."""
    reason = await state.redis.get(pause_key(state.run_id))
    if reason is None:
        return
    takeover = reason.startswith(TAKEOVER_PREFIX)
    run.status = "paused"
    await session.commit()
    await state.publish_status(
        "paused", takeover=takeover, reason=reason.removeprefix(TAKEOVER_PREFIX)
    )
    deadline = time.monotonic() + state.settings.takeover_timeout_seconds
    beat = time.monotonic()
    while await state.redis.exists(pause_key(state.run_id)):
        if time.monotonic() > deadline:
            await state.redis.delete(pause_key(state.run_id))
            break
        if time.monotonic() - beat > HEARTBEAT_SECONDS:
            # Shows the run is alive, so the chat does not treat it as dead.
            run.updated_at = datetime.now(UTC)
            await session.commit()
            beat = time.monotonic()
        await asyncio.sleep(state.settings.cancel_poll_seconds)
    run.status = "running"
    await session.commit()
    await state.publish_status("running")


async def _ask_for_approval(
    state: _State, session: AsyncSession, run: Run, row: ToolCall, tool: Tool, ctx: ToolContext
) -> None:
    """Creates the approval, parks the run and tells the user. Nothing has run."""
    preview = preview_for(tool, dict(row.args), ctx)
    card_chat = state.chat_id
    if state.group:
        # Never show an approval (or a Vault request) in a group: say where it is instead.
        card_chat = state.direct_chat_id or state.chat_id
        if state.length:
            await state.emit("\n\n")
        await state.emit(GROUP_APPROVAL_NOTE)
    approval = Approval(
        user_id=state.user_id,
        run_id=state.run_id,
        tool_call_id=row.id,
        bot_id=state.bot_id,
        chat_id=card_chat,
        tool=row.tool,
        title=preview.title[:300],
        preview={"kind": preview.kind, "fields": preview.fields, "context": preview.context},
    )
    session.add(approval)
    row.status = "waiting_approval"
    # A routine run does not wait for anyone: it ends `needs_review` and the approval sits
    # in the Approvals list. Approving it later continues the run.
    parked = "needs_review" if run.routine_id is not None else "waiting_approval"
    approval.from_routine = run.routine_id is not None
    state.parked_status = parked
    # In the same commit, so the approve endpoint never sees a half-parked run.
    run.status = parked
    await session.execute(
        update(Message).where(Message.id == state.message_id).values(content=state.text)
    )
    await session.commit()
    await session.refresh(row)
    await session.refresh(approval)
    await state.publish_chat(
        "tool.started",
        run_id=str(state.run_id),
        tool_call=ToolCallOut.model_validate(row).model_dump(mode="json"),
    )
    await state.publish_status(parked, message_id=str(state.message_id))
    await state.publish_routine(parked)
    await events.publish(
        state.redis,
        events.user_channel(state.user_id),
        "approval.created",
        {"approval": approval_out(approval).model_dump(mode="json")},
    )


async def _run_tool(
    state: _State,
    session: AsyncSession,
    run: Run,
    registry: ToolRegistry,
    ctx: ToolContext,
    step: int,
    use: ToolUse,
) -> dict[str, Any] | None:
    """Records, checks and runs one tool call. Returns the tool_result block for the LLM,
    or None when the call now waits for the user's approval."""
    await _wait_while_paused(state, session, run)
    tool = registry.get(use.name)
    row = await session.scalar(
        select(ToolCall).where(ToolCall.run_id == state.run_id, ToolCall.llm_tool_use_id == use.id)
    )
    resumed = row is not None
    if row is None:
        args: dict[str, Any] = use.input if isinstance(use.input, dict) else {}
        invalid = None if tool is None else validation_message(tool, use.input)
        risk = tool.risk(args, ctx) if tool is not None and invalid is None else "safe"
        if inject.names_in(args):
            risk = "risky"  # using a Vault secret always asks the user first
        summary = (
            tool.summary(args) if tool is not None else f"Tried an unknown tool: {use.name[:40]}"
        )
        # Written BEFORE anything runs.
        row = ToolCall(
            run_id=state.run_id,
            user_id=state.user_id,
            step=step,
            llm_tool_use_id=use.id,
            tool=use.name[:80],
            args=args,
            risk=risk,
            status="pending",
            summary=summary[:300],
        )
        session.add(row)
        await session.commit()
        await session.refresh(row)
    else:
        invalid = None

    async def announce(event_type: str) -> None:
        await state.publish_chat(
            event_type,
            run_id=str(state.run_id),
            tool_call=ToolCallOut.model_validate(row).model_dump(mode="json"),
        )

    if not resumed:
        await announce("tool.started")

    final_status = "error"
    if tool is None:
        result = ToolResult(False, f"There is no tool named {use.name[:40]}.", "Unknown tool")
    elif invalid is not None:
        result = ToolResult(False, invalid, "Invalid arguments")
    elif resumed and row.status != "waiting_approval":
        # Caught mid-flight by a crash: never run a tool twice on a guess.
        result = ToolResult(False, INTERRUPTED, row.result_summary or "Interrupted")
    else:
        if resumed:
            answer = await session.scalar(
                select(Approval.status).where(Approval.tool_call_id == row.id)
            )
        else:
            needs = policy.check(state.approval_mode, tool, row.risk).needs_approval  # type: ignore[arg-type]
            if needs:
                await _ask_for_approval(state, session, run, row, tool, ctx)
                return None
            answer = None
        if answer == "pending":
            return None  # still waiting
        if answer in ("rejected", "expired"):
            final_status = "rejected"
            result = ToolResult(False, REJECTED, "You rejected this")
        else:
            row.status = "running"
            row.started_at = datetime.now(UTC)
            await session.commit()
            if resumed:
                await announce("tool.started")  # the card's step moves from waiting to running
            try:
                # The gate checks the approval row itself, whatever this loop decided.
                result, used = await gate.execute(
                    session, registry, row, tool, state.approval_mode, ctx
                )
            except gate.NotApproved:
                final_status = "rejected"
                result = ToolResult(False, NOT_APPROVED, "Not approved")
            else:
                if used != row.args:
                    # The user edited it: record what actually ran.
                    row.args = used
                    row.summary = tool.summary(used)[:300]
                if result.ok:
                    final_status = "ok"

    # Updated AFTER it ran (or was refused).
    row.status = final_status
    row.result_summary = result.summary
    row.finished_at = datetime.now(UTC)
    await session.commit()
    await session.refresh(row)
    await announce("tool.finished")

    block: dict[str, Any] = {
        "type": "tool_result",
        "tool_use_id": use.id,
        "content": result.content,
    }
    if not result.ok:
        block["is_error"] = True
    return block


async def _run_tools(
    state: _State,
    session: AsyncSession,
    run: Run,
    registry: ToolRegistry,
    ctx: ToolContext,
    step: int,
    uses: list[ToolUse],
) -> list[dict[str, Any]] | None:
    """Runs one step's tool calls in order. Returns None if the run now waits for approval.

    Each result is saved as soon as it exists, so a resumed run skips what already ran.
    """
    results: list[dict[str, Any]] = list(run.pending_results)
    have = {block.get("tool_use_id") for block in results}
    for use in uses:
        if use.id in have:
            continue
        block = await _run_tool(state, session, run, registry, ctx, step, use)
        if block is None:
            return None
        results.append(block)
        run.pending_results = list(results)
        await session.commit()
    run.pending_results = []
    return results


def _unfinished_tool_uses(transcript: list[MessageDict]) -> list[ToolUse]:
    """Tool calls of the last assistant turn, if their results are not in the transcript."""
    if not transcript or transcript[-1]["role"] != "assistant":
        return []
    content = transcript[-1]["content"]
    if not isinstance(content, list):
        return []
    return [
        ToolUse(str(block["id"]), str(block["name"]), block.get("input", {}))
        for block in content
        if isinstance(block, dict) and block.get("type") == "tool_use"
    ]


async def _loop(
    state: _State,
    session: AsyncSession,
    run: Run,
    message: Message,
    bot: Bot,
    llm: LLM,
    registry: ToolRegistry,
    ctx: ToolContext,
) -> Outcome:
    settings = state.settings
    # Built-in tools plus the apps this Bot may use.
    registry = await registry_for_bot(session, registry, bot)
    apps = await connector_service.for_bot(session, bot)
    memories = (
        await session.scalars(select(Memory).where(Memory.bot_id == bot.id).order_by(Memory.id))
    ).all()
    skills = (
        await session.scalars(select(Skill).where(Skill.bot_id == bot.id).order_by(Skill.name))
    ).all()
    invoked = next((skill for skill in skills if skill.id == run.skill_id), None)
    other_bots: list[Bot] = []
    if bot.is_primary:
        other_bots = list(
            (
                await session.scalars(
                    select(Bot).where(Bot.user_id == bot.user_id, Bot.id != bot.id).order_by(Bot.id)
                )
            ).all()
        )
    system = build_system_prompt(
        bot,
        memories=memories,
        skills=skills,
        invoked=invoked,
        other_bots=other_bots,
        apps=[connector.name for connector in apps],
    )
    # Only the Primary Bot, and only when there is someone to hand to, gets `handoff`.
    tools = [
        definition
        for definition in registry.definitions(bot.enabled_tools)
        if definition["name"] != HANDOFF or other_bots
    ]
    names: dict[uuid.UUID, str] | None = None
    if state.group:
        team = await groups.members(session, state.chat_id)
        names = {member.id: member.name for member in team}
        system = f"{system}\n\n{groups.group_prompt(bot, team)}"
    transcript: list[MessageDict] = list(run.transcript)
    history = await _history(
        session, settings, state.chat_id, state.message_id, me=bot.id, names=names
    )
    messages = history + transcript
    if not messages:
        raise LLMError("empty_chat", "There is no message to reply to.")

    async def on_delta(text: str) -> None:
        if not text:
            return
        if state.need_separator:
            state.need_separator = False
            await state.emit("\n\n")
        await state.emit(text)
        # Save the partial text now and then, so a reconnecting client can catch up.
        if time.monotonic() - state.last_saved >= settings.partial_save_seconds:
            message.content = state.text
            run.updated_at = datetime.now(UTC)  # heartbeat for long replies
            await session.commit()
            state.last_saved = time.monotonic()

    async def finish_step(step: int, uses: list[ToolUse]) -> bool:
        results = await _run_tools(state, session, run, registry, ctx, step, uses)
        if results is None:
            return False
        tool_message: MessageDict = {"role": "user", "content": results}
        messages.append(tool_message)
        transcript.append(tool_message)
        run.transcript = list(transcript)
        await session.commit()
        return True

    # A run that was waiting for approval continues with the step it stopped in.
    unfinished = _unfinished_tool_uses(transcript)
    if unfinished and not await finish_step(max(run.steps - 1, 0), unfinished):
        return Outcome(state.parked_status)

    for step in range(run.steps, settings.crew_max_steps):
        await _wait_while_paused(state, session, run)
        stop = await check_budget(session, settings, run, state.user_id)
        if stop is not None:
            return Outcome("completed", stop=stop)

        result = await llm.stream(system=system, messages=messages, tools=tools, on_delta=on_delta)

        run.steps = step + 1
        run.input_tokens += result.input_tokens
        run.output_tokens += result.output_tokens
        await usage.add_usage(
            session,
            state.user_id,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )
        if result.content:
            assistant: MessageDict = {"role": "assistant", "content": result.content}
            messages.append(assistant)
            transcript.append(assistant)
            run.transcript = list(transcript)
        message.content = state.text
        await session.commit()
        state.need_separator = state.length > 0

        if result.stop_reason != "tool_use" or not result.tool_uses:
            if result.stop_reason == "max_tokens":
                return Outcome("completed", stop=OUTPUT_LIMIT)
            return Outcome("completed")

        if not await finish_step(step, result.tool_uses):
            return Outcome(state.parked_status)

    return Outcome("completed", stop=step_limit_stop(settings))


async def _finish(
    state: _State, session_factory: async_sessionmaker[AsyncSession], outcome: Outcome
) -> None:
    """Writes the final state with a fresh session, whatever happened to the loop's one."""
    if outcome.status in ("waiting_approval", "needs_review"):
        # Already parked and announced in one commit by `_ask_for_approval`. The approve
        # endpoint may have queued the run again by now, so nothing is written here.
        return
    if outcome.stop is not None:
        if state.length:
            await state.emit("\n\n")
        await state.emit(f"_{outcome.stop.message}_")

    async with session_factory() as session:
        run = await session.get(Run, state.run_id)
        if run is None:
            return
        # Tool calls caught mid-flight by a cancel or a crash must not look as if they ran.
        await session.execute(
            update(ToolCall)
            .where(ToolCall.run_id == run.id, ToolCall.status.in_(("pending", "running")))
            .values(status="error", result_summary="Stopped", finished_at=datetime.now(UTC))
        )
        tool_count = await session.scalar(
            select(func.count()).select_from(ToolCall).where(ToolCall.run_id == run.id)
        )
        run.status = outcome.status
        run.finished_at = datetime.now(UTC)
        if outcome.error is not None:
            run.error = outcome.error.message
        elif outcome.stop is not None:
            run.error = outcome.stop.code

        # Keep the bot message if it says something or has tool steps to show.
        kept = bool(state.text) or bool(tool_count)
        message = await session.get(Message, state.message_id)
        if message is not None:
            if kept:
                message.content = state.text
            else:
                await session.delete(message)
        chat = await session.get(Chat, state.chat_id)
        if chat is not None:
            chat.last_message_at = run.finished_at
        await session.commit()

    if kept:
        await state.publish_chat(
            "message.completed", message_id=str(state.message_id), length=state.length
        )
    extra: dict[str, object] = {"message_id": str(state.message_id), "message_kept": kept}
    if outcome.error is not None:
        extra["error"] = {"code": outcome.error.code, "message": outcome.error.message}
    if outcome.stop is not None:
        extra["stop"] = outcome.stop.code
    await state.publish_status(outcome.status, **extra)
    await state.publish_routine(outcome.status)
    if state.group and outcome.status == "completed":
        # The next Bot in line, or one this Bot asked by name, answers now.
        await groups.after_turn(
            session_factory, state.redis, state.job_queue, state.run_id, state.text
        )
    await state.redis.delete(cancel_key(state.run_id), pause_key(state.run_id))


async def _finalize(
    state: _State,
    session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    outcome: Outcome,
    computer: RunComputer,
) -> None:
    # Give the screen back, whatever happened.
    with contextlib.suppress(Exception):
        await computer.close()
    # The loop's session may have been interrupted mid-query: close it, never reuse it.
    with contextlib.suppress(Exception):
        await session.rollback()
    with contextlib.suppress(Exception):
        await session.close()
    await _finish(state, session_factory, outcome)


async def run_agent(
    run_id: uuid.UUID,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    redis: Redis,
    settings: Settings,
    llm: LLM | None,
    registry: ToolRegistry,
    http: httpx.AsyncClient,
    provider: ComputerProvider,
    llm_error: LLMError | None = None,
    queue: Any = None,
    vault: Any = None,
    connectors: Any = None,
    mcp_opener: Any = None,
    storage: Any = None,
) -> str:
    """Runs one queued run to its end. Returns the final status.

    `queue` (anything with `enqueue_job`) lets tools start other jobs: a handoff's run,
    tidying memory.
    """
    session = session_factory()
    try:
        # Claim the run: only one worker may move it from queued to running.
        claimed = await session.execute(
            update(Run)
            .where(Run.id == run_id, Run.status == "queued")
            .values(status="running", started_at=func.coalesce(Run.started_at, datetime.now(UTC)))
            .returning(Run.id)
        )
        run = await session.get(Run, run_id, populate_existing=True) if claimed.first() else None
        bot = await session.get(Bot, run.bot_id) if run is not None else None
        if run is None or bot is None or run.chat_id is None:
            await session.rollback()
            await session.close()
            log.warning("run.skipped", run_id=str(run_id))
            return "skipped"

        # A run resumed after an approval continues its existing reply.
        message = await session.scalar(
            select(Message).where(Message.run_id == run.id, Message.role == "bot").limit(1)
        )
        resumed = message is not None
        if message is None:
            message = Message(
                chat_id=run.chat_id, role="bot", bot_id=bot.id, content="", run_id=run.id
            )
            session.add(message)
        await session.commit()
        await session.refresh(message)
    except BaseException:
        await session.close()
        raise

    async with session_factory() as lookup:
        chat = await lookup.get(Chat, run.chat_id)
        group = chat is not None and chat.kind == "group"
        direct_chat_id = (
            await lookup.scalar(
                select(Chat.id)
                .join(ChatMember, ChatMember.chat_id == Chat.id)
                .where(
                    Chat.user_id == run.user_id, Chat.kind == "direct", ChatMember.bot_id == bot.id
                )
            )
            if group
            else None
        )
    state = _State(
        run_id=run.id,
        chat_id=run.chat_id,
        user_id=run.user_id,
        bot_id=bot.id,
        message_id=message.id,
        approval_mode=bot.approval_mode,
        redis=redis,
        settings=settings,
        group=group,
        direct_chat_id=direct_chat_id,
        job_queue=queue,
        routine_id=run.routine_id,
        parked_status="needs_review" if run.routine_id is not None else "waiting_approval",
    )
    if resumed and message.content:
        state.parts.append(message.content)
        state.length = len(message.content)
        state.need_separator = True
    if run.routine_id is not None:
        async with session_factory() as lookup:
            routine = await lookup.get(Routine, run.routine_id)
            skill = await lookup.get(Skill, run.skill_id) if run.skill_id else None
        state.routine_notify = bool(routine and routine.notify)
        state.routine_title = skill.name if skill is not None else "Routine"
    await state.publish_status("running")
    if not resumed:
        await state.publish_chat(
            "message.created", message=MessageOut.model_validate(message).model_dump(mode="json")
        )

    task = asyncio.current_task()
    assert task is not None
    watcher = asyncio.create_task(_watch_cancel(state, task))
    computer = RunComputer(session_factory, redis, provider, settings, run.user_id, run.id, bot.id)

    async def takeover(reason: str) -> None:
        await request_pause(
            redis, run.id, f"{TAKEOVER_PREFIX}{reason}", settings.takeover_timeout_seconds + 60
        )
        await _wait_while_paused(state, session, run)

    ctx = ToolContext(
        user_id=run.user_id,
        run_id=run.id,
        settings=settings,
        http=http,
        computer=computer,
        takeover=takeover,
        session_factory=session_factory,
        bot_id=bot.id,
        chat_id=run.chat_id,
        redis=redis,
        queue=queue,
        vault=vault,
        connectors=connectors,
        mcp_opener=mcp_opener,
        storage=storage,
    )
    try:
        if llm_error is not None or llm is None:
            raise llm_error or LLMError("llm_not_configured", GENERIC_ERROR)
        outcome = await _loop(state, session, run, message, bot, llm, registry, ctx)
    except asyncio.CancelledError:
        if not state.cancel_requested:
            watcher.cancel()
            await session.close()
            raise  # the worker itself is shutting down
        outcome = Outcome("cancelled")
    except LLMError as error:
        outcome = Outcome("failed", error=error)
    except Exception as error:  # the run must always end in a final status
        log.exception("run.crashed", run_id=str(run_id), error=type(error).__name__)
        outcome = Outcome("failed", error=LLMError("run_failed", GENERIC_ERROR))
    if outcome.status == "completed" and computer.started:
        # Files the Bot left in /workspace/outputs go to the Library, with a card in the chat.
        with contextlib.suppress(Exception):
            async with session_factory() as lookup:
                calls = (
                    await lookup.execute(
                        select(ToolCall.tool, ToolCall.args).where(ToolCall.run_id == run.id)
                    )
                ).all()
            await collect_outputs(ctx, run_paths([(tool, args) for tool, args in calls]))
    watcher.cancel()
    inject.forget_active()

    finalize = asyncio.create_task(_finalize(state, session, session_factory, outcome, computer))
    await _wait_shielded(finalize, state)
    log.info("run.finished", run_id=str(run_id), status=outcome.status)
    return outcome.status
