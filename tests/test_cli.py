"""Tests for clarion.cli — the CLI entry point (Layer 5)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from clarion.cli import app
from clarion.models import (
    AgentConfig,
    AgentRun,
    ResourceEnvelope,
    RunStatus,
)

runner = CliRunner()


# ── Helpers ─────────────────────────────────────────────────────────────


def _make_config(**overrides: object) -> AgentConfig:
    defaults: dict[str, object] = {
        "agent_id": "test-agent",
        "name": "Test Agent",
        "description": "test",
        "owner": "test",
        "version": 1,
        "template": "research",
        "triggers": [],
        "outputs": [],
        "database_enabled": True,
        "resources": ResourceEnvelope(run_timeout_seconds=30),
        "tools": ["web_search"],
        "base_system_prompt": "You are a test agent.",
    }
    return AgentConfig(**(defaults | overrides))


def _make_agent_run(*, status: RunStatus = RunStatus.SUCCESS, **overrides: object) -> AgentRun:
    defaults: dict[str, object] = {
        "run_id": "run_test123",
        "agent_id": "test-agent",
        "started_at": datetime(2026, 3, 22, 14, 0, 0, tzinfo=UTC),
        "completed_at": datetime(2026, 3, 22, 14, 0, 45, tzinfo=UTC),
        "status": status,
        "trigger": "manual",
    }
    return AgentRun(**(defaults | overrides))


def _write_agent_yaml(agent_dir: Path) -> None:
    agent_dir.mkdir(parents=True, exist_ok=True)
    (agent_dir / "agent.yaml").write_text(
        "meta:\n"
        "  name: Test Agent\n"
        "  description: A test agent\n"
        "  owner: test\n"
        "  version: 1\n"
        "template: research\n"
        "triggers:\n"
        '  - type: cron\n'
        '    expression: "0 6 * * 1"\n'
        "    timezone: UTC\n"
        "database:\n"
        "  enabled: true\n"
        "outputs: []\n"
    )


def _write_template(templates_dir: Path) -> None:
    templates_dir.mkdir(parents=True, exist_ok=True)
    (templates_dir / "research.yaml").write_text(
        "name: research\n"
        "description: test template\n"
        "tools:\n"
        "  - web_search\n"
        "  - execute_sql\n"
        "model: test-model\n"
        "max_tokens: 1024\n"
        "resources:\n"
        "  max_search_calls_per_run: 10\n"
        "  max_fetch_calls_per_run: 5\n"
        "  max_sql_calls_per_run: 20\n"
        "system_prompt: You are a test agent.\n"
    )


# ── clarion health ──────────────────────────────────────────────────────


class TestHealthCommand:
    def test_health_missing_llm_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("LLM_BASE_URL", raising=False)
        monkeypatch.delenv("LLM_API_KEY", raising=False)
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 1
        assert "LLM_BASE_URL" in result.output

    def test_health_with_llm_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("LLM_API_KEY", "sk-test")
        result = runner.invoke(app, ["health"])
        assert "LLM:" in result.output
        assert "https://api.example.com/v1" in result.output

    def test_health_telegram_optional(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.setenv("LLM_BASE_URL", "https://api.example.com/v1")
        monkeypatch.setenv("LLM_API_KEY", "sk-test")
        result = runner.invoke(app, ["health"])
        assert "TELEGRAM_BOT_TOKEN not set" in result.output


# ── clarion register ────────────────────────────────────────────────────


class TestRegisterCommand:
    def test_register_valid_config(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "test-agent"
        _write_agent_yaml(agent_dir)
        _write_template(tmp_path / "templates")

        # Patch _find_repo_root so it finds our tmp_path
        with patch("clarion.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["register", str(agent_dir)])

        assert result.exit_code == 0
        assert "agent.yaml valid" in result.output
        assert "template: research" in result.output

    def test_register_invalid_config(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "bad-agent"
        agent_dir.mkdir(parents=True)
        # Write invalid agent.yaml (missing template)
        (agent_dir / "agent.yaml").write_text("meta:\n  name: Bad\n")

        with patch("clarion.cli._find_repo_root", return_value=tmp_path):
            _write_template(tmp_path / "templates")
            result = runner.invoke(app, ["register", str(agent_dir)])

        assert result.exit_code == 1

    def test_register_missing_agent_yaml(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "no-yaml"
        agent_dir.mkdir(parents=True)

        with patch("clarion.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["register", str(agent_dir)])

        assert result.exit_code == 1

    def test_register_shows_mission_status(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "test-agent"
        _write_agent_yaml(agent_dir)
        _write_template(tmp_path / "templates")

        # No mission file → should show warning
        with patch("clarion.cli._find_repo_root", return_value=tmp_path):
            with patch("clarion.cli._data_root", return_value=tmp_path / "data"):
                result = runner.invoke(app, ["register", str(agent_dir)])

        assert result.exit_code == 0
        assert "mission not found" in result.output


# ── clarion run ─────────────────────────────────────────────────────────


class TestRunCommand:
    def test_run_missing_agent_dir(self, tmp_path: Path) -> None:
        with patch("clarion.cli._find_repo_root", return_value=tmp_path):
            result = runner.invoke(app, ["run", "--agent", "nonexistent"])

        assert result.exit_code == 1
        assert "Fatal error" in result.output

    def test_run_missing_mission(self, tmp_path: Path) -> None:
        agent_dir = tmp_path / "agents" / "test-agent"
        _write_agent_yaml(agent_dir)
        _write_template(tmp_path / "templates")
        data_dir = tmp_path / "data"

        with (
            patch("clarion.cli._find_repo_root", return_value=tmp_path),
            patch("clarion.cli._data_root", return_value=data_dir),
        ):
            result = runner.invoke(app, ["run", "--agent", "test-agent"])

        assert result.exit_code == 1
        assert "Fatal error" in result.output

    def test_run_success(self, tmp_path: Path) -> None:
        """Test full run with mocked _run_agent coroutine."""
        success_run = _make_agent_run(status=RunStatus.SUCCESS)

        with patch("clarion.cli._run_agent", new_callable=AsyncMock, return_value=success_run):
            result = runner.invoke(app, ["run", "--agent", "test-agent"])

        assert result.exit_code == 0
        assert "success" in result.output

    def test_run_failed_exits_1(self, tmp_path: Path) -> None:
        """Test that a failed run returns exit code 1."""
        failed_run = _make_agent_run(
            status=RunStatus.FAILED,
            error="Resource limit exceeded",
        )

        with patch("clarion.cli._run_agent", new_callable=AsyncMock, return_value=failed_run):
            result = runner.invoke(app, ["run", "--agent", "test-agent"])

        assert result.exit_code == 1
        assert "failed" in result.output
        assert "Resource limit exceeded" in result.output

    def test_run_prints_tool_call_counts(self, tmp_path: Path) -> None:
        run_with_tools = _make_agent_run(
            status=RunStatus.SUCCESS,
            tool_call_counts={"web_search": 5, "execute_sql": 3},
            outputs_produced=["weekly-briefing"],
        )

        with patch("clarion.cli._run_agent", new_callable=AsyncMock, return_value=run_with_tools):
            result = runner.invoke(app, ["run", "--agent", "test-agent"])

        assert result.exit_code == 0
        assert "weekly-briefing" in result.output


# ── no-args shows help ──────────────────────────────────────────────────


class TestNoArgs:
    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        # Typer returns exit code 0 or 2 for no-args help depending on version
        assert result.exit_code in (0, 2)
        assert "Usage" in result.output or "usage" in result.output.lower()
