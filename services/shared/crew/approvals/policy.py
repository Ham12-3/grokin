"""Which tool calls need the user's approval. Decided on the server, never by the model.

Modes (docs/06-agent-loop.md):
  always_ask  every tool except read-only ones needs approval
  ask_risky   only risky calls need approval (default)
  never_ask   same as ask_risky: risky calls ALWAYS ask, whatever the mode

A call that needs approval becomes an `approvals` row and the run stops until the user
answers (see `crew.agent.loop` and `crew.approvals.service`).
"""

from dataclasses import dataclass

from crew.tools.registry import Risk, Tool


@dataclass(frozen=True)
class Decision:
    needs_approval: bool
    reason: str | None = None


def check(approval_mode: str, tool: Tool, risk: Risk) -> Decision:
    if risk == "risky":
        return Decision(True, "This is a risky action, so it needs the user's approval.")
    if approval_mode == "always_ask" and not tool.read_only:
        return Decision(True, "This Bot is set to always ask before it changes anything.")
    return Decision(False)
