"""The LLM behind one small interface, so the agent run can be tested with a fake."""

from crew.llm.base import LLM, ChatTurn, LLMError, LLMResult, OnDelta
from crew.llm.factory import create_llm

__all__ = ["LLM", "ChatTurn", "LLMError", "LLMResult", "OnDelta", "create_llm"]
