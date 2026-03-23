"""Tests for clarion.prompt_assembly — system prompt construction."""

from __future__ import annotations

from datetime import UTC, datetime

from clarion.models import (
    AgentConfig,
    OutputDefinition,
    OutputTrigger,
    OutputType,
    ResourceEnvelope,
    RunContext,
)
from clarion.prompt_assembly import build_system_prompt

# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_config(**overrides: object) -> AgentConfig:
    defaults: dict[str, object] = {
        "agent_id": "test-agent",
        "name": "Test Agent",
        "description": "test",
        "owner": "test",
        "version": 1,
        "template": "research",
        "schedule_cron": "0 6 * * 1",
        "schedule_timezone": "UTC",
        "outputs": [],
        "database_enabled": True,
        "resources": ResourceEnvelope(),
        "tools": ["web_search", "execute_sql"],
        "base_system_prompt": "You are a research agent.",
    }
    return AgentConfig(**(defaults | overrides))


def _make_context(config: AgentConfig | None = None, **overrides: object) -> RunContext:
    if config is None:
        config = _make_config()
    defaults: dict[str, object] = {
        "agent_id": "test-agent",
        "run_id": "run_abc123",
        "config": config,
        "mission_md": "# Test Mission\nDo research.",
        "workspace_root": "/tmp/test",
        "trigger": "manual",
        "current_datetime": datetime(2026, 3, 22, 14, 30, 0, tzinfo=UTC),
    }
    return RunContext(**(defaults | overrides))


# ── Tests ───────────────────────────────────────────────────────────────────


class TestFullPrompt:
    def test_all_sections_present(self) -> None:
        ctx = _make_context()
        prompt = build_system_prompt(ctx)

        assert "You are a research agent." in prompt
        assert "## Your Mission" in prompt
        assert "Test Mission" in prompt
        assert "## This Run" in prompt
        assert "run_abc123" in prompt
        assert "## Resource Limits This Run" in prompt
        assert "## Tool Usage" in prompt

    def test_run_metadata_in_prompt(self) -> None:
        ctx = _make_context()
        prompt = build_system_prompt(ctx)

        assert "Triggered by: manual" in prompt
        assert "Timezone: UTC" in prompt
        assert "March 22, 2026" in prompt


class TestEmptyMission:
    def test_mission_section_omitted_when_empty(self) -> None:
        ctx = _make_context(mission_md="")
        prompt = build_system_prompt(ctx)

        assert "## Your Mission" not in prompt
        assert "## This Run" in prompt

    def test_mission_section_omitted_when_whitespace(self) -> None:
        ctx = _make_context(mission_md="   \n  ")
        prompt = build_system_prompt(ctx)

        assert "## Your Mission" not in prompt


class TestEmptyBasePrompt:
    def test_base_prompt_omitted_when_empty(self) -> None:
        config = _make_config(base_system_prompt="")
        ctx = _make_context(config=config)
        prompt = build_system_prompt(ctx)

        assert "You are a research agent" not in prompt
        assert "## This Run" in prompt


class TestOutputDefinitions:
    def test_scheduled_outputs_rendered(self) -> None:
        config = _make_config(
            outputs=[
                OutputDefinition(
                    name="weekly-briefing",
                    description="A weekly summary",
                    trigger=OutputTrigger.SCHEDULED,
                    type=OutputType.TELEGRAM,
                    destination="123",
                    format="Short summary.",
                ),
            ],
        )
        ctx = _make_context(config=config)
        prompt = build_system_prompt(ctx)

        assert "## Outputs Due This Run" in prompt
        assert "### weekly-briefing" in prompt
        assert "A weekly summary" in prompt
        assert "Format instructions:\nShort summary." in prompt

    def test_optional_outputs_rendered(self) -> None:
        config = _make_config(
            outputs=[
                OutputDefinition(
                    name="alert",
                    description="Breaking news alert",
                    trigger=OutputTrigger.AGENT_DECIDES,
                    type=OutputType.TELEGRAM,
                    destination="456",
                ),
            ],
        )
        ctx = _make_context(config=config)
        prompt = build_system_prompt(ctx)

        assert "## Outputs You Can Trigger If Warranted" in prompt
        assert "### alert" in prompt
        assert "Breaking news alert" in prompt

    def test_scheduled_and_optional_both_rendered(self) -> None:
        config = _make_config(
            outputs=[
                OutputDefinition(
                    name="briefing",
                    trigger=OutputTrigger.SCHEDULED,
                    type=OutputType.TELEGRAM,
                    destination="1",
                ),
                OutputDefinition(
                    name="alert",
                    trigger=OutputTrigger.AGENT_DECIDES,
                    type=OutputType.TELEGRAM,
                    destination="2",
                ),
            ],
        )
        ctx = _make_context(config=config)
        prompt = build_system_prompt(ctx)

        assert "## Outputs Due This Run" in prompt
        assert "## Outputs You Can Trigger If Warranted" in prompt

    def test_no_outputs_sections_when_none(self) -> None:
        config = _make_config(outputs=[])
        ctx = _make_context(config=config)
        prompt = build_system_prompt(ctx)

        assert "Outputs Due" not in prompt
        assert "Outputs You Can Trigger" not in prompt

    def test_destination_not_leaked(self) -> None:
        config = _make_config(
            outputs=[
                OutputDefinition(
                    name="briefing",
                    trigger=OutputTrigger.SCHEDULED,
                    type=OutputType.TELEGRAM,
                    destination="secret-chat-id-123",
                ),
            ],
        )
        ctx = _make_context(config=config)
        prompt = build_system_prompt(ctx)

        assert "secret-chat-id-123" not in prompt
        assert "telegram" not in prompt.lower().replace("## outputs", "")


class TestResourceLimits:
    def test_resource_limits_present(self) -> None:
        ctx = _make_context()
        prompt = build_system_prompt(ctx)

        assert "Search calls: max 30" in prompt
        assert "Fetch calls: max 15" in prompt
        assert "Deep research calls: max 3" in prompt
        assert "SQL calls: max 50" in prompt
        assert "Run timeout: 600s" in prompt

    def test_custom_resource_limits(self) -> None:
        config = _make_config(
            resources=ResourceEnvelope(
                max_search_calls_per_run=5,
                max_fetch_calls_per_run=2,
                run_timeout_seconds=120,
            ),
        )
        ctx = _make_context(config=config)
        prompt = build_system_prompt(ctx)

        assert "Search calls: max 5" in prompt
        assert "Fetch calls: max 2" in prompt
        assert "Run timeout: 120s" in prompt


class TestToolInstructions:
    def test_tool_instructions_filtered(self) -> None:
        config = _make_config(tools=["web_search"])
        ctx = _make_context(config=config)
        prompt = build_system_prompt(ctx)

        assert "web_search" in prompt
        # execute_sql not in tool list, its hint should be absent
        assert "execute_sql" not in prompt.split("## Tool Usage")[1]

    def test_no_tools_still_has_response_behaviour(self) -> None:
        config = _make_config(tools=[])
        ctx = _make_context(config=config)
        prompt = build_system_prompt(ctx)

        assert "Response behavior" in prompt
