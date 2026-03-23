"""Tests for clarion.adapters.telegram — Telegram delivery adapter."""

from __future__ import annotations

import json

import httpx
import pytest

from clarion.adapters.telegram import TelegramAdapter, _split_message

# ── Constructor ─────────────────────────────────────────────────────────────


class TestConstructor:
    def test_missing_bot_token_raises(self) -> None:
        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN is required"):
            TelegramAdapter("")

    def test_valid_token_sets_base_url(self) -> None:
        adapter = TelegramAdapter("123:ABC")
        assert adapter._base_url == "https://api.telegram.org/bot123:ABC"


# ── Message splitting ──────────────────────────────────────────────────────


class TestSplitMessage:
    def test_short_message_single_chunk(self) -> None:
        assert _split_message("hello") == ["hello"]

    def test_empty_message_single_chunk(self) -> None:
        assert _split_message("") == [""]

    def test_exact_limit_single_chunk(self) -> None:
        msg = "a" * 4096
        assert _split_message(msg) == [msg]

    def test_long_message_splits_at_paragraph(self) -> None:
        para1 = "a" * 2000
        para2 = "b" * 2000
        para3 = "c" * 2000
        msg = f"{para1}\n\n{para2}\n\n{para3}"

        chunks = _split_message(msg)
        assert len(chunks) >= 2
        rejoined = "".join(chunks)
        assert "a" * 2000 in rejoined
        assert "c" * 2000 in rejoined

    def test_long_message_splits_at_newline(self) -> None:
        lines = ["x" * 100 for _ in range(50)]
        msg = "\n".join(lines)

        chunks = _split_message(msg)
        assert len(chunks) >= 2
        for chunk in chunks:
            assert len(chunk) <= 4096

    def test_long_message_hard_splits(self) -> None:
        msg = "x" * 10000
        chunks = _split_message(msg)
        assert len(chunks) >= 3
        for chunk in chunks:
            assert len(chunk) <= 4096
        assert "".join(chunks) == msg


# ── Delivery (using httpx.MockTransport) ────────────────────────────────────


def _make_adapter_with_transport(
    handler,
) -> tuple[TelegramAdapter, httpx.AsyncClient]:
    """Build an adapter and an AsyncClient wired to a mock transport."""
    adapter = TelegramAdapter("fake-token")
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    return adapter, client


class TestDeliver:
    async def test_sends_post_to_correct_url(self, mocker) -> None:
        captured: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            captured.append(request)
            return httpx.Response(200, json={"ok": True})

        adapter, client = _make_adapter_with_transport(handler)
        mocker.patch(
            "clarion.adapters.telegram.httpx.AsyncClient",
            return_value=client,
        )

        result = await adapter.deliver("12345", "hello world", "test")

        assert len(captured) == 1
        assert "/sendMessage" in str(captured[0].url)
        body = json.loads(captured[0].content)
        assert body["chat_id"] == "12345"
        assert body["text"] == "hello world"
        assert body["parse_mode"] == "Markdown"
        assert "Delivered" in result

    async def test_api_error_raises_runtime_error(self, mocker) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, text="Bad Request: something wrong")

        adapter, client = _make_adapter_with_transport(handler)
        mocker.patch(
            "clarion.adapters.telegram.httpx.AsyncClient",
            return_value=client,
        )

        with pytest.raises(RuntimeError, match="Telegram API error"):
            await adapter.deliver("12345", "hello", "test")

    async def test_markdown_parse_failure_retries_without_parse_mode(self, mocker) -> None:
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            body = json.loads(request.content)
            if "parse_mode" in body:
                return httpx.Response(400, text="Bad Request: can't parse entities")
            return httpx.Response(200, json={"ok": True})

        adapter, client = _make_adapter_with_transport(handler)
        mocker.patch(
            "clarion.adapters.telegram.httpx.AsyncClient",
            return_value=client,
        )

        result = await adapter.deliver("12345", "bad *markdown", "test")

        assert len(calls) == 2
        assert "Delivered" in result

    async def test_markdown_retry_also_fails_raises(self, mocker) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content)
            if "parse_mode" in body:
                return httpx.Response(400, text="Bad Request: can't parse entities")
            return httpx.Response(500, text="Internal Server Error")

        adapter, client = _make_adapter_with_transport(handler)
        mocker.patch(
            "clarion.adapters.telegram.httpx.AsyncClient",
            return_value=client,
        )

        with pytest.raises(RuntimeError, match="Telegram API error: 500"):
            await adapter.deliver("12345", "bad", "test")

    async def test_long_message_sends_multiple_chunks(self, mocker) -> None:
        calls: list[httpx.Request] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request)
            return httpx.Response(200, json={"ok": True})

        adapter, client = _make_adapter_with_transport(handler)
        mocker.patch(
            "clarion.adapters.telegram.httpx.AsyncClient",
            return_value=client,
        )

        long_msg = "x" * 10000
        result = await adapter.deliver("12345", long_msg, "test")

        assert len(calls) >= 3
        assert "message(s)" in result
