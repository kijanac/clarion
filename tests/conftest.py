"""Shared fixtures for Clarion tests."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Create a temporary agent workspace directory."""
    workspace = tmp_path / "data" / "agents" / "test-agent"
    workspace.mkdir(parents=True)
    (workspace / "databases").mkdir()
    (workspace / "cron").mkdir()
    (workspace / "runs").mkdir()
    (workspace / "cache").mkdir()
    return workspace


@pytest.fixture
def tmp_agent_dir(tmp_path: Path) -> Path:
    """Create a temporary agent config directory with a minimal agent.yaml."""
    agent_dir = tmp_path / "agents" / "test-agent"
    agent_dir.mkdir(parents=True)
    return agent_dir


@pytest.fixture
def templates_dir(tmp_path: Path) -> Path:
    """Create a temporary templates directory with a minimal research template."""
    tpl_dir = tmp_path / "templates"
    tpl_dir.mkdir()
    (tpl_dir / "research.yaml").write_text(
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
    return tpl_dir
