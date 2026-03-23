"""Tests for clarion.agent_state — per-agent run history."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from clarion.agent_state import last_run, load_run_history, record_run
from clarion.models import AgentRun, RunStatus


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_run(run_id: str = "run_001", **overrides: object) -> AgentRun:
    defaults = {
        "run_id": run_id,
        "agent_id": "test-agent",
        "started_at": datetime.now(timezone.utc),
        "status": RunStatus.SUCCESS,
        "trigger": "manual",
    }
    return AgentRun(**(defaults | overrides))


# ── record_run ──────────────────────────────────────────────────────────────


class TestRecordRun:
    def test_creates_file_and_appends(self, tmp_workspace: Path) -> None:
        history_file = tmp_workspace / "runs" / "history.jsonl"
        assert not history_file.exists()

        run = _make_run()
        record_run(run, tmp_workspace)

        assert history_file.exists()
        lines = history_file.read_text().strip().split("\n")
        assert len(lines) == 1

    def test_appends_multiple_runs(self, tmp_workspace: Path) -> None:
        record_run(_make_run("run_001"), tmp_workspace)
        record_run(_make_run("run_002"), tmp_workspace)
        record_run(_make_run("run_003"), tmp_workspace)

        history_file = tmp_workspace / "runs" / "history.jsonl"
        lines = history_file.read_text().strip().split("\n")
        assert len(lines) == 3


# ── load_run_history ────────────────────────────────────────────────────────


class TestLoadRunHistory:
    def test_empty_when_no_file(self, tmp_workspace: Path) -> None:
        assert load_run_history(tmp_workspace) == []

    def test_returns_reverse_chronological(self, tmp_workspace: Path) -> None:
        for i in range(1, 4):
            record_run(_make_run(f"run_{i:03d}"), tmp_workspace)

        runs = load_run_history(tmp_workspace)
        assert [r.run_id for r in runs] == ["run_003", "run_002", "run_001"]

    def test_limit_parameter(self, tmp_workspace: Path) -> None:
        for i in range(1, 6):
            record_run(_make_run(f"run_{i:03d}"), tmp_workspace)

        runs = load_run_history(tmp_workspace, limit=2)
        assert len(runs) == 2
        assert [r.run_id for r in runs] == ["run_005", "run_004"]


# ── last_run ────────────────────────────────────────────────────────────────


class TestLastRun:
    def test_none_on_empty_history(self, tmp_workspace: Path) -> None:
        assert last_run(tmp_workspace) is None

    def test_returns_most_recent(self, tmp_workspace: Path) -> None:
        record_run(_make_run("run_001"), tmp_workspace)
        record_run(_make_run("run_002"), tmp_workspace)

        result = last_run(tmp_workspace)
        assert result is not None
        assert result.run_id == "run_002"


# ── Roundtrip ───────────────────────────────────────────────────────────────


class TestRoundtrip:
    def test_record_then_load_preserves_data(self, tmp_workspace: Path) -> None:
        original = _make_run(
            run_id="run_rt",
            status=RunStatus.FAILED,
            error="something broke",
            outputs_produced=["digest"],
            tool_call_counts={"web_search": 3},
        )
        record_run(original, tmp_workspace)

        loaded = load_run_history(tmp_workspace)
        assert len(loaded) == 1
        restored = loaded[0]
        assert restored.run_id == original.run_id
        assert restored.agent_id == original.agent_id
        assert restored.status == original.status
        assert restored.error == original.error
        assert restored.outputs_produced == original.outputs_produced
        assert restored.tool_call_counts == original.tool_call_counts


# ── Corrupt history ─────────────────────────────────────────────────────────


class TestCorruptHistory:
    def test_corrupt_line_skipped(self, tmp_workspace: Path) -> None:
        record_run(_make_run("run_001"), tmp_workspace)
        # Inject a corrupt line
        history_file = tmp_workspace / "runs" / "history.jsonl"
        with open(history_file, "a") as f:
            f.write("THIS IS NOT JSON\n")
        record_run(_make_run("run_003"), tmp_workspace)

        runs = load_run_history(tmp_workspace)
        assert len(runs) == 2
        assert runs[0].run_id == "run_003"
        assert runs[1].run_id == "run_001"

    def test_empty_lines_skipped(self, tmp_workspace: Path) -> None:
        record_run(_make_run("run_001"), tmp_workspace)
        history_file = tmp_workspace / "runs" / "history.jsonl"
        with open(history_file, "a") as f:
            f.write("\n\n\n")
        record_run(_make_run("run_002"), tmp_workspace)

        runs = load_run_history(tmp_workspace)
        assert len(runs) == 2
