"""Cron job management tool."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from croniter import croniter

from clarion.cron_state import (
    CronJob,
    add_job,
    edit_job,
    load_cron_state,
    remove_job,
)


class CronValidationError(ValueError):
    """Raised when a cron job has an invalid schedule."""


@dataclass
class CronEffects:
    registrations: list[CronJob] = field(default_factory=list)
    unregistrations: list[str] = field(default_factory=list)


def _format_schedule(job: CronJob) -> str:
    if job.kind == "at":
        return f"at {job.at}"
    if job.kind == "every":
        return f"every {job.every_ms}ms"
    return f"cron {job.cron_expr}"


def _validate_schedule(kind: str, arguments: dict[str, object]) -> None:
    """Validate schedule parameters before creating a job.

    Raises CronValidationError if the schedule is invalid.
    """
    if kind not in ("at", "every", "cron"):
        raise CronValidationError(f"Invalid kind: {kind!r}. Must be at, every, or cron.")

    if kind == "at":
        at = str(arguments.get("at", ""))
        if not at:
            raise CronValidationError("kind=at requires an 'at' ISO 8601 timestamp")
        try:
            datetime.fromisoformat(at)
        except ValueError:
            raise CronValidationError(f"Invalid ISO 8601 timestamp: {at!r}")

    elif kind == "every":
        every_ms = int(str(arguments.get("every_ms", 0)))
        if every_ms <= 0:
            raise CronValidationError("kind=every requires a positive 'every_ms' value")

    elif kind == "cron":
        cron_expr = str(arguments.get("cron", ""))
        if not cron_expr:
            raise CronValidationError("kind=cron requires a 'cron' expression")
        if not croniter.is_valid(cron_expr):
            raise CronValidationError(f"Invalid cron expression: {cron_expr!r}")


def execute_cron(
    arguments: dict[str, object],
    correlation_id: str,
    workspace_root: Path,
    agent_id: str,
) -> tuple[str, CronEffects]:
    action = str(arguments.get("action", ""))
    effects = CronEffects()

    if action == "add":
        kind = str(arguments.get("kind", ""))
        try:
            _validate_schedule(kind, arguments)
        except CronValidationError as exc:
            return f"Invalid schedule: {exc}", effects

        now = datetime.now(UTC).isoformat()
        job = CronJob(
            job_id=uuid.uuid4().hex[:12],
            name=str(arguments.get("name", "")),
            kind=kind,
            at=str(arguments.get("at", "")) or None,
            every_ms=int(str(arguments.get("every_ms", 0))) or None,
            cron_expr=str(arguments.get("cron", "")) or None,
            created_at=now,
        )
        add_job(workspace_root, job)
        effects.registrations.append(job)
        return f"Job added: {job.name} (kind={job.kind}) [id={job.job_id}]", effects

    if action == "list":
        jobs = load_cron_state(workspace_root)
        active = [j for j in jobs if j.enabled]
        if not active:
            return "(no active jobs)", effects
        lines: list[str] = []
        for j in active:
            sched = _format_schedule(j)
            lines.append(f"- {j.name} [{j.job_id}] {sched}")
        return "\n".join(lines), effects

    if action == "remove":
        job_id = str(arguments.get("job_id", ""))
        removed = remove_job(workspace_root, job_id)
        if removed:
            effects.unregistrations.append(job_id)
            return f"Job removed: {job_id}", effects
        return f"Job not found: {job_id}", effects

    if action == "edit":
        job_id = str(arguments.get("job_id", ""))
        updates: dict[str, object] = {}
        if "name" in arguments:
            updates["name"] = str(arguments["name"])
        if "enabled" in arguments:
            updates["enabled"] = bool(arguments["enabled"])
        if "kind" in arguments:
            new_kind = str(arguments["kind"])
            try:
                _validate_schedule(new_kind, arguments)
            except CronValidationError as exc:
                return f"Invalid schedule: {exc}", effects
            updates["kind"] = new_kind
            updates["at"] = str(arguments.get("at", "")) or None
            updates["every_ms"] = int(str(arguments.get("every_ms", 0))) or None
            updates["cron_expr"] = str(arguments.get("cron", "")) or None
        found = edit_job(workspace_root, job_id, **updates)
        if not found:
            return f"Job not found: {job_id}", effects
        return f"Job updated: {job_id}", effects

    raise RuntimeError(f"unknown cron action: {action}")


# ---------------------------------------------------------------------------
# ToolHandler
# ---------------------------------------------------------------------------

from clarion.tools.base import ToolContext, ToolHandler, ToolResult


class CronHandler(ToolHandler):
    async def execute(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        text, effects = execute_cron(
            arguments, ctx.correlation_id, ctx.workspace_root, ctx.agent_id
        )
        return ToolResult(
            text=text,
            cron_registrations=effects.registrations,
            cron_unregistrations=effects.unregistrations,
        )
