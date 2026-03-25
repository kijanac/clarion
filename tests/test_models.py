"""Tests for clarion.models — layer 0 data shapes."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from clarion.models import (
    AgentConfig,
    AgentRun,
    AgentTurn,
    OutputDefinition,
    OutputTrigger,
    OutputType,
    ResourceEnvelope,
    RunContext,
    RunStatus,
    ToolCallRequest,
)


# ── Fixtures ────────────────────────────────────────────────────────────────


def _make_output(**overrides: object) -> OutputDefinition:
    defaults = {
        "name": "daily-digest",
        "trigger": OutputTrigger.SCHEDULED,
        "type": OutputType.TELEGRAM,
        "destination": "@test_channel",
    }
    return OutputDefinition(**(defaults | overrides))


def _make_agent_config(**overrides: object) -> AgentConfig:
    defaults = {
        "agent_id": "agent-001",
        "name": "Test Agent",
        "description": "A test agent",
        "owner": "team-a",
        "version": 1,
        "template": "research",
        "triggers": [],
        "outputs": [_make_output()],
        "database_enabled": False,
        "resources": ResourceEnvelope(),
        "tools": ["web_search", "fetch_page"],
    }
    return AgentConfig(**(defaults | overrides))


def _make_agent_run(**overrides: object) -> AgentRun:
    defaults = {
        "run_id": "run-abc",
        "agent_id": "agent-001",
        "started_at": datetime(2026, 1, 1, tzinfo=timezone.utc),
        "status": RunStatus.RUNNING,
        "trigger": "scheduled",
    }
    return AgentRun(**(defaults | overrides))


# ── Instantiation ───────────────────────────────────────────────────────────


class TestInstantiation:
    def test_output_definition(self) -> None:
        od = _make_output()
        assert od.name == "daily-digest"
        assert od.trigger == OutputTrigger.SCHEDULED
        assert od.type == OutputType.TELEGRAM

    def test_resource_envelope(self) -> None:
        re = ResourceEnvelope()
        assert re.max_runs_per_day == 12

    def test_agent_config(self) -> None:
        cfg = _make_agent_config()
        assert cfg.agent_id == "agent-001"
        assert cfg.model == "claude-sonnet-4-6"
        assert cfg.max_tokens == 8192

    def test_agent_run(self) -> None:
        run = _make_agent_run()
        assert run.run_id == "run-abc"
        assert run.status == RunStatus.RUNNING
        assert run.outputs_produced == []
        assert run.tool_call_counts == {}

    def test_tool_call_request(self) -> None:
        tc = ToolCallRequest(name="web_search", arguments={"query": "test"}, id="tc-1")
        assert tc.name == "web_search"
        assert tc.arguments == {"query": "test"}

    def test_agent_turn(self) -> None:
        turn = AgentTurn(text="hello")
        assert turn.text == "hello"
        assert turn.tool_calls == []
        assert turn.parse_failure is False

    def test_run_context(self) -> None:
        cfg = _make_agent_config()
        ctx = RunContext(
            agent_id="agent-001",
            run_id="run-abc",
            config=cfg,
            mission_md="# Mission",
            workspace_root="/tmp/workspace",
            trigger="scheduled",
            current_datetime=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )
        assert ctx.agent_id == "agent-001"
        assert ctx.config is cfg


# ── Frozen immutability ─────────────────────────────────────────────────────


class TestFrozen:
    def test_agent_config_rejects_mutation(self) -> None:
        cfg = _make_agent_config()
        with pytest.raises(ValidationError):
            cfg.name = "mutated"

    def test_agent_run_rejects_mutation(self) -> None:
        run = _make_agent_run()
        with pytest.raises(ValidationError):
            run.status = RunStatus.SUCCESS


# ── Enum round-trip ─────────────────────────────────────────────────────────


class TestEnumSerialization:
    def test_run_status_roundtrip(self) -> None:
        run = _make_agent_run(status=RunStatus.SUCCESS)
        data = run.model_dump()
        assert data["status"] == "success"
        restored = AgentRun.model_validate(data)
        assert restored.status == RunStatus.SUCCESS

    def test_run_status_from_string(self) -> None:
        run = AgentRun.model_validate(
            {
                "run_id": "run-x",
                "agent_id": "agent-001",
                "started_at": "2026-01-01T00:00:00Z",
                "status": "failed",
                "trigger": "manual",
            }
        )
        assert run.status == RunStatus.FAILED

    def test_output_trigger_from_string(self) -> None:
        od = OutputDefinition.model_validate(
            {
                "name": "alert",
                "trigger": "agent_decides",
                "type": "webhook",
                "destination": "https://example.com/hook",
            }
        )
        assert od.trigger == OutputTrigger.AGENT_DECIDES
        assert od.type == OutputType.WEBHOOK


# ── ResourceEnvelope defaults ───────────────────────────────────────────────


class TestResourceEnvelopeDefaults:
    def test_all_defaults(self) -> None:
        re = ResourceEnvelope()
        assert re.max_runs_per_day == 12
        assert re.max_search_calls_per_run == 30
        assert re.max_fetch_calls_per_run == 15
        assert re.max_deep_research_calls_per_run == 3
        assert re.max_sql_calls_per_run == 50
        assert re.run_timeout_seconds == 600
        assert re.max_database_mb == 1000
        assert re.max_self_scheduled_runs_per_day == 6

    def test_override_single_default(self) -> None:
        re = ResourceEnvelope(max_runs_per_day=24)
        assert re.max_runs_per_day == 24
        assert re.max_search_calls_per_run == 30  # other defaults unchanged
