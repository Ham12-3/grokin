"""The last check before a tool runs. Independent of the agent loop (defence in depth).

Every tool execution in the worker goes through `execute`. A call that needs approval runs
only if its `approvals` row says `approved`, belongs to the same user and has not been used
before. Nothing the model writes can create or change that row: only the authenticated
user's approve endpoint can.
"""

from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from crew.approvals import policy
from crew.models import Approval, ToolCall
from crew.tools.registry import Args, Tool, ToolContext, ToolRegistry, ToolResult
from crew.vault import inject


class NotApproved(Exception):
    """The call needs approval and there is no unused, approved row for it."""


async def authorize(
    session: AsyncSession, row: ToolCall, tool: Tool, approval_mode: str, ctx: ToolContext
) -> Args:
    """Returns the arguments that may run: the stored ones, or the user's edited ones."""
    args: Args = dict(row.args)
    needs_approval = (
        row.risk == "risky"
        or policy.check(approval_mode, tool, tool.risk(args, ctx)).needs_approval
        # A secret can be sent anywhere a tool can reach: the user decides each time.
        or bool(inject.names_in(args))
    )
    if not needs_approval:
        return args
    # Claimed in one statement: an approval is good for exactly one execution.
    claimed = await session.execute(
        update(Approval)
        .where(
            Approval.tool_call_id == row.id,
            Approval.user_id == row.user_id,
            Approval.status == "approved",
            Approval.executed_at.is_(None),
        )
        .values(executed_at=datetime.now(UTC))
        .returning(Approval.edited_args)
    )
    first = claimed.first()
    if first is None:
        await session.commit()
        raise NotApproved
    await session.commit()
    edited: Args | None = first[0]
    return dict(edited) if edited is not None else args


async def execute(
    session: AsyncSession,
    registry: ToolRegistry,
    row: ToolCall,
    tool: Tool,
    approval_mode: str,
    ctx: ToolContext,
) -> tuple[ToolResult, Args]:
    """Runs one recorded tool call if it is allowed to. Returns the result and the args used."""
    args = await authorize(session, row, tool, approval_mode, ctx)
    # Vault values go in here, at the last moment, and are scrubbed from whatever comes back.
    try:
        real_args, secrets = await inject.resolve(
            session, ctx.vault, row.user_id, args, tool=tool.name
        )
    except inject.MissingSecret as error:
        return ToolResult(False, str(error), "A Vault item is missing"), args
    result = await registry.execute(tool, real_args, ctx)
    if secrets:
        result = ToolResult(
            result.ok,
            inject.redact(result.content, secrets),
            inject.redact(result.summary, secrets),
        )
    return result, args
