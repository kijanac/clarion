"""Tests for clarion.agent_registry — layer 3."""

from __future__ import annotations

from pathlib import Path

from clarion.agent_registry import AgentRegistry

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

INVALID_AGENT_YAML = "template: nonexistent\nmeta: {}\noutputs: []\n"


def _setup_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Create agents/, templates/, and data/ directories."""
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
    return agents_dir, templates_dir, data_root


# ── Scan finds valid agents ─────────────────────────────────────────────


class TestScan:
    def test_scan_finds_valid_agents(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_dirs(tmp_path)
        (agents_dir / "agent-a").mkdir()
        (agents_dir / "agent-a" / "agent.yaml").write_text(MINIMAL_AGENT_YAML)
        (agents_dir / "agent-b").mkdir()
        (agents_dir / "agent-b" / "agent.yaml").write_text(MINIMAL_AGENT_YAML)

        registry = AgentRegistry(agents_dir, templates_dir, data_root)
        registry.scan()

        assert len(registry.all_agents()) == 2
        assert registry.get("agent-a") is not None
        assert registry.get("agent-b") is not None

    def test_scan_skips_invalid_agents(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_dirs(tmp_path)
        (agents_dir / "valid").mkdir()
        (agents_dir / "valid" / "agent.yaml").write_text(MINIMAL_AGENT_YAML)
        (agents_dir / "invalid").mkdir()
        (agents_dir / "invalid" / "agent.yaml").write_text(INVALID_AGENT_YAML)

        registry = AgentRegistry(agents_dir, templates_dir, data_root)
        registry.scan()

        assert len(registry.all_agents()) == 1
        assert registry.get("valid") is not None
        assert registry.get("invalid") is None

    def test_scan_skips_dirs_without_agent_yaml(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_dirs(tmp_path)
        (agents_dir / "no-yaml").mkdir()

        registry = AgentRegistry(agents_dir, templates_dir, data_root)
        registry.scan()

        assert len(registry.all_agents()) == 0


# ── Reload ──────────────────────────────────────────────────────────────


class TestReload:
    def test_reload_agent_with_valid_edit(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_dirs(tmp_path)
        (agents_dir / "agent-a").mkdir()
        (agents_dir / "agent-a" / "agent.yaml").write_text(MINIMAL_AGENT_YAML)

        registry = AgentRegistry(agents_dir, templates_dir, data_root)
        registry.scan()

        assert registry.get("agent-a").name == "Test Agent"

        # Update to a new valid config
        updated = MINIMAL_AGENT_YAML.replace("Test Agent", "Updated Agent")
        (agents_dir / "agent-a" / "agent.yaml").write_text(updated)

        config = registry.reload_agent("agent-a")
        assert config is not None
        assert config.name == "Updated Agent"
        assert registry.get("agent-a").name == "Updated Agent"

    def test_reload_agent_with_invalid_edit_preserves_old(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_dirs(tmp_path)
        (agents_dir / "agent-a").mkdir()
        (agents_dir / "agent-a" / "agent.yaml").write_text(MINIMAL_AGENT_YAML)

        registry = AgentRegistry(agents_dir, templates_dir, data_root)
        registry.scan()

        original_config = registry.get("agent-a")
        assert original_config is not None

        # Write an invalid config
        (agents_dir / "agent-a" / "agent.yaml").write_text(INVALID_AGENT_YAML)

        config = registry.reload_agent("agent-a")
        assert config is not None
        assert config.name == "Test Agent"  # old config preserved


# ── Remove ──────────────────────────────────────────────────────────────


class TestRemove:
    def test_remove_agent(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_dirs(tmp_path)
        (agents_dir / "agent-a").mkdir()
        (agents_dir / "agent-a" / "agent.yaml").write_text(MINIMAL_AGENT_YAML)

        registry = AgentRegistry(agents_dir, templates_dir, data_root)
        registry.scan()

        assert registry.get("agent-a") is not None
        registry.remove_agent("agent-a")
        assert registry.get("agent-a") is None


# ── Mission reload ──────────────────────────────────────────────────────


class TestMissionReload:
    def test_reload_mission(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_dirs(tmp_path)
        workspace = data_root / "agents" / "agent-a"
        workspace.mkdir(parents=True)
        (workspace / "mission.md").write_text("# Mission\nDo things.")

        registry = AgentRegistry(agents_dir, templates_dir, data_root)
        mission = registry.reload_mission("agent-a")
        assert mission == "# Mission\nDo things."

    def test_reload_mission_missing(self, tmp_path: Path) -> None:
        agents_dir, templates_dir, data_root = _setup_dirs(tmp_path)
        registry = AgentRegistry(agents_dir, templates_dir, data_root)
        assert registry.reload_mission("nonexistent") is None
