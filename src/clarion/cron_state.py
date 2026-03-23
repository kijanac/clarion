"""Cron state persistence — layer 0.

Per-agent cron job state. Stores job definitions and fire history
to a JSON file in the agent's cron/ directory.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from croniter import croniter


@dataclass
class CronJob:
    job_id: str
    name: str
    kind: str  # "at", "every", "cron"
    at: str | None = None  # ISO 8601 for one-time
    every_ms: int | None = None  # interval for recurring
    cron_expr: str | None = None  # 5-field cron
    enabled: bool = True
    created_at: str = ""
    last_fired: str | None = None
    next_fire: str | None = None


def _state_file(workspace_root: Path) -> Path:
    return workspace_root / "cron" / "state.json"


def load_cron_state(workspace_root: Path) -> list[CronJob]:
    """Load all cron jobs from the agent's state file."""
    path = _state_file(workspace_root)
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    return [CronJob(**job) for job in data.get("jobs", [])]


def _save_cron_state(workspace_root: Path, jobs: list[CronJob]) -> None:
    """Persist cron jobs to the state file."""
    path = _state_file(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"jobs": [asdict(job) for job in jobs]}
    path.write_text(json.dumps(data, indent=2) + "\n")


def add_job(workspace_root: Path, job: CronJob) -> None:
    """Add a new cron job to the state."""
    jobs = load_cron_state(workspace_root)
    if job.cron_expr and not job.next_fire:
        job.next_fire = _next_cron_fire(job.cron_expr)
    jobs.append(job)
    _save_cron_state(workspace_root, jobs)


def remove_job(workspace_root: Path, job_id: str) -> bool:
    """Remove a job by ID. Returns True if found and removed."""
    jobs = load_cron_state(workspace_root)
    original_len = len(jobs)
    jobs = [j for j in jobs if j.job_id != job_id]
    if len(jobs) == original_len:
        return False
    _save_cron_state(workspace_root, jobs)
    return True


def edit_job(workspace_root: Path, job_id: str, **updates: object) -> bool:
    """Update fields on an existing job. Returns True if found."""
    jobs = load_cron_state(workspace_root)
    for job in jobs:
        if job.job_id == job_id:
            for key, value in updates.items():
                if hasattr(job, key):
                    setattr(job, key, value)
            _save_cron_state(workspace_root, jobs)
            return True
    return False


def mark_fired(workspace_root: Path, job_id: str) -> None:
    """Mark a job as fired: update last_fired and advance next_fire."""
    jobs = load_cron_state(workspace_root)
    for job in jobs:
        if job.job_id == job_id:
            job.last_fired = datetime.now(UTC).isoformat()
            if job.kind == "at":
                job.enabled = False
            elif job.cron_expr:
                job.next_fire = _next_cron_fire(job.cron_expr)
            elif job.every_ms:
                next_dt = datetime.now(UTC) + timedelta(milliseconds=job.every_ms)
                job.next_fire = next_dt.isoformat()
            break
    _save_cron_state(workspace_root, jobs)


def _next_cron_fire(cron_expr: str) -> str:
    """Calculate the next fire time for a cron expression."""
    cron = croniter(cron_expr, datetime.now(UTC))
    return cron.get_next(datetime).isoformat()
