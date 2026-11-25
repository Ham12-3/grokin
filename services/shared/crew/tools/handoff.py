"""handoff: the Primary Bot passes a task to the Bot whose job it is.

The task is posted in that Bot's own chat and a run starts there. Only the Primary Bot is
offered this tool, and the handler checks it again.
"""

from sqlalchemy import select

from crew.chats import service as chats
from crew.errors import AppError
from crew.models import Bot, Chat, ChatMember
from crew.skills.service import post_card
from crew.tools.registry import Args, Tool, ToolContext, ToolError, ToolOutput

NAME = "handoff"


def bot_ref(bot: Bot) -> str:
    """The short id the Primary Bot sees next to each Bot's name."""
    return bot.id.hex[-8:]


async def _handoff(args: Args, ctx: ToolContext) -> ToolOutput:
    if (
        ctx.session_factory is None
        or ctx.redis is None
        or ctx.queue is None
        or ctx.bot_id is None
        or ctx.chat_id is None
    ):
        raise ToolError("Handoff is not available here.")
    wanted = str(args["bot_id"]).strip().strip("[]").lower()
    async with ctx.session_factory() as session:
        bots = (await session.scalars(select(Bot).where(Bot.user_id == ctx.user_id))).all()
        me = next((bot for bot in bots if bot.id == ctx.bot_id), None)
        if me is None or not me.is_primary:
            raise ToolError("Only the Primary Bot can hand tasks to other Bots.")
        others = [bot for bot in bots if bot.id != ctx.bot_id]
        target = next(
            (
                bot
                for bot in others
                if bot_ref(bot) == wanted or bot.id.hex == wanted.replace("-", "")
            ),
            None,
        ) or next((bot for bot in others if bot.name.lower() == wanted), None)
        if target is None:
            raise ToolError("There is no other Bot with that id. Use an id from your Bot list.")
        chat_id = await session.scalar(
            select(Chat.id)
            .join(ChatMember, ChatMember.chat_id == Chat.id)
            .where(
                Chat.user_id == ctx.user_id, Chat.kind == "direct", ChatMember.bot_id == target.id
            )
        )
        if chat_id is None:
            raise ToolError(f"{target.name} has no chat to post in.")
        try:
            await chats.send_message(
                session,
                ctx.redis,
                ctx.queue,
                ctx.settings,
                ctx.user_id,
                chat_id,
                content=args["task"].strip(),
                card={
                    "type": "handoff_from",
                    "bot_id": str(me.id),
                    "bot_name": me.name,
                    "chat_id": str(ctx.chat_id),
                },
            )
        except AppError as error:
            if error.code == "bot_busy":
                raise ToolError(
                    f"{target.name} is busy with another task. Tell the user to try again "
                    "when it has finished."
                ) from error
            raise ToolError(error.message) from error
        await post_card(
            session,
            ctx.redis,
            ctx.chat_id,
            me.id,
            f"Passed to {target.name}",
            {
                "type": "handoff",
                "bot_id": str(target.id),
                "bot_name": target.name,
                "chat_id": str(chat_id),
            },
        )
    return ToolOutput(
        f"Passed to {target.name}. It is working on it in its own chat. Tell the user you "
        "passed it on; do not do the task yourself.",
        f"Passed to {target.name}",
    )


def make_handoff_tool() -> Tool:
    return Tool(
        name=NAME,
        description=(
            "Pass a task to another Bot when it clearly fits that Bot's job better than "
            "yours. Give the Bot's id from your Bot list and the full task in plain words, "
            "with everything that Bot needs to know."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "bot_id": {"type": "string", "minLength": 2, "maxLength": 80},
                "task": {"type": "string", "minLength": 3, "maxLength": 8000},
            },
            "required": ["bot_id", "task"],
            "additionalProperties": False,
        },
        handler=_handoff,
        summary=lambda args: "Passed the task to another Bot",
        read_only=False,
    )
