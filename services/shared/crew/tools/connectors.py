"""App tools: Gmail, Google Calendar, Slack, Notion and the user's custom MCP servers.

A Bot only gets the tools of apps the user ticked for it (the Apps tab). They are built
per run by `registry_for_bot`. Everything an app returns is untrusted data. Sending,
creating, posting and updating are always risky; MCP tools are risky unless the user marked
them safe.
"""

import json
import re
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from crew.connectors import mcp_client, service
from crew.connectors.backend import ConnectorError
from crew.models import Bot, Connector
from crew.tools.registry import (
    Args,
    Preview,
    Risk,
    Tool,
    ToolContext,
    ToolError,
    ToolOutput,
    ToolRegistry,
)
from crew.vault import inject


def _risky(_: Args, __: ToolContext) -> Risk:
    return "risky"


def _text(limit: int = 300) -> dict[str, Any]:
    return {"type": "string", "maxLength": limit}


def _schema(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


# name -> (app kind, description, schema, risky, summary, preview)
_SPECS: list[dict[str, Any]] = [
    {
        "name": "email_search",
        "kind": "gmail",
        "description": "Search the user's email. Returns ids, senders, subjects and snippets.",
        "schema": _schema(
            {
                "query": {**_text(), "description": 'Gmail search, for example "is:unread"'},
                "limit": {"type": "integer", "minimum": 1, "maximum": 25},
            },
            [],
        ),
        "summary": lambda args: f"Searched email: {str(args.get('query', 'recent'))[:60]}",
    },
    {
        "name": "email_read",
        "kind": "gmail",
        "description": "Read one email in full by its id.",
        "schema": _schema({"id": _text(200)}, ["id"]),
        "summary": lambda args: "Read an email",
    },
    {
        "name": "email_send",
        "kind": "gmail",
        "description": (
            "Send an email (set reply_to_id to reply in a thread). The user is asked to "
            "approve it first and may edit it."
        ),
        "schema": _schema(
            {
                "to": {"type": "string", "minLength": 3, "maxLength": 320, "pattern": r"^\S+@\S+$"},
                "subject": _text(),
                "body": _text(20_000),
                "reply_to_id": _text(200),
            },
            ["to", "subject", "body"],
        ),
        "risky": True,
        "summary": lambda args: f"Email to {str(args.get('to', '?'))[:80]}",
        "preview": lambda args, ctx: Preview(
            "email", f"Send email to {str(args.get('to', '?'))[:80]}", dict(args)
        ),
    },
    {
        "name": "calendar_list",
        "kind": "gcal",
        "description": "List calendar events between two times (ISO 8601).",
        "schema": _schema({"start": _text(40), "end": _text(40)}, []),
        "summary": lambda args: "Looked at the calendar",
    },
    {
        "name": "calendar_create",
        "kind": "gcal",
        "description": "Create a calendar event. The user is asked to approve it first.",
        "schema": _schema(
            {
                "title": _text(),
                "start": _text(40),
                "end": _text(40),
                "attendees": {"type": "array", "items": _text(320), "maxItems": 50},
                "description": _text(5000),
            },
            ["title", "start", "end"],
        ),
        "risky": True,
        "summary": lambda args: f"Calendar event: {str(args.get('title', ''))[:80]}",
        "preview": lambda args, ctx: Preview(
            "generic", f"Create the event “{str(args.get('title', ''))[:80]}”", dict(args)
        ),
    },
    {
        "name": "slack_read",
        "kind": "slack",
        "description": "Read recent messages in a Slack channel.",
        "schema": _schema(
            {"channel": _text(120), "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
            ["channel"],
        ),
        "summary": lambda args: f"Read Slack {str(args.get('channel', ''))[:60]}",
    },
    {
        "name": "slack_post",
        "kind": "slack",
        "description": "Post a message in a Slack channel. The user is asked to approve it first.",
        "schema": _schema(
            {"channel": _text(120), "text": {"type": "string", "minLength": 1, "maxLength": 5000}},
            ["channel", "text"],
        ),
        "risky": True,
        "summary": lambda args: f"Slack message to {str(args.get('channel', ''))[:60]}",
        "preview": lambda args, ctx: Preview(
            "post", f"Post in Slack {str(args.get('channel', ''))[:60]}", dict(args)
        ),
    },
    {
        "name": "notion_search",
        "kind": "notion",
        "description": "Search the user's Notion pages by text.",
        "schema": _schema({"query": _text()}, ["query"]),
        "summary": lambda args: f"Searched Notion: {str(args.get('query', ''))[:60]}",
    },
    {
        "name": "notion_update",
        "kind": "notion",
        "description": "Add text to a Notion page. The user is asked to approve it first.",
        "schema": _schema(
            {"page_id": _text(200), "content": _text(20_000)}, ["page_id", "content"]
        ),
        "risky": True,
        "summary": lambda args: "Notion page update",
        "preview": lambda args, ctx: Preview("generic", "Update a Notion page", dict(args)),
    },
]

# The app actions that exist, by tool name: what a backend must implement.
ACTIONS: dict[str, str] = {spec["name"]: spec["kind"] for spec in _SPECS}
APP_TOOLS = frozenset(ACTIONS)


def _app_tool(spec: dict[str, Any], connector: Connector) -> Tool:
    connection_id = str(connector.config.get("connection_id", ""))
    action = str(spec["name"])

    async def handler(args: Args, ctx: ToolContext) -> ToolOutput:
        if ctx.connectors is None:
            raise ToolError(f"{connector.name} is not available on this server.")
        try:
            data = await ctx.connectors.execute(ctx.user_id, connection_id, action, args)
        except ConnectorError as error:
            raise ToolError(str(error)) from error
        risky = bool(spec.get("risky"))
        done = {"email_send": f"Sent an email to {args.get('to')}"}.get(action, "Done")
        told = {"email_send": f"The email to {args.get('to')} was sent."}.get(action, "Done.")
        if risky:
            return ToolOutput(told, done)
        return ToolOutput(
            json.dumps(data, indent=1, default=str),
            spec["summary"](args),
            source=connector.kind,
        )

    return Tool(
        name=action,
        description=str(spec["description"]),
        input_schema=spec["schema"],
        handler=handler,
        summary=spec["summary"],
        read_only=not spec.get("risky"),
        risk=_risky if spec.get("risky") else (lambda args, ctx: "safe"),
        preview=spec.get("preview"),
        timeout_seconds=60.0,
    )


def mcp_tool_name(connector: Connector, tool: str) -> str:
    """A name the LLM accepts (letters, digits, underscores; at most 64 characters)."""
    slug = re.sub(r"[^a-z0-9]+", "_", connector.name.lower()).strip("_")[:20] or "mcp"
    clean = re.sub(r"[^A-Za-z0-9_]+", "_", tool)[:36]
    return f"mcp_{slug}_{clean}"[:64]


def _mcp_tool(connector: Connector, spec: dict[str, Any]) -> Tool:
    remote = str(spec["name"])
    name = mcp_tool_name(connector, remote)
    safe = remote in set(connector.config.get("safe_tools", []))
    url = str(connector.config.get("url", ""))

    async def handler(args: Args, ctx: ToolContext) -> ToolOutput:
        if ctx.session_factory is None:
            raise ToolError("This tool is not available here.")
        try:
            async with ctx.session_factory() as session:
                headers = await service.mcp_headers(session, ctx.vault, connector)
            opener = ctx.mcp_opener or mcp_client.open_http
            text = await mcp_client.call_tool(url, headers, remote, args, opener)
        except ConnectorError as error:
            raise ToolError(str(error)) from error
        # The server never gets to echo our own headers back to the model.
        text = inject.redact(text, list(headers.values()))
        return ToolOutput(
            text, f"Used {connector.name}: {remote}"[:200], source=f"mcp:{connector.name}"
        )

    return Tool(
        name=name,
        description=f"[{connector.name}] {spec.get('description', '')}"[:1000],
        input_schema=spec.get("input_schema") or {"type": "object"},
        handler=handler,
        summary=lambda args: f"{connector.name}: {remote}"[:200],
        read_only=safe,
        # Unknown code on someone else's server: it asks unless the user marked it safe.
        risk=(lambda args, ctx: "safe") if safe else _risky,
        preview=lambda args, ctx: Preview(
            "generic", f"Use {connector.name}: {remote}"[:200], dict(args)
        ),
        timeout_seconds=90.0,
    )


async def registry_for_bot(session: AsyncSession, base: ToolRegistry, bot: Bot) -> ToolRegistry:
    """The built-in tools plus the tools of the apps this Bot is allowed to use."""
    registry = ToolRegistry(dict(base.tools))
    for connector in await service.for_bot(session, bot):
        if connector.kind == "mcp":
            for spec in connector.config.get("tools", []):
                tool = _mcp_tool(connector, spec)
                if tool.name not in registry.tools:
                    registry.register(tool)
            continue
        for spec in _SPECS:
            if spec["kind"] == connector.kind and spec["name"] not in registry.tools:
                registry.register(_app_tool(spec, connector))
    return registry
