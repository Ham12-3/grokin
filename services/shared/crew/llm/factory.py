"""Picks the LLM from settings."""

from crew.config import Settings
from crew.llm.anthropic_llm import AnthropicLLM
from crew.llm.base import LLM
from crew.llm.fake import FakeLLM


def create_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "fake":
        if settings.crew_env == "prod":
            raise RuntimeError("LLM_PROVIDER=fake is not allowed in prod.")
        return FakeLLM(delay_seconds=settings.fake_llm_delay_seconds)
    return AnthropicLLM(settings)
