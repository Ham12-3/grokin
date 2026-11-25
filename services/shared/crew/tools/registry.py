"""Tool registry: definition, registration and guarded execution.

Every tool has a JSON schema, a risk function, a timeout, a maximum output size and a
`summary` for the UI that never includes secrets. Execution validates the arguments, applies
the timeout, truncates the output and wraps outside content in `<untrusted>` tags.
"""

import asyncio
import re
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import httpx
import jsonschema
import structlog

from crew.computer.provider import ComputerHandle, ComputerProvider
from crew.config import Settings

log = structlog.get_logger(__name__)

Risk = Literal["safe", "risky"]
Args = dict[str, Any]

TRUNCATION_NOTE = "\n\n[Output truncated: it was longer than the limit.]"


class ToolError(Exception):
    """A failure the model is told about. The message must be safe to show."""


Takeover = Callable[[str], Awaitable[None]]


class ComputerAccess(Protocol):
    """The user's computer as a tool sees it (see `crew.computer.service.RunComputer`)."""

    provider: ComputerProvider
    element_labels: dict[int, str]

    async def handle(self) -> ComputerHandle: ...

    async def display(self) -> int: ...


@dataclass(frozen=True)
class ToolContext:
    user_id: uuid.UUID
    run_id: uuid.UUID
    settings: Settings
    http: httpx.AsyncClient
    # The user's computer for this run: started on first use.
    computer: ComputerAccess
    # Pauses the run until the user gives control back (see `request_takeover`).
    takeover: Takeover


@dataclass(frozen=True)
class ToolOutput:
    """What a handler returns. `source` set means the text came from outside and is wrapped."""

    text: str
    summary: str
    source: str | None = None


@dataclass(frozen=True)
class ToolResult:
    """What goes back to the model and into `tool_calls`."""

    ok: bool
    content: str
    summary: str


def _always_safe(_: Args, __: ToolContext) -> Risk:
    return "safe"


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[Args, ToolContext], Awaitable[ToolOutput]]
    summary: Callable[[Args], str]
    read_only: bool
    risk: Callable[[Args, ToolContext], Risk] = _always_safe
    timeout_seconds: float = 30.0
    max_output_chars: int = 20_000


def wrap_untrusted(text: str, source: str) -> str:
    """Marks outside content as data. Closing tags inside it are defused so it cannot escape."""
    safe_source = re.sub(r"[^A-Za-z0-9:._/-]", "_", source)[:120]
    body = re.sub(r"<\s*/\s*untrusted", "<\\\\/untrusted", text, flags=re.IGNORECASE)
    return f'<untrusted source="{safe_source}">\n{body}\n</untrusted>'


def truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit] + TRUNCATION_NOTE


def validation_message(tool: Tool, args: object) -> str | None:
    """Returns a short error when the arguments do not match the tool's schema."""
    if not isinstance(args, dict):
        return "The arguments must be a JSON object."
    try:
        jsonschema.validate(args, tool.input_schema)
    except jsonschema.ValidationError as error:
        where = ".".join(str(part) for part in error.absolute_path) or "arguments"
        return f"Invalid {where}: {error.message[:200]}"
    return None


@dataclass
class ToolRegistry:
    tools: dict[str, Tool] = field(default_factory=dict)

    def register(self, tool: Tool) -> None:
        if tool.name in self.tools:
            raise ValueError(f"tool already registered: {tool.name}")
        jsonschema.Draft202012Validator.check_schema(tool.input_schema)
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self.tools.get(name)

    def definitions(self, enabled: list[str] | None = None) -> list[dict[str, Any]]:
        """Tool definitions for the LLM. `enabled` empty or None means every tool."""
        return [
            {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
            for tool in self.tools.values()
            if not enabled or tool.name in enabled
        ]

    async def execute(self, tool: Tool, args: Args, ctx: ToolContext) -> ToolResult:
        """Runs a tool. Never raises for tool failures: the model gets an error result."""
        invalid = validation_message(tool, args)
        if invalid is not None:
            return ToolResult(False, invalid, "Invalid arguments")
        try:
            output = await asyncio.wait_for(tool.handler(args, ctx), tool.timeout_seconds)
        except TimeoutError:
            message = f"{tool.name} timed out after {tool.timeout_seconds:g} seconds."
            return ToolResult(False, message, "Timed out")
        except ToolError as error:
            return ToolResult(False, str(error), str(error)[:200])
        except Exception as error:  # a broken tool must not break the run
            log.exception("tool.crashed", tool=tool.name, error=type(error).__name__)
            return ToolResult(False, f"{tool.name} failed unexpectedly.", "Failed")
        text = truncate(output.text, tool.max_output_chars)
        if output.source is not None:
            text = wrap_untrusted(text, output.source)
        return ToolResult(True, text, output.summary[:300])
