"""A scripted LLM for tests and for running the app without an API key (LLM_PROVIDER=fake)."""

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any

from crew.llm.base import LLMError, LLMResult, MessageDict, OnDelta, ToolDefinition, ToolUse

DEFAULT_REPLY = (
    "This is a **test reply** from the fake model, so you can try Crew without an API key.\n\n"
    "- It streams word by word\n- It supports `markdown`\n"
    "- Send a message with a link and it will read the page and save notes\n"
    "- Say `browse` with a link and it opens the page on its computer's screen\n"
    "- Say `sign in` with a link and it opens the page, then asks you to take over\n"
    "- With Gmail connected: `email` with an address drafts one for approval, and "
    "`unread emails` lists your inbox\n"
    "- Say `remember` or `I prefer` and it saves that to its memory\n"
    "- Say `save that as a skill` and it drafts a skill; `/` runs a saved one\n"
    "- Ask the Primary Bot for something that is another Bot's job and it passes it on\n\n"
    "You said: "
)
NO_GMAIL = "I cannot use email yet. Connect Gmail in Settings, then tick it in my Apps tab."
URL_PATTERN = re.compile(r"https?://[^\s<>\"')]+")
EMAIL_PATTERN = re.compile(r"\bemail\b.*?([\w.+-]+@[\w-]+(?:\.[\w-]+)+)", re.IGNORECASE | re.DOTALL)
MEMORY_PATTERN = re.compile(r"\b(remember|i prefer|i like|i always|i never)\b", re.IGNORECASE)
SKILL_PATTERN = re.compile(r"\bsave (that|this|it) as a skill\b", re.IGNORECASE)
TEAM_PATTERN = re.compile(r"^- \[([0-9a-f]{8})\] ([^:\n]+): (.*)$", re.MULTILINE)
MEMORY_LINE = re.compile(r"^- \[[0-9a-f]{8}\] (.+)$", re.MULTILINE)
RUN_SKILL = re.compile(r"^## Skill to run now: (.+)$", re.MULTILINE)
BROWSE_PATTERN = re.compile(r"\b(browse|sign in)\b", re.IGNORECASE)


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


def _words(text: str) -> list[str]:
    return [word + " " for word in text.split(" ")]


def _teammate(system: str, request: str) -> tuple[str, str] | None:
    """The other Bot whose name or job shares a word with the request (Primary Bot only)."""
    if "## Other Bots" not in system:
        return None
    team = system.split("## Other Bots", 1)[1].split("\n## ", 1)[0]
    asked = {word for word in re.findall(r"[a-z]{4,}", request.lower())}
    for ref, name, job in TEAM_PATTERN.findall(team):
        known = set(re.findall(r"[a-z]{4,}", f"{name} {job}".lower())) - {"bots"}
        if asked & known or any(a[:6] == k[:6] for a in asked for k in known):
            return ref, name
    return None


def _first_turn(request: str, system: str, tools: list[ToolDefinition], number: int) -> Turn | None:
    """Dev behaviour for memory, skills and handoff. None means "not one of those"."""
    names = {tool["name"] for tool in tools}
    running = RUN_SKILL.search(system)
    if running is not None:
        steps = system.split(running.group(0), 1)[1].strip()
        address = EMAIL_PATTERN.search(steps)
        if address is not None and "email_send" in names:
            # A skill that sends email: draft it, so a routine shows the needs-review path.
            draft = {"to": address.group(1), "subject": running.group(1), "body": steps[:500]}
            return Turn(
                _words(f"Running the skill **{running.group(1)}**. The email needs approval."),
                [ToolUse(f"fake_{number}", "email_send", draft)],
            )
        return Turn(_words(f"Running the skill **{running.group(1)}**.\n\n{steps}"))
    if SKILL_PATTERN.search(request):
        draft = {
            "name": "Saved task",
            "description": "A task saved from this chat",
            "steps": "1. Do what the user asked in this chat\n2. Reply with the result",
        }
        return Turn(
            ["Here ", "is ", "a ", "draft."], [ToolUse(f"fake_{number}", "skill_save", draft)]
        )
    if MEMORY_PATTERN.search(request):
        return Turn(
            ["I ", "will ", "remember ", "that."],
            [ToolUse(f"fake_{number}", "memory_add", {"text": request[:300]})],
        )
    teammate = _teammate(system, request) if "handoff" in names else None
    if teammate is not None:
        args = {"bot_id": teammate[0], "task": request}
        return Turn(
            _words(f"That is a job for {teammate[1]}."),
            [ToolUse(f"fake_{number}", "handoff", args)],
        )
    return None


def _demo_turn(
    messages: list[MessageDict],
    call_number: int,
    system: str = "",
    tools: list[ToolDefinition] | None = None,
) -> Turn:
    """Dev behaviour: echo, read a linked page and save notes, or use the browser."""
    last = messages[-1] if messages else {"role": "user", "content": ""}
    request = _last_text(messages)
    if isinstance(last["content"], str):
        offered = {tool["name"] for tool in tools or []}
        if re.search(r"\b(unread|inbox|my emails?)\b", request, re.IGNORECASE):
            if "email_search" not in offered:
                return Turn(_words(NO_GMAIL))
            return Turn(
                ["Checking ", "your ", "inbox."],
                [
                    ToolUse(
                        f"fake_{call_number}", "email_search", {"query": "is:unread", "limit": 5}
                    )
                ],
            )
        address = EMAIL_PATTERN.search(request)
        if address is not None and "email_send" not in offered:
            return Turn(_words(NO_GMAIL))
        if address is not None:
            draft = {"to": address.group(1), "subject": "A note from Crew", "body": request}
            return Turn(
                ["Here ", "is ", "the ", "email. ", "It ", "needs ", "your ", "approval."],
                [ToolUse(f"fake_{call_number}", "email_send", draft)],
            )
        special = _first_turn(request, system, tools or [], call_number)
        if special is not None:
            return special
        url = URL_PATTERN.search(request)
        if url is None:
            remembered = MEMORY_LINE.findall(
                system.split("## What you remember", 1)[1].split("\n## ", 1)[0]
                if "## What you remember" in system
                else ""
            )
            note = ""
            if remembered:
                note = "\n\nWhat I remember about you:\n" + "\n".join(
                    f"- {line}" for line in remembered
                )
            return Turn(_words(DEFAULT_REPLY + request + note))
        if BROWSE_PATTERN.search(request):
            return Turn(
                ["Opening ", "it ", "in ", "my ", "browser."],
                [ToolUse(f"fake_{call_number}", "browser_open", {"url": url.group(0)})],
            )
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
            [
                ToolUse(
                    f"fake_{call_number}",
                    "files_write",
                    {"path": "outputs/notes.md", "content": notes},
                )
            ],
        )
    if previous.get("name") == "memory_add":
        return Turn(["Noted. ", "You ", "can ", "see ", "it ", "in ", "my ", "Memory ", "tab."])
    if previous.get("name") == "skill_save":
        return Turn(_words("I drafted a skill. Click Save on the card to keep it."))
    if previous.get("name") == "handoff":
        if last["content"][0].get("is_error"):
            return Turn(_words("I could not pass it on: " + result[:200]))
        return Turn(_words("I've passed this on. Open that Bot's chat to follow it."))
    if previous.get("name") == "email_search":
        subjects = re.findall(r'"subject": "([^"]+)"', result)
        listing = "\n".join(f"- {subject}" for subject in subjects) or "- (nothing found)"
        return Turn(_words(f"Your unread emails:\n{listing}"))
    if previous.get("name") == "email_send":
        if last["content"][0].get("is_error"):
            return Turn(["Understood. ", "I ", "did ", "not ", "send ", "it."])
        return Turn(["Done. ", "The ", "email ", "was ", "sent."])
    if previous.get("name") == "browser_open":
        if "sign in" in request.lower():
            reason = "Please sign in on this page, then give control back."
            return Turn(
                ["I ", "need ", "you ", "for ", "this."],
                [ToolUse(f"fake_{call_number}", "request_takeover", {"reason": reason})],
            )
        return Turn(
            ["Taking ", "a ", "screenshot."],
            [ToolUse(f"fake_{call_number}", "browser_screenshot", {})],
        )
    if previous.get("name") == "request_takeover":
        return Turn(
            ["Thanks. ", "Reading ", "the ", "page ", "again."],
            [ToolUse(f"fake_{call_number}", "browser_read", {})],
        )
    if str(previous.get("name", "")).startswith("browser_"):
        return Turn(["Done. ", "The ", "page ", "is ", "open ", "on ", "my ", "screen."])
    return Turn(
        [
            "Done. ",
            "I ",
            "saved ",
            "what ",
            "I ",
            "found ",
            "to ",
            "`outputs/notes.md`. ",
            "It ",
            "is ",
            "in ",
            "your ",
            "Library.",
        ]
    )


PICKER_MARK = "You decide which teammate should answer"


def _pick(prompt: str) -> str:
    """Dev behaviour for the group picker: the Bot whose name or job fits the last line."""
    team = re.findall(r"^- ([^:\n]+): (.*)$", prompt, re.MULTILINE)
    last = prompt.split("<conversation>")[-1].strip().splitlines()[-2:]
    asked = set(re.findall(r"[a-z]{4,}", " ".join(last).lower()))
    if asked & {"thanks", "thank", "okay"}:
        return "none"
    for name, job in team:
        known = set(re.findall(r"[a-z]{4,}", f"{name} {job}".lower())) - {"bots"}
        if any(a[:6] == k[:6] for a in asked for k in known):
            return str(name)
    return str(team[0][0]) if team else "none"


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
        if self.script is None and system.startswith(PICKER_MARK):
            turn = Turn([_pick(str(messages[-1]["content"]))])
        elif self.script is None:
            turn = _demo_turn(messages, call_number, system, tools)
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
