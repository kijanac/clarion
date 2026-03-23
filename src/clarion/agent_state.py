"""Per-agent run history — append-only JSONL — layer 0."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import structlog

from clarion.models import AgentRun

log = structlog.get_logger()


def record_run(run: AgentRun, workspace_root: Path) -> None:
    """Append a completed AgentRun to the agent's run history."""
    runs_dir = Path(workspace_root) / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    history_file = runs_dir / "history.jsonl"
    with open(history_file, "a", encoding="utf-8") as f:
        f.write(run.model_dump_json() + "\n")


def load_run_history(workspace_root: Path, limit: int = 50) -> list[AgentRun]:
    """Load the most recent runs from history, newest first."""
    history_file = Path(workspace_root) / "runs" / "history.jsonl"
    if not history_file.exists():
        return []
    runs: list[AgentRun] = []
    for line in reversed(history_file.read_text(encoding="utf-8").splitlines()):
        if not line.strip():
            continue
        try:
            runs.append(AgentRun.model_validate_json(line))
        except Exception:
            log.warning("run_history.invalid_line")
            continue
        if len(runs) >= limit:
            break
    return runs


def last_run(workspace_root: Path) -> AgentRun | None:
    """Return the most recent run, or None if no history."""
    history = load_run_history(workspace_root, limit=1)
    return history[0] if history else None


def count_runs_since(
    workspace_root: Path,
    since: datetime,
    trigger_filter: str | None = None,
) -> int:
    """Count runs since a given datetime, optionally filtered by trigger."""
    history = load_run_history(workspace_root, limit=200)
    count = 0
    for run in history:
        if run.started_at < since:
            break  # history is newest-first, so we can stop
        if trigger_filter and run.trigger != trigger_filter:
            continue
        count += 1
    return count
