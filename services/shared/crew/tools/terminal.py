"""terminal_run: a shell command on the user's computer, in /workspace.

Most commands are safe. Ones that match a destructive or "download and run" pattern are
risky and need approval. The pattern list is a net, not a wall: the real limits are the
machine itself (no root, blocked private networks, CPU and memory caps).
"""

import re

from crew.computer.provider import ComputerError
from crew.tools.registry import Args, Risk, Tool, ToolContext, ToolError, ToolOutput

RISKY_PATTERNS = [
    re.compile(r"\brm\s+(-[a-zA-Z]*\s+)*-[a-zA-Z]*[rRf]"),  # rm -rf, rm -r, rm -f
    re.compile(r"\b(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(ba|z|da)?sh\b"),  # curl ... | sh
    re.compile(r"\bsudo\b"),
    re.compile(r"\b(mkfs|dd)\b"),
    re.compile(r"\bgit\s+push\b"),
    re.compile(r"\b(npm|pnpm|yarn|twine|cargo)\s+publish\b"),
    re.compile(r">\s*/dev/sd"),
]


def terminal_risk(args: Args, _: ToolContext) -> Risk:
    command = str(args.get("cmd", ""))
    return "risky" if any(pattern.search(command) for pattern in RISKY_PATTERNS) else "safe"


async def _terminal_run(args: Args, ctx: ToolContext) -> ToolOutput:
    timeout = min(float(args.get("timeout", 60)), ctx.settings.terminal_max_seconds)
    try:
        handle = await ctx.computer.handle()
        result = await ctx.computer.provider.exec(handle, args["cmd"], timeout)
    except ComputerError as error:
        raise ToolError(str(error)) from error
    parts = [f"exit code: {result.exit_code}"]
    if result.timed_out:
        parts.append(f"The command was stopped after {timeout:g} seconds.")
    if result.stdout.strip():
        parts.append(f"stdout:\n{result.stdout.rstrip()}")
    if result.stderr.strip():
        parts.append(f"stderr:\n{result.stderr.rstrip()}")
    status = "timed out" if result.timed_out else f"exit {result.exit_code}"
    return ToolOutput("\n".join(parts), f"Ran a command ({status})", source="terminal")


def _summary(args: Args) -> str:
    command = " ".join(str(args.get("cmd", "")).split())
    return f"Ran: {command[:80]}" + ("..." if len(command) > 80 else "")


def make_terminal_tool() -> Tool:
    return Tool(
        name="terminal_run",
        description=(
            "Run a shell command on your computer. It starts in your workspace folder. "
            "Use it for git, scripts, installing packages for a task, and working with files."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "cmd": {"type": "string", "minLength": 1, "maxLength": 8000},
                "timeout": {
                    "type": "number",
                    "minimum": 1,
                    "maximum": 300,
                    "description": "Seconds before the command is stopped (default 60)",
                },
            },
            "required": ["cmd"],
            "additionalProperties": False,
        },
        handler=_terminal_run,
        summary=_summary,
        read_only=False,
        risk=terminal_risk,
        timeout_seconds=460.0,  # the longest command plus starting the computer
    )
