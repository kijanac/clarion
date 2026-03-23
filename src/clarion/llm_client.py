"""OpenAI-compatible LLM client for Clarion.

Uses the openai SDK for request handling, streaming, and error management.
"""

from __future__ import annotations

import json
import os
from typing import Any

import structlog
from openai import APITimeoutError, AsyncOpenAI

from clarion.models import AgentTurn, ToolCallRequest

log = structlog.get_logger()

_DEFAULT_TIMEOUT_S = 90.0
_PARSE_FAILURE_TEXT = (
    "I ran into an internal response-format error while composing that reply. Please retry."
)


class LlmTimeoutError(TimeoutError):
    """Raised when an LLM call exceeds the timeout."""


class OpenAIStreamingClient:
    """OpenAI-compatible LLM client backed by the openai SDK."""

    def __init__(
        self,
        *,
        base_url: str = "",
        api_key: str = "",
        timeout_s: float = _DEFAULT_TIMEOUT_S,
    ) -> None:
        resolved_base_url = base_url or os.environ.get("LLM_BASE_URL", "").strip().rstrip("/")
        resolved_api_key = api_key or os.environ.get("LLM_API_KEY", "").strip()
        self._timeout_s = timeout_s
        self._client = AsyncOpenAI(
            base_url=resolved_base_url or None,
            api_key=resolved_api_key or "unused",
            timeout=timeout_s,
            max_retries=0,
        )

    async def respond(
        self,
        *,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        model: str,
        max_tokens: int,
    ) -> AgentTurn:
        all_messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            *messages,
        ]

        kwargs: dict[str, Any] = {
            "model": model,
            "messages": all_messages,
            "max_tokens": max_tokens,
        }
        if tools:
            kwargs["tools"] = tools

        for attempt in range(2):
            try:
                response = await self._client.chat.completions.create(**kwargs)
            except APITimeoutError as exc:
                log.error("llm.timeout", timeout_s=self._timeout_s)
                raise LlmTimeoutError("model response timed out") from exc

            turn = _response_to_turn(response)

            is_blank = turn.text is None and not turn.tool_calls
            if is_blank and attempt == 0:
                log.warning("llm.retry_blank")
                continue

            if not is_blank:
                log.info(
                    "llm.response",
                    content_len=len(turn.text) if turn.text else 0,
                    tool_call_count=len(turn.tool_calls),
                )
                return turn

        log.error("llm.parse_fallback", error="blank response after retry")
        return AgentTurn(text=_PARSE_FAILURE_TEXT, parse_failure=True)


def _response_to_turn(response: Any) -> AgentTurn:
    """Convert a ChatCompletion response to an AgentTurn."""
    choice = response.choices[0]
    msg = choice.message

    text = (msg.content or "").strip() or None

    tool_calls: list[ToolCallRequest] = []
    if msg.tool_calls:
        for tc in msg.tool_calls:
            try:
                parsed = json.loads(tc.function.arguments)
            except (json.JSONDecodeError, TypeError):
                parsed = {}
            arguments: dict[str, object] = {k: v for k, v in parsed.items() if v is not None}
            tool_calls.append(
                ToolCallRequest(
                    name=tc.function.name,
                    arguments=arguments,
                    id=tc.id or "",
                ),
            )

    return AgentTurn(text=text, tool_calls=tool_calls)
