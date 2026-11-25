"""The dev-mode demo script of FakeLLM (LLM_PROVIDER=fake): it must reach the browser tools."""

from typing import Any

from crew.llm.base import MessageDict
from crew.llm.fake import FakeLLM


async def _noop(chunk: str) -> None:
    return None


TOOLS = [{"name": "handoff", "description": "", "input_schema": {}}]
TEAM = "## Other Bots\nYou are the Primary Bot.\n- [0a1b2c3d] Research Bot: Researches topics\n\n## Rules"


async def _play(
    request: str, system: str = "", tools: list[dict[str, Any]] | None = None
) -> list[str]:
    """Runs the demo to the end, answering every tool call, and returns the tools it used."""
    llm = FakeLLM()
    messages: list[MessageDict] = [{"role": "user", "content": request}]
    used: list[str] = []
    for _ in range(8):
        result = await llm.stream(
            system=system, messages=messages, tools=tools or [], on_delta=_noop
        )
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


async def test_email_drafts_an_email_for_approval() -> None:
    assert await _play("Email sam@example.com to say the report is ready") == ["email_send"]


async def test_memory_skill_and_handoff_triggers() -> None:
    assert await _play("I prefer short bullet summaries") == ["memory_add"]
    assert await _play("Please save that as a skill") == ["skill_save"]
    assert await _play("Research the history of Tauri", TEAM, TOOLS) == ["handoff"]
    # Not the Primary Bot (no tool), or nothing that fits another Bot: no handoff.
    assert await _play("Research the history of Tauri", TEAM) == []
    assert await _play("What time is it", TEAM, TOOLS) == []


async def test_the_echo_shows_what_it_remembers_and_runs_an_invoked_skill() -> None:
    llm = FakeLLM()
    memory = (
        "## What you remember about this user\nFollow these.\n- [0a1b2c3d] Likes tea\n\n## Rules"
    )
    said = await llm.stream(
        system=memory, messages=[{"role": "user", "content": "hi"}], tools=[], on_delta=_noop
    )
    assert "What I remember about you:\n- Likes tea" in said.text
    skill = "## Rules\n\n## Skill to run now: Weekly Report\nFollow its steps.\n\n1. Read notes"
    ran = await llm.stream(
        system=skill,
        messages=[{"role": "user", "content": "/weekly-report"}],
        tools=[],
        on_delta=_noop,
    )
    assert "Running the skill **Weekly Report**" in ran.text and "1. Read notes" in ran.text
