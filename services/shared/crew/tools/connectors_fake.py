"""Stand-in connector tools until real connectors arrive (phase 8).

`email_send` and `social_post` send nothing: they write a row to `connector_log`. They are
always risky, so they exercise the whole approval flow.
"""

from crew.models import ConnectorLog
from crew.tools.registry import Args, Preview, Risk, Tool, ToolContext, ToolError, ToolOutput


def _risky(_: Args, __: ToolContext) -> Risk:
    return "risky"


async def _log(ctx: ToolContext, tool: str, payload: Args) -> None:
    if ctx.session_factory is None:
        raise ToolError("This tool is not available here.")
    async with ctx.session_factory() as session:
        session.add(
            ConnectorLog(user_id=ctx.user_id, run_id=ctx.run_id, tool=tool, payload=payload)
        )
        await session.commit()


async def _email_send(args: Args, ctx: ToolContext) -> ToolOutput:
    await _log(ctx, "email_send", {key: args[key] for key in ("to", "subject", "body")})
    return ToolOutput(f"The email to {args['to']} was sent.", f"Sent an email to {args['to']}")


async def _social_post(args: Args, ctx: ToolContext) -> ToolOutput:
    await _log(ctx, "social_post", {"text": args["text"]})
    return ToolOutput("The post was published.", "Published a post")


def make_fake_connector_tools() -> list[Tool]:
    return [
        Tool(
            name="email_send",
            description=(
                "Send an email. The user is asked to approve it first and may edit it. "
                "(Test connector: the email is recorded, not delivered.)"
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "to": {
                        "type": "string",
                        "minLength": 3,
                        "maxLength": 320,
                        "pattern": "^\\S+@\\S+$",
                    },
                    "subject": {"type": "string", "maxLength": 300},
                    "body": {"type": "string", "maxLength": 20_000},
                },
                "required": ["to", "subject", "body"],
                "additionalProperties": False,
            },
            handler=_email_send,
            summary=lambda args: f"Email to {str(args.get('to', '?'))[:80]}",
            read_only=False,
            risk=_risky,
            preview=lambda args, ctx: Preview(
                "email", f"Send email to {str(args.get('to', '?'))[:80]}", dict(args)
            ),
        ),
        Tool(
            name="social_post",
            description=(
                "Publish a public post. The user is asked to approve it first and may edit "
                "it. (Test connector: the post is recorded, not published.)"
            ),
            input_schema={
                "type": "object",
                "properties": {"text": {"type": "string", "minLength": 1, "maxLength": 5000}},
                "required": ["text"],
                "additionalProperties": False,
            },
            handler=_social_post,
            summary=lambda args: "Public post",
            read_only=False,
            risk=_risky,
            preview=lambda args, ctx: Preview("post", "Publish a post", dict(args)),
        ),
    ]
