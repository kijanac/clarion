"""Tests for clarion.cron_scheduler — layer 0 cron scheduling."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from clarion.cron_scheduler import CronScheduler
from clarion.cron_state import CronJob, add_job


# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_due_job(**overrides: object) -> CronJob:
    """Create a cron job whose next_fire is in the past (immediately due)."""
    past = (datetime.now(UTC) - timedelta(minutes=5)).isoformat()
    defaults: dict[str, object] = {
        "job_id": "job-1",
        "name": "Due Job",
        "kind": "cron",
        "cron_expr": "0 9 * * *",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        "next_fire": past,
    }
    return CronJob(**(defaults | overrides))


def _make_future_job(**overrides: object) -> CronJob:
    """Create a cron job whose next_fire is in the future (not yet due)."""
    future = (datetime.now(UTC) + timedelta(hours=2)).isoformat()
    defaults: dict[str, object] = {
        "job_id": "job-future",
        "name": "Future Job",
        "kind": "cron",
        "cron_expr": "0 9 * * *",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
        "next_fire": future,
    }
    return CronJob(**(defaults | overrides))


# ── Tick fires due jobs ─────────────────────────────────────────────────────


class TestTickFiresDue:
    async def test_tick_fires_callback_for_due_job(self, tmp_workspace: Path) -> None:
        job = _make_due_job()
        add_job(tmp_workspace, job)

        fired: list[tuple[str, CronJob]] = []

        async def on_fire(agent_id: str, j: CronJob) -> None:
            fired.append((agent_id, j))

        scheduler = CronScheduler()
        scheduler.register("agent-1", str(tmp_workspace), on_fire)
        await scheduler.tick()

        assert len(fired) == 1
        assert fired[0][0] == "agent-1"
        assert fired[0][1].job_id == "job-1"


# ── Tick skips future jobs ──────────────────────────────────────────────────


class TestTickSkipsFuture:
    async def test_tick_does_not_fire_future_job(self, tmp_workspace: Path) -> None:
        job = _make_future_job()
        add_job(tmp_workspace, job)

        fired: list[tuple[str, CronJob]] = []

        async def on_fire(agent_id: str, j: CronJob) -> None:
            fired.append((agent_id, j))

        scheduler = CronScheduler()
        scheduler.register("agent-1", str(tmp_workspace), on_fire)
        await scheduler.tick()

        assert fired == []


# ── Tick skips disabled jobs ────────────────────────────────────────────────


class TestTickSkipsDisabled:
    async def test_tick_does_not_fire_disabled_job(self, tmp_workspace: Path) -> None:
        job = _make_due_job(enabled=False)
        add_job(tmp_workspace, job)

        fired: list[tuple[str, CronJob]] = []

        async def on_fire(agent_id: str, j: CronJob) -> None:
            fired.append((agent_id, j))

        scheduler = CronScheduler()
        scheduler.register("agent-1", str(tmp_workspace), on_fire)
        await scheduler.tick()

        assert fired == []


# ── Unregister ──────────────────────────────────────────────────────────────


class TestUnregister:
    async def test_unregister_removes_agent(self, tmp_workspace: Path) -> None:
        job = _make_due_job()
        add_job(tmp_workspace, job)

        fired: list[tuple[str, CronJob]] = []

        async def on_fire(agent_id: str, j: CronJob) -> None:
            fired.append((agent_id, j))

        scheduler = CronScheduler()
        scheduler.register("agent-1", str(tmp_workspace), on_fire)
        scheduler.unregister("agent-1")
        await scheduler.tick()

        assert fired == []
