"""Tests for clarion.logging — structured logging configuration."""

from __future__ import annotations

import json

import structlog

from clarion.logging import bind_context, clear_context, configure_logging


def test_configure_logging_json_mode() -> None:
    configure_logging(json=True, level="DEBUG")
    log = structlog.get_logger()
    # Should not raise
    log.info("json-test", key="value")


def test_configure_logging_dev_mode() -> None:
    configure_logging(json=False, level="DEBUG")
    log = structlog.get_logger()
    log.info("dev-test", key="value")


def test_bind_context_adds_fields(capsys: object) -> None:
    configure_logging(json=True, level="DEBUG")
    clear_context()
    bind_context(agent_id="a1", run_id="r1")

    log = structlog.get_logger()
    log.info("ctx-test")

    captured = capsys.readouterr()  # type: ignore[union-attr]
    record = json.loads(captured.out.strip())
    assert record["agent_id"] == "a1"
    assert record["run_id"] == "r1"
    assert record["event"] == "ctx-test"


def test_clear_context_removes_fields(capsys: object) -> None:
    configure_logging(json=True, level="DEBUG")
    clear_context()
    bind_context(trace_id="t1")
    clear_context()

    log = structlog.get_logger()
    log.info("after-clear")

    captured = capsys.readouterr()  # type: ignore[union-attr]
    record = json.loads(captured.out.strip())
    assert "trace_id" not in record
    assert record["event"] == "after-clear"
