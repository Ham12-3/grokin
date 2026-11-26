"""Talks to a user's custom MCP server: list its tools, call one.

Everything a server returns is untrusted data. Headers (API keys) come from the Vault at
call time and are never stored with the connector.
"""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Any

import jsonschema
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from crew.connectors.backend import ConnectorError

MAX_TOOLS = 60
TIMEOUT_SECONDS = 60.0
UNREACHABLE = "That MCP server could not be reached."

# Opens a client for (url, headers). Tests swap this for an in-process server.
Opener = Callable[[str, dict[str, str]], AbstractAsyncContextManager[Any]]


@asynccontextmanager
async def open_http(url: str, headers: dict[str, str]) -> AsyncIterator[Any]:
    async with (
        create_mcp_http_client(headers=headers or None) as http,
        Client(
            streamable_http_client(url, http_client=http), read_timeout_seconds=TIMEOUT_SECONDS
        ) as client,
    ):
        yield client


def _schema(raw: Any) -> dict[str, Any]:
    """The tool's input schema if it is a usable JSON schema, else "any object"."""
    if isinstance(raw, dict) and raw.get("type") == "object":
        try:
            jsonschema.Draft202012Validator.check_schema(raw)
        except jsonschema.SchemaError:
            pass
        else:
            return raw
    return {"type": "object", "additionalProperties": True}


async def list_tools(
    url: str, headers: dict[str, str], opener: Opener = open_http
) -> list[dict[str, Any]]:
    try:
        async with opener(url, headers) as client:
            result = await client.list_tools()
    except ConnectorError:
        raise
    except Exception as error:  # the SDK raises many kinds; none are safe to show raw
        raise ConnectorError(UNREACHABLE) from error
    return [
        {
            "name": str(tool.name)[:80],
            "description": str(tool.description or "")[:1000],
            "input_schema": _schema(tool.input_schema),
        }
        for tool in result.tools[:MAX_TOOLS]
    ]


async def call_tool(
    url: str,
    headers: dict[str, str],
    name: str,
    arguments: dict[str, Any],
    opener: Opener = open_http,
) -> str:
    try:
        async with opener(url, headers) as client:
            result = await client.call_tool(name, arguments)
    except Exception as error:
        raise ConnectorError(UNREACHABLE) from error
    parts = [str(block.text) for block in result.content if getattr(block, "text", None)]
    text = "\n".join(parts) or "(the tool returned nothing to read)"
    if result.is_error:
        raise ConnectorError(f"The tool reported an error: {text[:500]}")
    return text
