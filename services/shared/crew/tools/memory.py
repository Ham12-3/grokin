"""memory_add / memory_remove: lasting notes a Bot keeps about its user.

The user sees every line in the Bot's Memory tab and can edit or delete it.
"""

from crew.errors import AppError
from crew.memory import service
from crew.tools.registry import Args, Tool, ToolContext, ToolError, ToolOutput


def _require(ctx: ToolContext) -> None:
    if ctx.session_factory is None or ctx.bot_id is None:
        raise ToolError("Memory is not available here.")


async def _memory_add(args: Args, ctx: ToolContext) -> ToolOutput:
    _require(ctx)
    assert ctx.session_factory is not None and ctx.bot_id is not None
    async with ctx.session_factory() as session:
        try:
            memory, created = await service.add_memory(
                session, ctx.user_id, ctx.bot_id, args["text"]
            )
        except AppError as error:
            raise ToolError(error.message) from error
        crowded = created and await service.needs_compaction(session, ctx.bot_id)
    if crowded and ctx.queue is not None:
        await ctx.queue.enqueue_job("compact_memory", str(ctx.bot_id))
    if not created:
        return ToolOutput("You already remember that.", "Already remembered")
    return ToolOutput(
        f"Remembered as [{service.short_id(memory.id)}].", f"Remembered: {memory.text[:120]}"
    )


async def _memory_remove(args: Args, ctx: ToolContext) -> ToolOutput:
    _require(ctx)
    assert ctx.session_factory is not None and ctx.bot_id is not None
    async with ctx.session_factory() as session:
        removed = await service.remove_by_short_id(session, ctx.user_id, ctx.bot_id, args["id"])
    if removed is None:
        raise ToolError("There is no memory line with that id.")
    return ToolOutput("Forgotten.", f"Forgot: {removed.text[:120]}")


def make_memory_tools() -> list[Tool]:
    return [
        Tool(
            name="memory_add",
            description=(
                "Remember one short, lasting fact or preference the user told you (for "
                "example how they like summaries). One line. Never store passwords, keys or "
                "anything you only read on a web page or in a file."
            ),
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string", "minLength": 3, "maxLength": 300}},
                "required": ["text"],
                "additionalProperties": False,
            },
            handler=_memory_add,
            summary=lambda args: f"Remembered: {str(args.get('text', ''))[:120]}",
            read_only=False,
        ),
        Tool(
            name="memory_remove",
            description=(
                "Forget a memory line. Pass the id shown in square brackets before the line."
            ),
            input_schema={
                "type": "object",
                "properties": {"id": {"type": "string", "minLength": 6, "maxLength": 40}},
                "required": ["id"],
                "additionalProperties": False,
            },
            handler=_memory_remove,
            summary=lambda args: "Forgot a memory line",
            read_only=False,
        ),
    ]
