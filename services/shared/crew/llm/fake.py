"""A scripted LLM for tests and for running the app without an API key (LLM_PROVIDER=fake)."""

import asyncio

from crew.llm.base import ChatTurn, LLMError, LLMResult, OnDelta

DEFAULT_REPLY = (
    "This is a **test reply** from the fake model, so you can try Crew without an API key.\n\n"
    "- It streams word by word\n- It supports `markdown`\n\nYou said: "
)


class FakeLLM:
    """Streams `chunks` (or echoes the last user message) and records what it was asked."""

    def __init__(
        self,
        chunks: list[str] | None = None,
        *,
        delay_seconds: float = 0.0,
        error: LLMError | None = None,
        fail_after: int | None = None,
    ) -> None:
        self.chunks = chunks
        self.delay_seconds = delay_seconds
        self.error = error
        self.fail_after = fail_after
        self.calls: list[tuple[str, list[ChatTurn]]] = []

    async def stream(
        self, *, system: str, messages: list[ChatTurn], on_delta: OnDelta
    ) -> LLMResult:
        self.calls.append((system, messages))
        if self.error is not None and self.fail_after is None:
            raise self.error
        chunks = self.chunks
        if chunks is None:
            reply = DEFAULT_REPLY + (messages[-1].content if messages else "")
            chunks = [word + " " for word in reply.split(" ")]
        sent: list[str] = []
        for index, chunk in enumerate(chunks):
            if self.fail_after is not None and index >= self.fail_after:
                raise self.error or LLMError("llm_failed", "Claude returned an error. Try again.")
            if self.delay_seconds:
                await asyncio.sleep(self.delay_seconds)
            await on_delta(chunk)
            sent.append(chunk)
        text = "".join(sent)
        return LLMResult(
            text=text,
            input_tokens=sum(len(turn.content) for turn in messages) // 4 + len(system) // 4,
            output_tokens=max(1, len(text) // 4),
            stop_reason="end_turn",
        )
