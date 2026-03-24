"""Tests for clarion.agent_config — layer 0."""

from __future__ import annotations

from pathlib import Path

import pytest

from clarion.agent_config import ConfigValidationError, load_agent_config
from clarion.boundary_validation import BoundaryValidationError
from clarion.models import TriggerType

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
    "timezone: UTC\n"
    "database:\n"
    "  enabled: true\n"
    "outputs: []\n"
)


# ── Valid loading ───────────────────────────────────────────────────────────


class TestLoadValidConfig:
    def test_loads_valid_agent_yaml(
        self, tmp_agent_dir: Path, templates_dir: Path
    ) -> None:
        (tmp_agent_dir / "agent.yaml").write_text(MINIMAL_AGENT_YAML)
        config = load_agent_config(tmp_agent_dir, "test-agent", templates_dir)

        assert config.agent_id == "test-agent"
        assert config.name == "Test Agent"
        assert config.description == "A test agent"
        assert config.owner == "test-owner"
        assert config.version == 1
        assert config.template == "research"
        assert len(config.triggers) == 1
        assert config.triggers[0].type == TriggerType.CRON
        assert config.triggers[0].expression == "0 */4 * * *"
        assert config.timezone == "UTC"
        assert config.database_enabled is True
        assert config.outputs == []
        assert config.tools == ["web_search", "execute_sql"]
        assert config.model == "test-model"
        assert config.max_tokens == 1024
        assert config.base_system_prompt == "You are a test agent."

    def test_agent_id_comes_from_parameter(
        self, tmp_agent_dir: Path, templates_dir: Path
    ) -> None:
        (tmp_agent_dir / "agent.yaml").write_text(MINIMAL_AGENT_YAML)
        config = load_agent_config(tmp_agent_dir, "my-custom-id", templates_dir)

        assert config.agent_id == "my-custom-id"
        assert config.name == "Test Agent"


# ── Resource overrides ──────────────────────────────────────────────────────


class TestResourceOverrides:
    def test_downward_override_accepted(
        self, tmp_agent_dir: Path, templates_dir: Path
    ) -> None:
        yaml_text = (
            MINIMAL_AGENT_YAML + "resources:\n" "  max_search_calls_per_run: 5\n"
        )
        (tmp_agent_dir / "agent.yaml").write_text(yaml_text)
        config = load_agent_config(tmp_agent_dir, "test-agent", templates_dir)

        assert config.resources.max_search_calls_per_run == 5

    def test_upward_override_rejected(
        self, tmp_agent_dir: Path, templates_dir: Path
    ) -> None:
        yaml_text = (
            MINIMAL_AGENT_YAML + "resources:\n" "  max_search_calls_per_run: 100\n"
        )
        (tmp_agent_dir / "agent.yaml").write_text(yaml_text)

        with pytest.raises(ConfigValidationError, match="exceeds template maximum"):
            load_agent_config(tmp_agent_dir, "test-agent", templates_dir)


# ── Error cases ─────────────────────────────────────────────────────────────


class TestConfigErrors:
    def test_missing_template_file(
        self, tmp_agent_dir: Path, templates_dir: Path
    ) -> None:
        yaml_text = "template: nonexistent\nmeta: {}\noutputs: []\n"
        (tmp_agent_dir / "agent.yaml").write_text(yaml_text)

        with pytest.raises(ConfigValidationError, match="not found"):
            load_agent_config(tmp_agent_dir, "test-agent", templates_dir)

    def test_missing_agent_yaml(self, tmp_agent_dir: Path, templates_dir: Path) -> None:
        with pytest.raises(ConfigValidationError, match="No agent.yaml"):
            load_agent_config(tmp_agent_dir, "test-agent", templates_dir)

    def test_invalid_cron_expression(
        self, tmp_agent_dir: Path, templates_dir: Path
    ) -> None:
        yaml_text = (
            "template: research\n"
            "meta: {}\n"
            "triggers:\n"
            "  - type: cron\n"
            '    expression: "not a cron"\n'
            "outputs: []\n"
        )
        (tmp_agent_dir / "agent.yaml").write_text(yaml_text)

        with pytest.raises(ConfigValidationError, match="Invalid cron"):
            load_agent_config(tmp_agent_dir, "test-agent", templates_dir)

    def test_invalid_timezone_rejected(
        self, tmp_agent_dir: Path, templates_dir: Path
    ) -> None:
        yaml_text = (
            "template: research\n"
            "meta: {}\n"
            "timezone: Not/A/Timezone\n"
            "triggers:\n"
            "  - type: cron\n"
            '    expression: "0 */4 * * *"\n'
            "outputs: []\n"
        )
        (tmp_agent_dir / "agent.yaml").write_text(yaml_text)

        with pytest.raises(ConfigValidationError, match="Invalid timezone"):
            load_agent_config(tmp_agent_dir, "test-agent", templates_dir)

    def test_meta_not_mapping_rejected(
        self, tmp_agent_dir: Path, templates_dir: Path
    ) -> None:
        yaml_text = "template: research\nmeta: not-a-mapping\noutputs: []\n"
        (tmp_agent_dir / "agent.yaml").write_text(yaml_text)

        with pytest.raises(ConfigValidationError, match="'meta' must be a mapping"):
            load_agent_config(tmp_agent_dir, "test-agent", templates_dir)

    def test_duplicate_output_names_rejected(
        self, tmp_agent_dir: Path, templates_dir: Path
    ) -> None:
        yaml_text = (
            "template: research\n"
            "meta: {}\n"
            "outputs:\n"
            "  - name: digest\n"
            "    trigger: scheduled\n"
            "    type: telegram\n"
            "    destination: '123'\n"
            "  - name: digest\n"
            "    trigger: agent_decides\n"
            "    type: telegram\n"
            "    destination: '456'\n"
        )
        (tmp_agent_dir / "agent.yaml").write_text(yaml_text)

        with pytest.raises(ConfigValidationError, match="Duplicate output name"):
            load_agent_config(tmp_agent_dir, "test-agent", templates_dir)


# ── Env var expansion in outputs ────────────────────────────────────────────


class TestOutputEnvVarExpansion:
    def test_env_var_expanded_in_destination(
        self,
        tmp_agent_dir: Path,
        templates_dir: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
        yaml_text = (
            "template: research\n"
            "meta: {}\n"
            "outputs:\n"
            "  - name: digest\n"
            "    trigger: scheduled\n"
            "    type: telegram\n"
            "    destination: '${TELEGRAM_CHAT_ID}'\n"
        )
        (tmp_agent_dir / "agent.yaml").write_text(yaml_text)
        config = load_agent_config(tmp_agent_dir, "test-agent", templates_dir)

        assert config.outputs[0].destination == "12345"

    def test_missing_env_var_raises(
        self, tmp_agent_dir: Path, templates_dir: Path
    ) -> None:
        yaml_text = (
            "template: research\n"
            "meta: {}\n"
            "outputs:\n"
            "  - name: digest\n"
            "    trigger: scheduled\n"
            "    type: telegram\n"
            "    destination: '${MISSING_VAR_FOR_TEST_XYZ}'\n"
        )
        (tmp_agent_dir / "agent.yaml").write_text(yaml_text)

        with pytest.raises(BoundaryValidationError, match="not set"):
            load_agent_config(tmp_agent_dir, "test-agent", templates_dir)
