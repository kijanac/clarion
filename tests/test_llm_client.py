"""Tests for clarion.llm_client — OpenAI SDK-backed LLM client."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from openai import APITimeoutError

from clarion.llm_client import (
    LlmTimeoutError,
    OpenAIStreamingClient,
    _PARSE_FAILURE_TEXT,
    _response_to_turn,
)
from clarion.models import AgentTurn


# ── Helpers ─────────────────────────────────────────────────────────────────


def _mock_completion(content=None, tool_calls=None):
    """Build a mock ChatCompletion response."""
    message = MagicMock()
    message.content = content
    message.tool_calls = tool_calls or None

    choice = MagicMock()
    choice.message = message

    response = MagicMock()
    response.choices = [choice]
    return response


def _mock_tool_call(tc_id: str, name: str, arguments_json: str):
    """Build a mock ChatCompletionMessageToolCall."""
    tc = MagicMock()
    tc.id = tc_id
    tc.function = MagicMock()
    tc.function.name = name
    tc.function.arguments = arguments_json
    return tc


# ── _response_to_turn ──────────────────────────────────────────────────────


class TestResponseToTurn:
    def test_text_content(self) -> None:
        response = _mock_completion(content="Hello world")
        turn = _response_to_turn(response)
        assert turn.text == "Hello world"
        assert turn.tool_calls == []

    def test_tool_calls_parsed(self) -> None:
        tc = _mock_tool_call("tc_1", "web_search", '{"query": "python"}')
        response = _mock_completion(tool_calls=[tc])
        turn = _response_to_turn(response)
        assert turn.text is None
        assert len(turn.tool_calls) == 1
        assert turn.tool_calls[0].name == "web_search"
        assert turn.tool_calls[0].id == "tc_1"
        assert turn.tool_calls[0].arguments == {"query": "python"}

    def test_null_arguments_filtered(self) -> None:
        tc = _mock_tool_call(
            "tc_2", "web_fetch", '{"url": "https://example.com", "mode": null}'
        )
        response = _mock_completion(tool_calls=[tc])
        turn = _response_to_turn(response)
        assert turn.tool_calls[0].arguments == {"url": "https://example.com"}

    def test_invalid_json_arguments(self) -> None:
        tc = _mock_tool_call("tc_3", "broken", "not json")
        response = _mock_completion(tool_calls=[tc])
        turn = _response_to_turn(response)
        assert turn.tool_calls[0].arguments == {}

    def test_whitespace_stripped(self) -> None:
        response = _mock_completion(content="  hello  ")
        turn = _response_to_turn(response)
        assert turn.text == "hello"

    def test_none_content(self) -> None:
        response = _mock_completion(content=None)
        turn = _response_to_turn(response)
        assert turn.text is None

    def test_empty_content(self) -> None:
        response = _mock_completion(content="")
        turn = _response_to_turn(response)
        assert turn.text is None


# ── OpenAIStreamingClient.respond ──────────────────────────────────────────


class TestOpenAIStreamingClient:
    async def test_successful_response(self) -> None:
        response = _mock_completion(content="Hello")
        client = OpenAIStreamingClient(base_url="http://test", api_key="key")

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = response
            turn = await client.respond(
                system_prompt="sys",
                messages=[],
                tools=[],
                model="test-model",
                max_tokens=100,
            )

        assert isinstance(turn, AgentTurn)
        assert turn.text == "Hello"
        assert turn.parse_failure is False

    async def test_blank_response_triggers_retry_then_parse_failure(self) -> None:
        blank = _mock_completion(content=None, tool_calls=None)
        client = OpenAIStreamingClient(base_url="http://test", api_key="key")

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = blank
            turn = await client.respond(
                system_prompt="sys",
                messages=[],
                tools=[],
                model="test-model",
                max_tokens=100,
            )

        assert mock_create.call_count == 2
        assert turn.text == _PARSE_FAILURE_TEXT
        assert turn.parse_failure is True

    async def test_timeout_raises_llm_timeout_error(self) -> None:
        client = OpenAIStreamingClient(base_url="http://test", api_key="key")

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.side_effect = APITimeoutError(request=MagicMock())
            with pytest.raises(LlmTimeoutError):
                await client.respond(
                    system_prompt="sys",
                    messages=[],
                    tools=[],
                    model="test-model",
                    max_tokens=100,
                )

    async def test_tools_not_sent_when_empty(self) -> None:
        response = _mock_completion(content="hi")
        client = OpenAIStreamingClient(base_url="http://test", api_key="key")

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = response
            await client.respond(
                system_prompt="sys",
                messages=[],
                tools=[],
                model="test-model",
                max_tokens=100,
            )

        call_kwargs = mock_create.call_args[1]
        assert "tools" not in call_kwargs

    async def test_tools_sent_when_present(self) -> None:
        response = _mock_completion(content="hi")
        client = OpenAIStreamingClient(base_url="http://test", api_key="key")
        tool_schema = [{"type": "function", "function": {"name": "test"}}]

        with patch.object(
            client._client.chat.completions, "create", new_callable=AsyncMock
        ) as mock_create:
            mock_create.return_value = response
            await client.respond(
                system_prompt="sys",
                messages=[],
                tools=tool_schema,
                model="test-model",
                max_tokens=100,
            )

        call_kwargs = mock_create.call_args[1]
        assert call_kwargs["tools"] == tool_schema
