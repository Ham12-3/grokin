"""The dev-mode demo script of FakeLLM (LLM_PROVIDER=fake): it must reach the browser tools."""

from typing import Any

from crew.llm.base import MessageDict
from crew.llm.fake import FakeLLM


async def _noop(chunk: str) -> None:
    return None


async def _play(request: str) -> list[str]:
    """Runs the demo to the end, answering every tool call, and returns the tools it used."""
    llm = FakeLLM()
    messages: list[MessageDict] = [{"role": "user", "content": request}]
    used: list[str] = []
    for _ in range(8):
        result = await llm.stream(system="", messages=messages, tools=[], on_delta=_noop)
        if not result.tool_uses:
            return used
        used += [use.name for use in result.tool_uses]
        results: list[dict[str, Any]] = [
            {"type": "tool_result", "tool_use_id": use.id, "content": "ok"}
            for use in result.tool_uses
        ]
        messages += [
            {"role": "assistant", "content": result.content},
            {"role": "user", "content": results},
        ]
    raise AssertionError("the demo never finished")


async def test_browse_opens_the_page_and_takes_a_screenshot() -> None:
    assert await _play("browse https://example.com/") == ["browser_open", "browser_screenshot"]


async def test_sign_in_asks_the_user_to_take_over_then_reads_the_page() -> None:
    assert await _play("Sign in at https://example.com/login") == [
        "browser_open",
        "request_takeover",
        "browser_read",
    ]


async def test_a_plain_link_still_reads_the_page_and_saves_notes() -> None:
    assert await _play("summarise https://example.com/") == ["web_fetch", "files_write"]


async def test_no_link_is_an_echo() -> None:
    assert await _play("browse the shelves") == []
