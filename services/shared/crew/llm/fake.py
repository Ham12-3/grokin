"""A scripted LLM for tests and for running the app without an API key (LLM_PROVIDER=fake)."""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from crew.llm.base import LLMError, LLMResult, MessageDict, OnDelta, ToolDefinition, ToolUse

DEFAULT_REPLY = (
    "This is a **test reply** from the fake model, so you can try Crew without an API key.\n\n"
    "- It streams word by word\n- It supports `markdown`\n"
    "- Send a message with a link and it will read the page and save notes\n\nYou said: "
)
URL_PATTERN = re.compile(r"https?://[^\s<>\"')]+")


@dataclass
class Turn:
    """One scripted assistant turn: some text, then optional tool calls."""

    chunks: list[str] = field(default_factory=list)
    tool_uses: list[ToolUse] = field(default_factory=list)
    error: LLMError | None = None
    fail_after: int | None = None  # raise after this many chunks


def _last_text(messages: list[MessageDict]) -> str:
    for message in reversed(messages):
        if message["role"] == "user" and isinstance(message["content"], str):
            return str(message["content"])
    return ""


def _demo_turn(messages: list[MessageDict], call_number: int) -> Turn:
    """Dev behaviour: echo, or read a linked page and save notes (three turns)."""
    last = messages[-1] if messages else {"role": "user", "content": ""}
    request = _last_text(messages)
    if isinstance(last["content"], str):
        url = URL_PATTERN.search(request)
        if url is None:
            return Turn([word + " " for word in (DEFAULT_REPLY + request).split(" ")])
        return Turn(
            ["Let ", "me ", "read ", "that ", "page."],
            [ToolUse(f"fake_{call_number}", "web_fetch", {"url": url.group(0)})],
        )
    previous: dict[str, Any] = next(
        (block for block in messages[-2]["content"] if block.get("type") == "tool_use"), {}
    )
    result = str(last["content"][0].get("content", ""))
    if previous.get("name") == "web_fetch":
        notes = f"# Notes\n\nSource: {previous['input']['url']}\n\n{result[:1500]}\n"
        return Turn(
            ["Saving ", "notes."],
            [ToolUse(f"fake_{call_number}", "files_write", {"path": "notes.md", "content": notes})],
        )
    return Turn(["Done. ", "I ", "saved ", "what ", "I ", "found ", "to ", "`notes.md`."])


class FakeLLM:
    """Plays `script` turn by turn and records every call it receives.

    `FakeLLM(["a", "b"])` is one text turn. With no script it runs the dev demo above.
    """

    def __init__(
        self,
        script: list[Turn] | list[str] | None = None,
        *,
        delay_seconds: float = 0.0,
        error: LLMError | None = None,
        fail_after: int | None = None,
    ) -> None:
        self.script: list[Turn] | None
        if script is None:
            self.script = [Turn(error=error)] if error is not None else None
        elif script and isinstance(script[0], str):
            chunks = [str(chunk) for chunk in script]
            self.script = [Turn(chunks, error=error, fail_after=fail_after)]
        else:
            self.script = [turn for turn in script if isinstance(turn, Turn)]
        self.delay_seconds = delay_seconds
        self.calls: list[dict[str, Any]] = []
        self.chunks_sent = 0

    async def stream(
        self,
        *,
        system: str,
        messages: list[MessageDict],
        tools: list[ToolDefinition],
        on_delta: OnDelta,
    ) -> LLMResult:
        call_number = len(self.calls)
        self.calls.append({"system": system, "messages": list(messages), "tools": tools})
        if self.script is None:
            turn = _demo_turn(messages, call_number)
        elif call_number < len(self.script):
            turn = self.script[call_number]
        else:
            turn = Turn(["(the script ran out)"])

        if turn.error is not None and turn.fail_after is None:
            raise turn.error
        sent: list[str] = []
        for index, chunk in enumerate(turn.chunks):
            if turn.fail_after is not None and index >= turn.fail_after:
                raise turn.error or LLMError("llm_failed", "Claude returned an error. Try again.")
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            await on_delta(chunk)
            sent.append(chunk)
            self.chunks_sent += 1
        text = "".join(sent)
        content: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
        content += [
            {"type": "tool_use", "id": use.id, "name": use.name, "input": use.input}
            for use in turn.tool_uses
        ]
        return LLMResult(
            text=text,
            input_tokens=sum(len(str(message["content"])) for message in messages) // 4
            + len(system) // 4,
            output_tokens=max(1, len(text) // 4),
            stop_reason="tool_use" if turn.tool_uses else "end_turn",
            tool_uses=list(turn.tool_uses),
            content=content,
        )
