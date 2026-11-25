"""LLM interface.

Messages and tool definitions use the Anthropic Messages API shapes (plain dicts), so a
run's transcript can be stored and replayed exactly, including blocks the app does not
interpret itself.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

OnDelta = Callable[[str], Awaitable[None]]
MessageDict = dict[str, Any]
ToolDefinition = dict[str, Any]


@dataclass(frozen=True)
class ToolUse:
    id: str
    name: str
    input: Any  # validated against the tool's schema before anything runs


@dataclass(frozen=True)
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None
    tool_uses: list[ToolUse] = field(default_factory=list)
    # The assistant turn's raw content blocks, to send back unchanged on the next call.
    content: list[dict[str, Any]] = field(default_factory=list)


class LLMError(Exception):
    """A failure the user can be told about. `message` is safe to show; no secrets."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LLM(Protocol):
    async def stream(
        self,
        *,
        system: str,
        messages: list[MessageDict],
        tools: list[ToolDefinition],
        on_delta: OnDelta,
    ) -> LLMResult:
        """Streams one assistant turn. Calls `on_delta` for each piece of text."""
        ...
