"""Tests for clarion.tools.executor — tool dispatch, staging, and memoization."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clarion.models import AgentConfig, ResourceEnvelope
from clarion.tools.base import ToolResult
from clarion.tools.executor import ToolExecutor, TurnSideEffects

# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_config(**overrides: object) -> AgentConfig:
    defaults: dict[str, object] = {
        "agent_id": "test-agent",
        "name": "Test Agent",
        "description": "test",
        "owner": "test",
        "version": 1,
        "template": "research",
        "schedule_cron": "0 * * * *",
        "schedule_timezone": "UTC",
        "outputs": [],
        "database_enabled": True,
        "resources": ResourceEnvelope(),
        "tools": ["current_datetime", "execute_sql", "write_file", "cron"],
    }
    return AgentConfig(**(defaults | overrides))


def _make_executor(tmp_workspace: Path, **overrides: object) -> ToolExecutor:
    config = _make_config()
    return ToolExecutor(
        agent_id="test-agent",
        agent_config=config,
        workspace_root=tmp_workspace,
        **overrides,
    )


def _mock_handler(return_result: ToolResult | None = None) -> MagicMock:
    """Create a mock ToolHandler with async validate and execute."""
    handler = MagicMock()
    handler.validate = AsyncMock(side_effect=lambda args, ctx: args)
    handler.execute = AsyncMock(
        return_value=return_result or ToolResult(text="mock result"),
    )
    return handler


# ── Dispatch ────────────────────────────────────────────────────────────────


class TestDispatch:
    async def test_current_datetime_returns_text(self, tmp_workspace: Path) -> None:
        executor = _make_executor(tmp_workspace)
        mock = _mock_handler(ToolResult(text="Sunday, March 22, 2026 — 07:15 PM (UTC)"))
        with patch.dict(executor._handlers, {"current_datetime": mock}):
            result = await executor.execute("current_datetime", {}, correlation_id="d-1")
        assert "text" in result
        assert len(result["text"]) > 0
        mock.execute.assert_called_once()

    async def test_execute_sql_dispatches_correctly(
        self, tmp_workspace: Path
    ) -> None:
        executor = _make_executor(tmp_workspace)
        mock = _mock_handler(ToolResult(text="rows_affected: 0"))
        with patch.dict(executor._handlers, {"execute_sql": mock}):
            result = await executor.execute(
                "execute_sql",
                {"name": "testdb", "sql": "SELECT 1"},
                correlation_id="d-2",
            )
        assert result["text"] == "rows_affected: 0"
        mock.execute.assert_called_once()

    async def test_write_file_dispatches_correctly(
        self, tmp_workspace: Path
    ) -> None:
        executor = _make_executor(tmp_workspace)
        mock = _mock_handler(ToolResult(text="wrote 5 bytes"))
        with patch.dict(executor._handlers, {"write_file": mock}):
            result = await executor.execute(
                "write_file",
                {"path": "out.txt", "content": "hello"},
                correlation_id="d-3",
            )
        assert result["text"] == "wrote 5 bytes"
        mock.execute.assert_called_once()


# ── Unknown tool ────────────────────────────────────────────────────────────


class TestUnknownTool:
    async def test_unknown_tool_raises_key_error(
        self, tmp_workspace: Path
    ) -> None:
        executor = _make_executor(tmp_workspace)
        with pytest.raises(KeyError):
            await executor.execute("no_such_tool", {}, correlation_id="u-1")


# ── Turn staging ────────────────────────────────────────────────────────────


class TestTurnStaging:
    async def test_start_execute_commit_returns_side_effects(
        self, tmp_workspace: Path
    ) -> None:
        executor = _make_executor(tmp_workspace)
        executor.start_turn()

        fake_job = MagicMock()
        fake_job.job_id = "j-1"

        mock = _mock_handler(ToolResult(
            text="Job added: reminder (kind=cron) [id=j-1]",
            cron_registrations=[fake_job],
        ))
        with patch.dict(executor._handlers, {"cron": mock}):
            await executor.execute(
                "cron",
                {"action": "add", "name": "reminder", "kind": "cron", "cron": "0 9 * * *"},
                correlation_id="s-1",
            )

        effects = executor.commit_turn()
        assert len(effects.cron_registrations) == 1
        assert effects.cron_registrations[0].job_id == "j-1"

    def test_start_turn_twice_raises(self, tmp_workspace: Path) -> None:
        executor = _make_executor(tmp_workspace)
        executor.start_turn()
        with pytest.raises(RuntimeError, match="already in progress"):
            executor.start_turn()

    def test_commit_without_start_returns_empty(self, tmp_workspace: Path) -> None:
        executor = _make_executor(tmp_workspace)
        effects = executor.commit_turn()
        assert effects.cron_registrations == []
        assert effects.cron_unregistrations == []
        assert effects.outputs_delivered == []


# ── Discard turn ────────────────────────────────────────────────────────────


class TestDiscardTurn:
    async def test_discard_clears_staged_effects(
        self, tmp_workspace: Path
    ) -> None:
        executor = _make_executor(tmp_workspace)
        executor.start_turn()

        # Stage some effects via the internal target
        fake_job = MagicMock()
        fake_job.job_id = "j-2"
        executor._target().cron_registrations.append(fake_job)

        executor.discard_turn()

        # After discard, commit should return empty effects
        effects = executor.commit_turn()
        assert effects.cron_registrations == []
        assert effects.cron_unregistrations == []

    def test_discard_clears_memo(self, tmp_workspace: Path) -> None:
        executor = _make_executor(tmp_workspace)
        executor.start_turn()
        executor._memo["test:key"] = {"text": "cached"}
        executor.discard_turn()
        assert executor._memo == {}


# ── Memoization ─────────────────────────────────────────────────────────────


class TestMemoization:
    async def test_memoized_tool_called_once_per_turn(
        self, tmp_workspace: Path
    ) -> None:
        executor = _make_executor(tmp_workspace)
        executor.start_turn()

        mock = _mock_handler(ToolResult(text="Sunday, March 22, 2026 — 07:15 PM (UTC)"))
        with patch.dict(executor._handlers, {"current_datetime": mock}):
            r1 = await executor.execute("current_datetime", {}, correlation_id="m-1")
            r2 = await executor.execute("current_datetime", {}, correlation_id="m-2")

        assert r1 == r2
        assert mock.execute.call_count == 1

    async def test_memo_cleared_across_turns(
        self, tmp_workspace: Path
    ) -> None:
        executor = _make_executor(tmp_workspace)

        mock = _mock_handler()
        call_count = 0

        async def _counting_execute(args, ctx):
            nonlocal call_count
            call_count += 1
            return ToolResult(text=f"result-{call_count}")

        mock.execute = AsyncMock(side_effect=_counting_execute)

        with patch.dict(executor._handlers, {"current_datetime": mock}):
            executor.start_turn()
            r1 = await executor.execute("current_datetime", {}, correlation_id="m-3")
            executor.commit_turn()

            executor.start_turn()
            r2 = await executor.execute("current_datetime", {}, correlation_id="m-4")
            executor.commit_turn()

        assert "text" in r1
        assert "text" in r2
        # dispatch called twice — memo was cleared between turns
        assert call_count == 2


# ── Non-memoized tools ─────────────────────────────────────────────────────


class TestNonMemoized:
    async def test_execute_sql_always_re_executes(
        self, tmp_workspace: Path
    ) -> None:
        executor = _make_executor(tmp_workspace)
        executor.start_turn()

        mock = _mock_handler(ToolResult(text="[]"))
        with patch.dict(executor._handlers, {"execute_sql": mock}):
            await executor.execute(
                "execute_sql",
                {"name": "db", "sql": "SELECT 1"},
                correlation_id="nm-1",
            )
            await executor.execute(
                "execute_sql",
                {"name": "db", "sql": "SELECT 1"},
                correlation_id="nm-2",
            )

        # execute_sql has memoize_duplicate_calls_within_turn=False
        assert mock.execute.call_count == 2
        executor.commit_turn()
