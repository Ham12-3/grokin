"""The LLM behind one small interface, so the agent loop can be tested with a fake."""

from crew.llm.base import LLM, LLMError, LLMResult, MessageDict, OnDelta, ToolUse
from crew.llm.factory import create_llm, create_small_llm

__all__ = [
    "LLM",
    "LLMError",
    "LLMResult",
    "MessageDict",
    "OnDelta",
    "ToolUse",
    "create_llm",
    "create_small_llm",
]
