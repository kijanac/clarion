"""Tests for clarion.agent_runner — the agent execution loop."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from clarion.agent_runner import (
    MAX_TOOL_STEPS,
    ParseFailureError,
    ResourceLimitError,
    ResourceTracker,
    ToolLoopExhaustedError,
    run_agent,
)
from clarion.models import (
    AgentConfig,
    AgentTurn,
    ResourceEnvelope,
    RunContext,
    RunStatus,
    ToolCallRequest,
)
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
        "triggers": [],
        "timezone": "UTC",
        "outputs": [],
        "database_enabled": True,
        "resources": ResourceEnvelope(run_timeout_seconds=30),
        "tools": ["web_search"],
        "base_system_prompt": "You are a test agent.",
    }
    return AgentConfig(**(defaults | overrides))


def _make_context(config: AgentConfig | None = None, **overrides: object) -> RunContext:
    if config is None:
        config = _make_config()
    defaults: dict[str, object] = {
        "agent_id": "test-agent",
        "run_id": "run_test123",
        "config": config,
        "mission_md": "Do test stuff.",
        "workspace_root": "",  # overridden per-test
        "trigger": "manual",
        "current_datetime": datetime(2026, 3, 22, 14, 0, 0, tzinfo=UTC),
    }
    return RunContext(**(defaults | overrides))


def _make_executor(tmp_workspace: Path) -> ToolExecutor:
    config = _make_config()
    return ToolExecutor(
        agent_id="test-agent",
        agent_config=config,
        workspace_root=tmp_workspace,
    )


def _mock_llm_text(text: str) -> AsyncMock:
    """Create a mock LLM client that returns a single text response."""
    client = AsyncMock()
    client.respond.return_value = AgentTurn(text=text)
    return client


def _mock_llm_sequence(turns: list[AgentTurn]) -> AsyncMock:
    """Create a mock LLM client that returns turns in sequence."""
    client = AsyncMock()
    client.respond.side_effect = turns
    return client


# ── ResourceTracker ─────────────────────────────────────────────────────────


class TestResourceTracker:
    def test_within_limits(self) -> None:
        envelope = ResourceEnvelope(max_search_calls_per_run=3)
        tracker = ResourceTracker(envelope)
        tracker.check_and_record("web_search")
        tracker.check_and_record("web_search")
        tracker.check_and_record("web_search")
        assert tracker.counts["web_search"] == 3

    def test_exceeds_limit_raises(self) -> None:
        envelope = ResourceEnvelope(max_search_calls_per_run=1)
        tracker = ResourceTracker(envelope)
        tracker.check_and_record("web_search")
        with pytest.raises(ResourceLimitError, match="max_search_calls_per_run"):
            tracker.check_and_record("web_search")

    def test_untracked_tool_unlimited(self) -> None:
        envelope = ResourceEnvelope()
        tracker = ResourceTracker(envelope)
        for _ in range(100):
            tracker.check_and_record("current_datetime")
        assert tracker.counts["current_datetime"] == 100

    def test_web_extract_counts_against_fetch(self) -> None:
        envelope = ResourceEnvelope(max_fetch_calls_per_run=1)
        tracker = ResourceTracker(envelope)
        tracker.check_and_record("web_extract")
        with pytest.raises(ResourceLimitError, match="max_fetch_calls_per_run"):
            tracker.check_and_record("web_extract")

    def test_sql_limit(self) -> None:
        envelope = ResourceEnvelope(max_sql_calls_per_run=2)
        tracker = ResourceTracker(envelope)
        tracker.check_and_record("execute_sql")
        tracker.check_and_record("execute_sql")
        with pytest.raises(ResourceLimitError, match="max_sql_calls_per_run"):
            tracker.check_and_record("execute_sql")

    def test_deep_research_limit(self) -> None:
        envelope = ResourceEnvelope(max_deep_research_calls_per_run=1)
        tracker = ResourceTracker(envelope)
        tracker.check_and_record("deep_research")
        with pytest.raises(ResourceLimitError, match="max_deep_research_calls_per_run"):
            tracker.check_and_record("deep_research")


# ── run_agent success path ──────────────────────────────────────────────────


class TestRunAgentSuccess:
    async def test_simple_text_response(self, tmp_workspace: Path) -> None:
        ctx = _make_context(workspace_root=str(tmp_workspace))
        llm = _mock_llm_text("Here is your briefing.")
        executor = _make_executor(tmp_workspace)

        run = await run_agent(ctx, llm, executor)

        assert run.status == RunStatus.SUCCESS
        assert run.error is None
        assert run.run_id == "run_test123"
        assert run.agent_id == "test-agent"
        assert run.started_at is not None
        assert run.completed_at is not None

    async def test_run_recorded_to_history(self, tmp_workspace: Path) -> None:
        ctx = _make_context(workspace_root=str(tmp_workspace))
        llm = _mock_llm_text("Done.")
        executor = _make_executor(tmp_workspace)

        await run_agent(ctx, llm, executor)

        history_file = tmp_workspace / "runs" / "history.jsonl"
        assert history_file.exists()
        lines = history_file.read_text().strip().split("\n")
        assert len(lines) == 1


# ── Tool call path ──────────────────────────────────────────────────────────


class TestRunAgentToolCalls:
    async def test_tool_calls_executed(self, tmp_workspace: Path) -> None:
        ctx = _make_context(workspace_root=str(tmp_workspace))

        # Turn 1: LLM requests a tool call
        turn1 = AgentTurn(
            text="Let me search.",
            tool_calls=[
                ToolCallRequest(name="web_search", arguments={"query": "test"}, id="tc-1"),
            ],
        )
        # Turn 2: LLM responds with final text
        turn2 = AgentTurn(text="Here are the results.")

        llm = _mock_llm_sequence([turn1, turn2])
        executor = _make_executor(tmp_workspace)

        mock_handler = MagicMock()
        mock_handler.validate = AsyncMock(side_effect=lambda args, ctx: args)
        mock_handler.execute = AsyncMock(
            return_value=ToolResult(text="Search results here.")
        )
        with patch.dict(executor._handlers, {"web_search": mock_handler}):
            run = await run_agent(ctx, llm, executor)

        assert run.status == RunStatus.SUCCESS
        assert run.tool_call_counts.get("web_search") == 1

    async def test_outputs_tracked(self, tmp_workspace: Path) -> None:
        ctx = _make_context(workspace_root=str(tmp_workspace))

        turn1 = AgentTurn(
            tool_calls=[
                ToolCallRequest(
                    name="deliver_output",
                    arguments={"output_name": "briefing", "content": "hello"},
                    id="tc-1",
                ),
            ],
        )
        turn2 = AgentTurn(text="Delivered.")

        llm = _mock_llm_sequence([turn1, turn2])
        executor = _make_executor(tmp_workspace)

        mock_handler = MagicMock()
        mock_handler.validate = AsyncMock(side_effect=lambda args, ctx: args)
        mock_handler.execute = AsyncMock(
            return_value=ToolResult(
                text="Delivered to channel.",
                outputs_delivered=["briefing"],
            )
        )
        with patch.dict(executor._handlers, {"deliver_output": mock_handler}):
            run = await run_agent(ctx, llm, executor)

        assert run.status == RunStatus.SUCCESS
        assert "briefing" in run.outputs_produced


# ── Resource limit ──────────────────────────────────────────────────────────


class TestRunAgentResourceLimit:
    async def test_resource_limit_fails_run(self, tmp_workspace: Path) -> None:
        config = _make_config(
            resources=ResourceEnvelope(max_search_calls_per_run=1, run_timeout_seconds=30),
        )
        ctx = _make_context(config=config, workspace_root=str(tmp_workspace))

        # LLM keeps requesting searches
        search_turn = AgentTurn(
            tool_calls=[
                ToolCallRequest(name="web_search", arguments={"query": "a"}, id="tc-1"),
                ToolCallRequest(name="web_search", arguments={"query": "b"}, id="tc-2"),
            ],
        )
        llm = _mock_llm_sequence([search_turn])
        executor = _make_executor(tmp_workspace)

        mock_handler = MagicMock()
        mock_handler.validate = AsyncMock(side_effect=lambda args, ctx: args)
        mock_handler.execute = AsyncMock(return_value=ToolResult(text="results"))
        with patch.dict(executor._handlers, {"web_search": mock_handler}):
            run = await run_agent(ctx, llm, executor)

        assert run.status == RunStatus.FAILED
        assert "max_search_calls_per_run" in run.error


# ── Timeout ─────────────────────────────────────────────────────────────────


class TestRunAgentTimeout:
    async def test_timeout_sets_status(self, tmp_workspace: Path) -> None:
        config = _make_config(
            resources=ResourceEnvelope(run_timeout_seconds=1),
        )
        ctx = _make_context(config=config, workspace_root=str(tmp_workspace))

        async def slow_respond(**kwargs):
            await asyncio.sleep(10)
            return AgentTurn(text="Too late.")

        llm = AsyncMock()
        llm.respond.side_effect = slow_respond
        executor = _make_executor(tmp_workspace)

        import asyncio

        run = await run_agent(ctx, llm, executor)

        assert run.status == RunStatus.TIMEOUT
        assert "timed out" in run.error


# ── Tool error ──────────────────────────────────────────────────────────────


class TestRunAgentToolError:
    async def test_tool_error_continues_run(self, tmp_workspace: Path) -> None:
        ctx = _make_context(workspace_root=str(tmp_workspace))

        turn1 = AgentTurn(
            tool_calls=[
                ToolCallRequest(name="web_search", arguments={"query": "fail"}, id="tc-1"),
            ],
        )
        turn2 = AgentTurn(text="I'll work around that error.")

        llm = _mock_llm_sequence([turn1, turn2])
        executor = _make_executor(tmp_workspace)

        mock_handler = MagicMock()
        mock_handler.validate = AsyncMock(side_effect=lambda args, ctx: args)
        mock_handler.execute = AsyncMock(side_effect=RuntimeError("network error"))
        with patch.dict(executor._handlers, {"web_search": mock_handler}):
            run = await run_agent(ctx, llm, executor)

        assert run.status == RunStatus.SUCCESS
        # The LLM got a second call after the tool error
        assert llm.respond.call_count == 2


# ── Parse failure ───────────────────────────────────────────────────────────


class TestRunAgentParseFailure:
    async def test_parse_failure_exits_cleanly(self, tmp_workspace: Path) -> None:
        ctx = _make_context(workspace_root=str(tmp_workspace))
        llm = AsyncMock()
        llm.respond.return_value = AgentTurn(
            text="Parse error occurred.",
            parse_failure=True,
        )
        executor = _make_executor(tmp_workspace)

        run = await run_agent(ctx, llm, executor)

        assert run.status == RunStatus.FAILED
        assert "unparseable" in run.error
        assert llm.respond.call_count == 1


# ── Max steps ───────────────────────────────────────────────────────────────


class TestRunAgentMaxSteps:
    async def test_exits_at_max_tool_steps(self, tmp_workspace: Path) -> None:
        config = _make_config(
            resources=ResourceEnvelope(run_timeout_seconds=30),
            tools=["current_datetime"],
        )
        ctx = _make_context(config=config, workspace_root=str(tmp_workspace))

        # LLM always returns a tool call
        always_tool = AgentTurn(
            tool_calls=[
                ToolCallRequest(name="current_datetime", arguments={}, id="tc-loop"),
            ],
        )
        llm = AsyncMock()
        llm.respond.return_value = always_tool
        executor = _make_executor(tmp_workspace)

        mock_handler = MagicMock()
        mock_handler.validate = AsyncMock(side_effect=lambda args, ctx: args)
        mock_handler.execute = AsyncMock(return_value=ToolResult(text="now"))
        with patch.dict(executor._handlers, {"current_datetime": mock_handler}):
            run = await run_agent(ctx, llm, executor)

        assert run.status == RunStatus.FAILED
        assert "exceeded" in run.error
        assert llm.respond.call_count == MAX_TOOL_STEPS
