"""Claude through the official Anthropic SDK, with streaming."""

import anthropic
import structlog
from anthropic.types import MessageParam

from crew.config import Settings
from crew.llm.base import ChatTurn, LLMError, LLMResult, OnDelta

log = structlog.get_logger(__name__)

REFUSAL_TEXT = "I can't help with that request."


def _param(turn: ChatTurn) -> MessageParam:
    if turn.role == "user":
        return {"role": "user", "content": turn.content}
    return {"role": "assistant", "content": turn.content}


class AnthropicLLM:
    def __init__(self, settings: Settings) -> None:
        if not settings.anthropic_api_key:
            raise LLMError("llm_not_configured", "ANTHROPIC_API_KEY is not set on the server.")
        if not settings.crew_model:
            raise LLMError("llm_not_configured", "CREW_MODEL is not set on the server.")
        self._client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
        self._model = settings.crew_model
        self._max_tokens = settings.crew_max_output_tokens

    async def stream(
        self, *, system: str, messages: list[ChatTurn], on_delta: OnDelta
    ) -> LLMResult:
        params = [_param(turn) for turn in messages]
        try:
            async with self._client.messages.stream(
                model=self._model,
                max_tokens=self._max_tokens,
                system=system,
                messages=params,
            ) as stream:
                async for text in stream.text_stream:
                    await on_delta(text)
                final = await stream.get_final_message()
        except anthropic.AuthenticationError as exc:
            raise LLMError(
                "llm_auth_failed", "The server's Anthropic API key was rejected."
            ) from exc
        except anthropic.NotFoundError as exc:
            raise LLMError("llm_model_not_found", "The configured model was not found.") from exc
        except anthropic.RateLimitError as exc:
            raise LLMError(
                "llm_rate_limited", "Claude is busy right now. Try again shortly."
            ) from exc
        except anthropic.APIStatusError as exc:
            log.warning("llm.api_error", status=exc.status_code)
            raise LLMError("llm_failed", "Claude returned an error. Try again.") from exc
        except anthropic.APIConnectionError as exc:
            raise LLMError("llm_unreachable", "Could not reach Claude. Try again.") from exc

        text = "".join(block.text for block in final.content if block.type == "text")
        if final.stop_reason == "refusal" and not text:
            # Declined by a safety classifier: there is no text to show.
            text = REFUSAL_TEXT
            await on_delta(text)
        return LLMResult(
            text=text,
            input_tokens=final.usage.input_tokens,
            output_tokens=final.usage.output_tokens,
            stop_reason=final.stop_reason,
        )
