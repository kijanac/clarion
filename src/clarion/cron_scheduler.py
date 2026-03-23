"""Cron scheduler — layer 0.

Background scheduler that checks for due cron jobs and fires callbacks.
Runs as an asyncio task in the daemon. Includes exponential backoff
for jobs whose callbacks fail.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from collections.abc import Callable, Coroutine
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import structlog

from clarion.cron_state import CronJob, load_cron_state, mark_fired

log = structlog.get_logger()

# Type alias for async callback: receives (agent_id, job)
JobCallback = Callable[[str, CronJob], Coroutine[Any, Any, None]]

# Exponential backoff schedule (seconds) for failing jobs
_BACKOFF_SCHEDULE = (30, 60, 300, 900, 3600)  # 30s, 1m, 5m, 15m, 1h


class CronScheduler:
    """Checks registered agents for due cron jobs and fires callbacks.

    Implements exponential backoff: if a job's callback fails, the job
    is suppressed for increasing intervals before retrying. A successful
    fire resets the backoff.
    """

    def __init__(self, tick_interval: float = 30.0) -> None:
        self._tick_interval = tick_interval
        # Map of agent_id -> (workspace_root, callback)
        self._agents: dict[str, tuple[Path, JobCallback]] = {}
        self._running = False
        # Backoff tracking: (agent_id, job_id) -> (fail_count, retry_after_utc)
        self._backoff: dict[tuple[str, str], tuple[int, datetime]] = defaultdict(
            lambda: (0, datetime.min.replace(tzinfo=timezone.utc))
        )

    @property
    def agent_count(self) -> int:
        return len(self._agents)

    def register(
        self,
        agent_id: str,
        workspace_root: str,
        callback: JobCallback,
    ) -> None:
        """Register an agent's cron jobs for scheduling."""
        self._agents[agent_id] = (Path(workspace_root), callback)
        log.info("cron.register", agent_id=agent_id)

    def unregister(self, agent_id: str) -> None:
        """Remove an agent from the scheduler."""
        self._agents.pop(agent_id, None)
        # Clear backoff state for this agent
        keys_to_remove = [k for k in self._backoff if k[0] == agent_id]
        for k in keys_to_remove:
            del self._backoff[k]
        log.info("cron.unregister", agent_id=agent_id)

    async def tick(self) -> None:
        """Check all registered agents for due jobs and fire them."""
        now = datetime.now(timezone.utc)
        for agent_id, (workspace_root, callback) in list(self._agents.items()):
            jobs = load_cron_state(workspace_root)
            for job in jobs:
                if not job.enabled:
                    continue
                if job.next_fire is None:
                    continue
                next_fire_dt = datetime.fromisoformat(job.next_fire)
                if next_fire_dt.tzinfo is None:
                    next_fire_dt = next_fire_dt.replace(tzinfo=timezone.utc)
                if next_fire_dt > now:
                    continue

                # Check backoff
                backoff_key = (agent_id, job.job_id)
                fail_count, retry_after = self._backoff[backoff_key]
                if fail_count > 0 and now < retry_after:
                    continue  # Still in backoff period

                log.info(
                    "cron.fire",
                    agent_id=agent_id,
                    job_id=job.job_id,
                    job_name=job.name,
                )
                try:
                    await callback(agent_id, job)
                    mark_fired(workspace_root, job.job_id)
                    # Success — reset backoff
                    if backoff_key in self._backoff:
                        del self._backoff[backoff_key]
                except Exception:
                    # Increment backoff
                    new_count = fail_count + 1
                    backoff_idx = min(new_count - 1, len(_BACKOFF_SCHEDULE) - 1)
                    backoff_s = _BACKOFF_SCHEDULE[backoff_idx]
                    retry_at = datetime.now(timezone.utc) + timedelta(seconds=backoff_s)
                    self._backoff[backoff_key] = (new_count, retry_at)
                    log.error(
                        "cron.fire_error",
                        agent_id=agent_id,
                        job_id=job.job_id,
                        fail_count=new_count,
                        backoff_s=backoff_s,
                        retry_after=retry_at.isoformat(),
                    )

    async def run(self) -> None:
        """Infinite tick loop. Call as an asyncio task."""
        self._running = True
        log.info("cron.scheduler_start", tick_interval=self._tick_interval)
        try:
            while self._running:
                await self.tick()
                await asyncio.sleep(self._tick_interval)
        finally:
            log.info("cron.scheduler_stop")

    def stop(self) -> None:
        """Signal the run loop to stop."""
        self._running = False
