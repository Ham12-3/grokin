"""Step and token budgets. A run stops with a clear message when one is used up."""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from crew import usage
from crew.config import Settings
from crew.models import Run, User

DAILY_LIMIT_MESSAGE = "Daily limit reached, resets at midnight UTC."


@dataclass(frozen=True)
class BudgetStop:
    code: str
    message: str


async def check_budget(
    session: AsyncSession, settings: Settings, run: Run, user_id: uuid.UUID
) -> BudgetStop | None:
    """Called before every LLM call. Returns why the run must stop, or None."""
    if run.input_tokens + run.output_tokens >= settings.crew_max_run_tokens:
        return BudgetStop(
            "run_token_limit",
            "I stopped because this request used its token limit. "
            "Ask me to continue if you need more.",
        )
    user = await session.get(User, user_id)
    today = await usage.usage_today(session, user_id)
    daily_budget = user.daily_token_budget if user is not None else 0
    if today.input_tokens + today.output_tokens >= daily_budget:
        return BudgetStop("daily_token_limit", DAILY_LIMIT_MESSAGE)
    return None


def step_limit_stop(settings: Settings) -> BudgetStop:
    steps = settings.crew_max_steps
    return BudgetStop(
        "step_limit",
        f"I stopped after {steps} steps, which is the limit for one request. "
        "Ask me to continue if you want me to keep going.",
    )
