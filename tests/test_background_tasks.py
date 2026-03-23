"""Tests for clarion.background_tasks — async task manager."""

from __future__ import annotations

import asyncio

import pytest

from clarion.background_tasks import BackgroundTaskManager


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _immediate(value: str = "done") -> str:
    return value


async def _slow(seconds: float = 10.0) -> str:
    await asyncio.sleep(seconds)
    return "finished"


# ── Tests ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_spawn_and_complete():
    mgr = BackgroundTaskManager(max_concurrent=3)
    results: list[tuple[str | None, str | None]] = []

    async def on_complete(handle, result, error):
        results.append((result, error))

    mgr.spawn(
        agent_id="test",
        label="test-task",
        task_factory=lambda: _immediate("done"),
        on_complete=on_complete,
    )
    await asyncio.sleep(0.1)

    assert results == [("done", None)]


@pytest.mark.asyncio
async def test_timeout_calls_on_complete_with_error():
    mgr = BackgroundTaskManager(max_concurrent=3)
    results: list[tuple[str | None, str | None]] = []

    async def on_complete(handle, result, error):
        results.append((result, error))

    mgr.spawn(
        agent_id="test",
        label="slow-task",
        task_factory=lambda: _slow(10.0),
        on_complete=on_complete,
        timeout_s=0.05,
    )
    await asyncio.sleep(0.3)

    assert len(results) == 1
    assert results[0][0] is None
    assert results[0][1] is not None
    assert "timed out" in results[0][1]


@pytest.mark.asyncio
async def test_shutdown_cancels_active_tasks():
    mgr = BackgroundTaskManager(max_concurrent=3)
    callback_called = False

    async def on_complete(handle, result, error):
        nonlocal callback_called
        callback_called = True

    mgr.spawn(
        agent_id="test",
        label="long-task",
        task_factory=lambda: _slow(60.0),
        on_complete=on_complete,
    )
    assert mgr.active_count == 1

    await mgr.shutdown()

    assert mgr.active_count == 0
    # CancelledError path returns without calling on_complete
    assert callback_called is False


@pytest.mark.asyncio
async def test_active_count_tracks_running_tasks():
    mgr = BackgroundTaskManager(max_concurrent=5)
    barrier = asyncio.Event()

    async def _wait_for_barrier() -> str:
        await barrier.wait()
        return "ok"

    async def on_complete(handle, result, error):
        pass

    mgr.spawn(
        agent_id="a",
        label="t1",
        task_factory=lambda: _wait_for_barrier(),
        on_complete=on_complete,
    )
    mgr.spawn(
        agent_id="b",
        label="t2",
        task_factory=lambda: _wait_for_barrier(),
        on_complete=on_complete,
    )
    await asyncio.sleep(0.05)

    assert mgr.active_count == 2

    barrier.set()
    await asyncio.sleep(0.1)

    assert mgr.active_count == 0
