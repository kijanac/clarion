"""Tests for clarion.tool_registry — layer 1 tool definitions."""

from __future__ import annotations

from clarion.tool_registry import (
    TOOL_REGISTRY,
    ToolExecutionPolicy,
    build_tool_instructions,
    get_execution_policy,
    get_spec,
    get_tool_schemas,
)

EXPECTED_TOOL_NAMES = [
    "current_datetime",
    "web_search",
    "web_fetch",
    "web_extract",
    "deep_research",
    "execute_sql",
    "list_databases",
    "cron",
    "write_file",
    "deliver_output",
]


# ── Registry completeness ───────────────────────────────────────────────────


class TestRegistryCompleteness:
    def test_contains_all_expected_tools(self) -> None:
        names = [spec.name for spec in TOOL_REGISTRY]
        assert names == EXPECTED_TOOL_NAMES

    def test_registry_has_ten_tools(self) -> None:
        assert len(TOOL_REGISTRY) == 10


# ── OpenAI schema structure ─────────────────────────────────────────────────


class TestSchemaStructure:
    def test_all_specs_have_valid_openai_schema(self) -> None:
        for spec in TOOL_REGISTRY:
            schema = spec.tool_schema
            assert schema["type"] == "function", f"{spec.name}: missing type=function"
            fn = schema["function"]
            assert "name" in fn, f"{spec.name}: missing function.name"
            assert fn["name"] == spec.name, f"{spec.name}: schema name mismatch"
            assert "parameters" in fn, f"{spec.name}: missing function.parameters"


# ── get_spec ────────────────────────────────────────────────────────────────


class TestGetSpec:
    def test_returns_none_for_unknown_tool(self) -> None:
        assert get_spec("nonexistent_tool") is None

    def test_returns_correct_spec_for_known_tool(self) -> None:
        spec = get_spec("web_search")
        assert spec is not None
        assert spec.name == "web_search"
        assert spec.tool_schema["function"]["name"] == "web_search"


# ── get_tool_schemas ────────────────────────────────────────────────────────


class TestGetToolSchemas:
    def test_filters_to_requested_tools(self) -> None:
        subset = ["web_search", "cron"]
        schemas = get_tool_schemas(subset)
        assert len(schemas) == 2
        returned_names = {s["function"]["name"] for s in schemas}
        assert returned_names == {"web_search", "cron"}

    def test_ignores_unknown_tool_names(self) -> None:
        schemas = get_tool_schemas(["web_search", "bogus"])
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "web_search"

    def test_empty_list_returns_empty(self) -> None:
        assert get_tool_schemas([]) == []


# ── get_execution_policy ────────────────────────────────────────────────────


class TestGetExecutionPolicy:
    def test_returns_default_for_unknown_tool(self) -> None:
        policy = get_execution_policy("nonexistent_tool")
        assert policy == ToolExecutionPolicy()

    def test_returns_spec_policy_for_known_tool(self) -> None:
        policy = get_execution_policy("cron")
        assert policy.side_effecting is True


# ── build_tool_instructions ─────────────────────────────────────────────────


class TestBuildToolInstructions:
    def test_includes_hints_only_for_listed_tools(self) -> None:
        instructions = build_tool_instructions(["web_search"])
        assert "web_search" in instructions
        assert "cron" not in instructions

    def test_always_includes_response_behaviour(self) -> None:
        instructions = build_tool_instructions(["web_search"])
        assert "Response behavior for tool loops" in instructions

    def test_omits_empty_hints(self) -> None:
        instructions = build_tool_instructions(["execute_sql"])
        assert get_spec("execute_sql") is not None
        assert get_spec("execute_sql").prompt_hint.strip() == ""
        assert "execute_sql" not in instructions
