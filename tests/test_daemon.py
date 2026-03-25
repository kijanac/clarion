"""Tests for clarion.daemon — layer 3."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from clarion.agent_state import record_run
from clarion.daemon import Daemon
from clarion.models import AgentRun, RunStatus

MINIMAL_AGENT_YAML = (
    "template: research\n"
    "meta:\n"
    "  name: Test Agent\n"
    "  description: A test agent\n"
    "  owner: test-owner\n"
    "  version: 1\n"
    "triggers:\n"
    '  - type: cron\n'
    '    expression: "0 */4 * * *"\n'
    "    timezone: UTC\n"
    "database:\n"
    "  enabled: true\n"
    "outputs: []\n"
)


def _setup_env(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Set up agents dir, templates dir, data root with one valid agent."""
    agents_dir = tmp_path / "agents"
    agents_dir.mkdir()
    templates_dir = tmp_path / "templates"
    templates_dir.mkdir()
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
    data_root = tmp_path / "data"
    data_root.mkdir()

    # Create one valid agent
    (agents_dir / "agent-a").mkdir()
    (agents_dir / "agent-a" / "agent.yaml").write_text(MINIMAL_AGENT_YAML)

    # Create workspace and mission
    workspace = data_root / "agents" / "agent-a"
    workspace.mkdir(parents=True)
    (workspace / "runs").mkdir()
    (workspace / "cron").mkdir()
    (workspace / "mission.md").write_text("# Mission\nTest mission.")

    return agents_dir, templates_dir, data_root


# ── Startup scan ────────────────────────────────────────────────────────


class TestStartup:
    async def test_startup_registers_agents(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_env(tmp_path)

        d = Daemon(
            agents_dir=agents_dir,
            templates_dir=templates_dir,
            data_root=data_root,
        )

        # Start and immediately request shutdown
        async def _start_and_stop() -> None:
            task = asyncio.create_task(d.start())
            await asyncio.sleep(0.1)
            await d.shutdown()
            await task

        await _start_and_stop()

        assert d._registry.get("agent-a") is not None


# ── Run budget enforcement ──────────────────────────────────────────────


class TestRunBudget:
    async def test_max_runs_per_day_enforced(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_env(tmp_path)

        d = Daemon(
            agents_dir=agents_dir,
            templates_dir=templates_dir,
            data_root=data_root,
        )
        d._registry.scan()

        workspace = data_root / "agents" / "agent-a"

        # Fill up the daily budget (default is 12)
        config = d._registry.get("agent-a")
        for i in range(config.resources.max_runs_per_day):
            run = AgentRun(
                run_id=f"run_{i:04d}",
                agent_id="agent-a",
                started_at=datetime.now(UTC),
                status=RunStatus.SUCCESS,
                trigger="scheduled",
            )
            record_run(run, workspace)

        assert d._can_run("agent-a") is False

    async def test_can_run_when_budget_available(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_env(tmp_path)

        d = Daemon(
            agents_dir=agents_dir,
            templates_dir=templates_dir,
            data_root=data_root,
        )
        d._registry.scan()

        assert d._can_run("agent-a") is True

    async def test_can_run_unknown_agent(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_env(tmp_path)

        d = Daemon(
            agents_dir=agents_dir,
            templates_dir=templates_dir,
            data_root=data_root,
        )
        d._registry.scan()

        assert d._can_run("nonexistent") is False


# ── Config change handling ──────────────────────────────────────────────


class TestConfigChange:
    async def test_config_change_reloads_agent(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_env(tmp_path)

        d = Daemon(
            agents_dir=agents_dir,
            templates_dir=templates_dir,
            data_root=data_root,
        )
        d._registry.scan()

        assert d._registry.get("agent-a").name == "Test Agent"

        # Update config
        updated = MINIMAL_AGENT_YAML.replace("Test Agent", "Updated Agent")
        (agents_dir / "agent-a" / "agent.yaml").write_text(updated)
        d._handle_config_change("agent-a")

        assert d._registry.get("agent-a").name == "Updated Agent"

    async def test_invalid_config_change_preserves_old(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_env(tmp_path)

        d = Daemon(
            agents_dir=agents_dir,
            templates_dir=templates_dir,
            data_root=data_root,
        )
        d._registry.scan()

        # Write invalid config
        (agents_dir / "agent-a" / "agent.yaml").write_text(
            "template: nonexistent\nmeta: {}\noutputs: []\n"
        )
        d._handle_config_change("agent-a")

        assert d._registry.get("agent-a").name == "Test Agent"


# ── Agent removal ───────────────────────────────────────────────────────


class TestAgentRemoval:
    async def test_unregister_removes_agent(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_env(tmp_path)

        d = Daemon(
            agents_dir=agents_dir,
            templates_dir=templates_dir,
            data_root=data_root,
        )
        d._registry.scan()
        d._register_agent("agent-a", d._registry.get("agent-a"))

        d._unregister_agent("agent-a")

        assert d._registry.get("agent-a") is None


# ── Graceful shutdown ───────────────────────────────────────────────────


class TestGracefulShutdown:
    async def test_shutdown_completes(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_env(tmp_path)

        d = Daemon(
            agents_dir=agents_dir,
            templates_dir=templates_dir,
            data_root=data_root,
        )

        async def _start_and_stop() -> None:
            task = asyncio.create_task(d.start())
            await asyncio.sleep(0.1)
            await d.shutdown()
            await task

        # Should complete without hanging
        await asyncio.wait_for(_start_and_stop(), timeout=5.0)


# ── Fire run ────────────────────────────────────────────────────────────


class TestFireRun:
    async def test_fire_skip_unregistered(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_env(tmp_path)

        d = Daemon(
            agents_dir=agents_dir,
            templates_dir=templates_dir,
            data_root=data_root,
        )
        # Don't scan — agent not registered
        await d._fire_run("nonexistent")
        # Should not raise, just skip

    async def test_fire_skip_no_mission(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_env(tmp_path)

        d = Daemon(
            agents_dir=agents_dir,
            templates_dir=templates_dir,
            data_root=data_root,
        )
        d._registry.scan()

        # Remove mission file
        mission = data_root / "agents" / "agent-a" / "mission.md"
        mission.unlink()

        await d._fire_run("agent-a")
        # Should not raise, just skip
