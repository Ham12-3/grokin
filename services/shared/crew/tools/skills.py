"""skill_save: the Bot drafts a skill. Nothing is saved until the user clicks Save."""

from crew.skills import service
from crew.tools.registry import Args, Tool, ToolContext, ToolError, ToolOutput


async def _skill_save(args: Args, ctx: ToolContext) -> ToolOutput:
    if (
        ctx.session_factory is None
        or ctx.redis is None
        or ctx.bot_id is None
        or ctx.chat_id is None
    ):
        raise ToolError("Skills are not available here.")
    card = {
        "type": service.DRAFT_CARD,
        "status": "draft",
        "name": args["name"].strip(),
        "description": str(args.get("description", "")).strip(),
        "steps": args["steps"].strip(),
        "rules": str(args.get("rules", "")).strip(),
    }
    async with ctx.session_factory() as session:
        await service.post_card(session, ctx.redis, ctx.chat_id, ctx.bot_id, "", card)
    return ToolOutput(
        "A draft of the skill is now shown to the user. It is saved only if they click Save. "
        "Tell them to check the draft.",
        f"Drafted the skill {card['name'][:60]!r}",
    )


def make_skill_tool() -> Tool:
    return Tool(
        name="skill_save",
        description=(
            "Draft a reusable skill from a task you just did, when the user asks you to "
            "save it. Write the steps so you could repeat the task later from them alone. "
            "The user sees the draft and decides whether to save it."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string", "minLength": 2, "maxLength": 80},
                "description": {"type": "string", "maxLength": 300},
                "steps": {
                    "type": "string",
                    "minLength": 5,
                    "maxLength": 20_000,
                    "description": "Numbered steps in markdown",
                },
                "rules": {
                    "type": "string",
                    "maxLength": 5000,
                    "description": "Things to always or never do while running it",
                },
            },
            "required": ["name", "steps"],
            "additionalProperties": False,
        },
        handler=_skill_save,
        summary=lambda args: f"Drafted the skill {str(args.get('name', ''))[:60]!r}",
        # Nothing changes until the user clicks Save on the draft.
        read_only=True,
    )
