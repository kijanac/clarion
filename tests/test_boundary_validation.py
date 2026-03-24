"""Tests for clarion.boundary_validation — layer 0."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from clarion.boundary_validation import (
    MAX_FETCH_CONTENT_LEN,
    MAX_QUERY_LEN,
    MAX_SQL_LEN,
    MAX_URL_LEN,
    BoundaryValidationError,
    expand_env_vars,
    validate_agent_path,
    validate_sql,
    validate_tool_result,
    validate_url,
)
from clarion.tools import build_handler_registry
from clarion.tools.base import ToolContext


# ── Path validation ────────────────────────────────────────────────────────


class TestValidateAgentPath:
    def test_valid_path(self, tmp_path: Path) -> None:
        result = validate_agent_path("agent-1", "data/file.txt", tmp_path)
        assert result == (tmp_path / "data" / "file.txt").resolve()

    def test_traversal_attack_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(BoundaryValidationError, match="escapes agent workspace"):
            validate_agent_path("agent-1", "../../etc/passwd", tmp_path)

    def test_dot_dot_in_middle_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(BoundaryValidationError, match="escapes agent workspace"):
            validate_agent_path("agent-1", "subdir/../../etc/passwd", tmp_path)

    def test_absolute_path_outside_rejected(self, tmp_path: Path) -> None:
        with pytest.raises(BoundaryValidationError, match="escapes agent workspace"):
            validate_agent_path("agent-1", "/etc/passwd", tmp_path)

    def test_nested_valid_path(self, tmp_path: Path) -> None:
        result = validate_agent_path("agent-1", "a/b/c/file.txt", tmp_path)
        assert str(result).startswith(str(tmp_path.resolve()))


# ── SQL validation ──────────────────────────────────────────────────────────


class TestValidateSql:
    def test_normal_select_passes(self) -> None:
        assert validate_sql("SELECT * FROM users") == "SELECT * FROM users"

    def test_insert_passes(self) -> None:
        sql = "INSERT INTO events (name) VALUES ('test')"
        assert validate_sql(sql) == sql

    def test_create_table_passes(self) -> None:
        sql = "CREATE TABLE IF NOT EXISTS items (id INTEGER PRIMARY KEY)"
        assert validate_sql(sql) == sql

    def test_update_passes(self) -> None:
        sql = "UPDATE users SET name = 'new' WHERE id = 1"
        assert validate_sql(sql) == sql

    def test_pragma_table_info_passes(self) -> None:
        assert validate_sql("PRAGMA table_info(users)") == "PRAGMA table_info(users)"

    def test_pragma_table_list_passes(self) -> None:
        assert validate_sql("PRAGMA table_list") == "PRAGMA table_list"

    def test_attach_blocked(self) -> None:
        with pytest.raises(BoundaryValidationError, match="blocked pattern"):
            validate_sql("ATTACH DATABASE '/etc/passwd' AS stolen")

    def test_load_extension_blocked(self) -> None:
        with pytest.raises(BoundaryValidationError, match="blocked pattern"):
            validate_sql("SELECT LOAD_EXTENSION('/tmp/evil.so')")

    def test_dangerous_pragma_blocked(self) -> None:
        with pytest.raises(BoundaryValidationError, match="blocked pattern"):
            validate_sql("PRAGMA journal_mode = WAL")

    def test_exceeds_max_length(self) -> None:
        sql = "SELECT " + "x" * MAX_SQL_LEN
        with pytest.raises(BoundaryValidationError, match="maximum length"):
            validate_sql(sql)


# ── URL validation ──────────────────────────────────────────────────────────


class TestValidateUrl:
    async def test_valid_https_url(self) -> None:
        url = "https://example.com/page"
        with patch("clarion.boundary_validation.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 0)),
            ]
            assert await validate_url(url) == url

    async def test_valid_http_url(self) -> None:
        url = "http://example.com"
        with patch("clarion.boundary_validation.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("93.184.216.34", 0)),
            ]
            assert await validate_url(url) == url

    async def test_empty_url_rejected(self) -> None:
        with pytest.raises(BoundaryValidationError, match="must not be empty"):
            await validate_url("")

    async def test_invalid_scheme_rejected(self) -> None:
        with pytest.raises(BoundaryValidationError, match="http or https"):
            await validate_url("ftp://example.com")

    async def test_too_long_rejected(self) -> None:
        url = "https://example.com/" + "a" * MAX_URL_LEN
        with pytest.raises(BoundaryValidationError, match="maximum length"):
            await validate_url(url)

    async def test_private_ip_127_rejected(self) -> None:
        with patch("clarion.boundary_validation.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("127.0.0.1", 0)),
            ]
            with pytest.raises(BoundaryValidationError, match="non-global IP"):
                await validate_url("https://localhost/secret")

    async def test_private_ip_192_168_rejected(self) -> None:
        with patch("clarion.boundary_validation.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [
                (2, 1, 6, "", ("192.168.1.1", 0)),
            ]
            with pytest.raises(BoundaryValidationError, match="non-global IP"):
                await validate_url("https://internal.corp/admin")

    async def test_unresolvable_host_rejected(self) -> None:
        with patch("clarion.boundary_validation.socket.getaddrinfo") as mock_gai:
            mock_gai.side_effect = OSError("Name resolution failed")
            with pytest.raises(BoundaryValidationError, match="Cannot resolve"):
                await validate_url("https://nonexistent.invalid/page")


# ── Env var expansion ───────────────────────────────────────────────────────


class TestExpandEnvVars:
    def test_valid_var_expanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("MY_VAR", "hello")
        assert expand_env_vars("prefix-${MY_VAR}-suffix") == "prefix-hello-suffix"

    def test_multiple_vars_expanded(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("A", "1")
        monkeypatch.setenv("B", "2")
        assert expand_env_vars("${A}+${B}") == "1+2"

    def test_missing_var_raises(self) -> None:
        with pytest.raises(BoundaryValidationError, match="not set"):
            expand_env_vars("${DEFINITELY_NOT_SET_VAR_12345}")

    def test_no_vars_returns_unchanged(self) -> None:
        assert expand_env_vars("plain string") == "plain string"

    def test_empty_string(self) -> None:
        assert expand_env_vars("") == ""


# ── Handler validation ──────────────────────────────────────────────────────


def _make_ctx(tmp_path: Path | None = None) -> ToolContext:
    """Build a minimal ToolContext for validation tests."""
    from unittest.mock import MagicMock

    return ToolContext(
        workspace_root=tmp_path or Path("/tmp/fake"),
        agent_id="test-agent",
        agent_config=MagicMock(),
        delivery_adapters={},
        fetch_cache=None,
        timezone="UTC",
        correlation_id="test-corr",
    )


class TestHandlerValidation:
    async def test_web_search_valid(self) -> None:
        args = {"query": "test query"}
        handler = build_handler_registry()["web_search"]
        assert await handler.validate(args, _make_ctx()) == args

    async def test_web_search_too_long(self) -> None:
        handler = build_handler_registry()["web_search"]
        with pytest.raises(BoundaryValidationError, match="maximum length"):
            await handler.validate({"query": "x" * (MAX_QUERY_LEN + 1)}, _make_ctx())

    async def test_deep_research_valid(self) -> None:
        args = {"question": "research topic"}
        handler = build_handler_registry()["deep_research"]
        assert await handler.validate(args, _make_ctx()) == args

    async def test_deep_research_too_long(self) -> None:
        handler = build_handler_registry()["deep_research"]
        with pytest.raises(BoundaryValidationError, match="maximum length"):
            await handler.validate({"question": "x" * (MAX_QUERY_LEN + 1)}, _make_ctx())

    async def test_execute_sql_valid(self) -> None:
        args = {"sql": "SELECT 1"}
        handler = build_handler_registry()["execute_sql"]
        assert await handler.validate(args, _make_ctx()) == args

    async def test_execute_sql_blocked(self) -> None:
        handler = build_handler_registry()["execute_sql"]
        with pytest.raises(BoundaryValidationError, match="blocked pattern"):
            await handler.validate({"sql": "ATTACH DATABASE 'x' AS y"}, _make_ctx())

    async def test_write_file_valid(self, tmp_path: Path) -> None:
        args = {"path": "data.txt", "content": "hello"}
        handler = build_handler_registry()["write_file"]
        result = await handler.validate(args, _make_ctx(tmp_path))
        assert result == args

    async def test_write_file_traversal(self, tmp_path: Path) -> None:
        handler = build_handler_registry()["write_file"]
        with pytest.raises(BoundaryValidationError, match="escapes"):
            await handler.validate({"path": "../../etc/passwd"}, _make_ctx(tmp_path))

    async def test_deliver_output_valid(self) -> None:
        args = {"output_name": "digest", "content": "hello"}
        handler = build_handler_registry()["deliver_output"]
        assert await handler.validate(args, _make_ctx()) == args

    async def test_deliver_output_non_string_name(self) -> None:
        handler = build_handler_registry()["deliver_output"]
        with pytest.raises(BoundaryValidationError, match="output_name must be a string"):
            await handler.validate({"output_name": 123, "content": "x"}, _make_ctx())

    async def test_deliver_output_content_too_large(self) -> None:
        handler = build_handler_registry()["deliver_output"]
        with pytest.raises(BoundaryValidationError, match="maximum length"):
            await handler.validate(
                {"output_name": "big", "content": "x" * (MAX_FETCH_CONTENT_LEN + 1)},
                _make_ctx(),
            )

    async def test_passthrough_tools(self) -> None:
        for tool in ("current_datetime", "list_databases", "cron"):
            handler = build_handler_registry()[tool]
            assert await handler.validate({}, _make_ctx()) == {}

    async def test_web_fetch_delegates_to_url_validation(self) -> None:
        handler = build_handler_registry()["web_fetch"]
        with pytest.raises(BoundaryValidationError, match="must not be empty"):
            await handler.validate({"url": ""}, _make_ctx())

    async def test_web_extract_delegates_to_url_validation(self) -> None:
        handler = build_handler_registry()["web_extract"]
        with pytest.raises(BoundaryValidationError, match="must not be empty"):
            await handler.validate({"url": ""}, _make_ctx())

    async def test_web_fetch_invalid_mode(self) -> None:
        handler = build_handler_registry()["web_fetch"]
        with patch("clarion.boundary_validation.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
            with pytest.raises(BoundaryValidationError, match="Invalid fetch mode"):
                await handler.validate(
                    {"url": "https://example.com", "mode": "bad"}, _make_ctx()
                )

    async def test_web_fetch_valid_mode(self) -> None:
        handler = build_handler_registry()["web_fetch"]
        with patch("clarion.boundary_validation.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
            result = await handler.validate(
                {"url": "https://example.com", "mode": "stealth"}, _make_ctx()
            )
            assert result["mode"] == "stealth"

    async def test_web_extract_invalid_selector_type(self) -> None:
        handler = build_handler_registry()["web_extract"]
        with patch("clarion.boundary_validation.socket.getaddrinfo") as mock_gai:
            mock_gai.return_value = [(2, 1, 6, "", ("93.184.216.34", 0))]
            with pytest.raises(BoundaryValidationError, match="Invalid selector_type"):
                await handler.validate(
                    {"url": "https://example.com", "selector": "div", "selector_type": "bad"},
                    _make_ctx(),
                )


# ── Tool result validation ──────────────────────────────────────────────────


class TestValidateToolResult:
    def test_short_result_unchanged(self) -> None:
        assert validate_tool_result("short") == "short"

    def test_result_at_limit_unchanged(self) -> None:
        text = "x" * MAX_FETCH_CONTENT_LEN
        assert validate_tool_result(text) == text

    def test_oversized_result_truncated(self) -> None:
        text = "x" * (MAX_FETCH_CONTENT_LEN + 100)
        result = validate_tool_result(text)
        assert len(result) == MAX_FETCH_CONTENT_LEN

    def test_empty_result(self) -> None:
        assert validate_tool_result("") == ""
