"""LLM interface."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol

OnDelta = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class ChatTurn:
    role: Literal["user", "assistant"]
    content: str


@dataclass(frozen=True)
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None


class LLMError(Exception):
    """A failure the user can be told about. `message` is safe to show; no secrets."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class LLM(Protocol):
    async def stream(
        self, *, system: str, messages: list[ChatTurn], on_delta: OnDelta
    ) -> LLMResult:
        """Streams one reply. Calls `on_delta` for each piece of text as it arrives."""
        ...
