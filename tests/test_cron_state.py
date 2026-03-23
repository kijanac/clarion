"""Tests for clarion.cron_state — layer 0 cron persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from clarion.cron_state import (
    CronJob,
    add_job,
    edit_job,
    load_cron_state,
    mark_fired,
    remove_job,
)

# ── Helpers ─────────────────────────────────────────────────────────────────


def _make_job(**overrides: object) -> CronJob:
    defaults: dict[str, object] = {
        "job_id": "job-1",
        "name": "Test Job",
        "kind": "cron",
        "cron_expr": "0 9 * * *",
        "created_at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
    }
    return CronJob(**(defaults | overrides))


# ── Empty state ─────────────────────────────────────────────────────────────


class TestEmptyState:
    def test_load_empty_returns_empty_list(self, tmp_workspace: Path) -> None:
        assert load_cron_state(tmp_workspace) == []


# ── Add / Load roundtrip ───────────────────────────────────────────────────


class TestAddAndLoad:
    def test_add_and_load_roundtrip(self, tmp_workspace: Path) -> None:
        job = _make_job()
        add_job(tmp_workspace, job)

        loaded = load_cron_state(tmp_workspace)
        assert len(loaded) == 1
        assert loaded[0].job_id == "job-1"
        assert loaded[0].name == "Test Job"
        assert loaded[0].cron_expr == "0 9 * * *"

    def test_add_cron_job_sets_next_fire(self, tmp_workspace: Path) -> None:
        job = _make_job(next_fire=None)
        add_job(tmp_workspace, job)

        loaded = load_cron_state(tmp_workspace)
        assert loaded[0].next_fire is not None

    def test_add_multiple_jobs(self, tmp_workspace: Path) -> None:
        add_job(tmp_workspace, _make_job(job_id="job-1"))
        add_job(tmp_workspace, _make_job(job_id="job-2", name="Second"))

        loaded = load_cron_state(tmp_workspace)
        assert len(loaded) == 2
        assert {j.job_id for j in loaded} == {"job-1", "job-2"}


# ── Remove ──────────────────────────────────────────────────────────────────


class TestRemoveJob:
    def test_remove_existing_job(self, tmp_workspace: Path) -> None:
        add_job(tmp_workspace, _make_job(job_id="job-1"))
        add_job(tmp_workspace, _make_job(job_id="job-2"))

        assert remove_job(tmp_workspace, "job-1") is True
        loaded = load_cron_state(tmp_workspace)
        assert len(loaded) == 1
        assert loaded[0].job_id == "job-2"

    def test_remove_nonexistent_returns_false(self, tmp_workspace: Path) -> None:
        add_job(tmp_workspace, _make_job(job_id="job-1"))
        assert remove_job(tmp_workspace, "no-such-job") is False


# ── Edit ────────────────────────────────────────────────────────────────────


class TestEditJob:
    def test_edit_updates_fields(self, tmp_workspace: Path) -> None:
        add_job(tmp_workspace, _make_job(job_id="job-1"))
        assert edit_job(tmp_workspace, "job-1", name="Updated", enabled=False) is True

        loaded = load_cron_state(tmp_workspace)
        assert loaded[0].name == "Updated"
        assert loaded[0].enabled is False

    def test_edit_nonexistent_returns_false(self, tmp_workspace: Path) -> None:
        assert edit_job(tmp_workspace, "no-such-job", name="X") is False


# ── Mark fired ──────────────────────────────────────────────────────────────


class TestMarkFired:
    def test_mark_fired_sets_last_fired_and_advances_cron(
        self, tmp_workspace: Path
    ) -> None:
        job = _make_job(job_id="job-1", kind="cron", cron_expr="0 9 * * *")
        add_job(tmp_workspace, job)

        mark_fired(tmp_workspace, "job-1")

        loaded = load_cron_state(tmp_workspace)
        assert loaded[0].last_fired is not None
        assert loaded[0].next_fire is not None
        # next_fire must be strictly after last_fired
        last = datetime.fromisoformat(loaded[0].last_fired)
        nxt = datetime.fromisoformat(loaded[0].next_fire)
        assert nxt > last

    def test_mark_fired_disables_at_job(self, tmp_workspace: Path) -> None:
        job = _make_job(
            job_id="once",
            kind="at",
            cron_expr=None,
            at="2026-06-01T12:00:00+00:00",
        )
        add_job(tmp_workspace, job)
        mark_fired(tmp_workspace, "once")

        loaded = load_cron_state(tmp_workspace)
        assert loaded[0].enabled is False
        assert loaded[0].last_fired is not None

    def test_mark_fired_advances_every_ms(self, tmp_workspace: Path) -> None:
        job = _make_job(
            job_id="interval",
            kind="every",
            cron_expr=None,
            every_ms=60_000,
        )
        add_job(tmp_workspace, job)
        mark_fired(tmp_workspace, "interval")

        loaded = load_cron_state(tmp_workspace)
        assert loaded[0].next_fire is not None
        assert loaded[0].last_fired is not None


# ── Persistence ─────────────────────────────────────────────────────────────


class TestPersistence:
    def test_state_survives_reload(self, tmp_workspace: Path) -> None:
        job = _make_job(job_id="persist-1", name="Persistent")
        add_job(tmp_workspace, job)
        edit_job(tmp_workspace, "persist-1", name="Renamed")

        reloaded = load_cron_state(tmp_workspace)
        assert len(reloaded) == 1
        assert reloaded[0].name == "Renamed"
        assert reloaded[0].job_id == "persist-1"
