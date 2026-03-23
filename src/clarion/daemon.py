"""Clarion daemon — layer 3.

The always-on process. Manages the lifecycle: scan agents,
register schedules, fire runs, handle rescheduling, watch for changes.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import structlog

from clarion.agent_registry import AgentRegistry
from clarion.agent_runner import new_run_id, run_agent
from clarion.agent_state import count_runs_since
from clarion.cron_scheduler import CronScheduler
from clarion.cron_state import CronJob, load_cron_state
from clarion.llm_client import OpenAIStreamingClient
from clarion.models import AgentConfig, OutputType, RunContext, RunStatus

log = structlog.get_logger()


class Daemon:
    """The Clarion daemon — runs agents on their schedules."""

    def __init__(
        self,
        *,
        agents_dir: Path,
        templates_dir: Path,
        data_root: Path,
        max_concurrent_runs: int = 5,
    ) -> None:
        self._agents_dir = agents_dir
        self._templates_dir = templates_dir
        self._data_root = data_root

        self._registry = AgentRegistry(
            agents_dir=agents_dir,
            templates_dir=templates_dir,
            data_root=data_root,
        )
        self._scheduler = CronScheduler(tick_interval=30.0)
        self._max_concurrent = max_concurrent_runs
        self._run_semaphore = asyncio.Semaphore(max_concurrent_runs)
        self._active_runs: dict[str, asyncio.Task[None]] = {}

        self._shutdown_event = asyncio.Event()
        self._watcher_task: asyncio.Task[None] | None = None
        self._scheduler_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the daemon. Runs until interrupted."""
        # 1. Scan agents/ directory
        self._registry.scan()
        agents = self._registry.all_agents()
        log.info("daemon.scan_complete", agents=len(agents))

        # 2. Register schedules with CronScheduler
        for agent_id, config in agents.items():
            self._register_schedule(agent_id, config)

        # 3. Start file watcher
        self._watcher_task = asyncio.create_task(self._watch_files())

        # 4. Start scheduler tick loop
        self._scheduler_task = asyncio.create_task(self._scheduler.run())

        # 5. Wait for shutdown signal
        await self._shutdown_event.wait()

    async def shutdown(self) -> None:
        """Graceful shutdown. Wait for in-flight runs to complete."""
        log.info("daemon.shutdown_start")
        self._shutdown_event.set()

        if self._watcher_task is not None:
            self._watcher_task.cancel()
        if self._scheduler_task is not None:
            self._scheduler.stop()
            self._scheduler_task.cancel()

        # Wait for in-flight runs with a grace period
        if self._active_runs:
            log.info("daemon.shutdown_waiting", active_runs=len(self._active_runs))
            done, pending = await asyncio.wait(
                self._active_runs.values(),
                timeout=60.0,
            )
            for task in pending:
                task.cancel()
            if pending:
                await asyncio.gather(*pending, return_exceptions=True)

        log.info("daemon.shutdown_complete")

    # -- schedule registration ------------------------------------------------

    def _register_schedule(self, agent_id: str, config: AgentConfig) -> None:
        """Register an agent's default cron schedule."""
        workspace = self._data_root / "agents" / agent_id
        workspace.mkdir(parents=True, exist_ok=True)
        (workspace / "cron").mkdir(exist_ok=True)
        (workspace / "runs").mkdir(exist_ok=True)

        async def _on_cron_fire(aid: str, job: CronJob) -> None:
            await self._fire_run(aid, trigger="self_scheduled")

        self._scheduler.register(agent_id, str(workspace), _on_cron_fire)
        log.info(
            "daemon.schedule_registered",
            agent_id=agent_id,
            cron=config.schedule_cron,
        )

    def _unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from registry and scheduler."""
        self._registry.remove_agent(agent_id)
        self._scheduler.unregister(agent_id)
        log.info("daemon.agent_unregistered", agent_id=agent_id)

    # -- run budget -----------------------------------------------------------

    def _can_run(self, agent_id: str, trigger: str) -> bool:
        """Check if the agent has budget for another run today."""
        workspace = self._data_root / "agents" / agent_id
        today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        config = self._registry.get(agent_id)
        if config is None:
            return False

        total_today = count_runs_since(workspace, since=today_start)
        if total_today >= config.resources.max_runs_per_day:
            log.warning(
                "daemon.run_budget_exhausted",
                agent_id=agent_id,
                total_today=total_today,
                max_runs=config.resources.max_runs_per_day,
            )
            return False

        if trigger == "self_scheduled":
            self_today = count_runs_since(
                workspace, since=today_start, trigger_filter="self_scheduled"
            )
            if self_today >= config.resources.max_self_scheduled_runs_per_day:
                log.warning(
                    "daemon.self_schedule_budget_exhausted",
                    agent_id=agent_id,
                    self_today=self_today,
                    max_self=config.resources.max_self_scheduled_runs_per_day,
                )
                return False

        return True

    # -- run assembly and execution -------------------------------------------

    async def _fire_run(self, agent_id: str, trigger: str = "scheduled") -> None:
        """Assemble and spawn a single agent run."""
        config = self._registry.get(agent_id)
        if config is None:
            log.warning("daemon.fire_skip", agent_id=agent_id, reason="not registered")
            return

        if not self._can_run(agent_id, trigger):
            return

        # Read mission fresh from disk (hot-reload)
        workspace = self._data_root / "agents" / agent_id
        mission_path = workspace / "mission.md"
        if not mission_path.exists():
            log.error("daemon.fire_skip", agent_id=agent_id, reason="no mission.md")
            return
        mission_md = mission_path.read_text()

        # Assemble RunContext
        run_id = new_run_id()
        context = RunContext(
            agent_id=agent_id,
            run_id=run_id,
            config=config,
            mission_md=mission_md,
            workspace_root=str(workspace),
            trigger=trigger,
            current_datetime=datetime.now(UTC),
        )

        # Spawn as a concurrent task with semaphore control
        task = asyncio.create_task(self._guarded_run(context))
        task_key = f"{agent_id}-{run_id}"
        self._active_runs[task_key] = task
        task.add_done_callback(lambda _: self._active_runs.pop(task_key, None))

    async def _guarded_run(self, context: RunContext) -> None:
        """Execute a run under the concurrency semaphore."""
        async with self._run_semaphore:
            await self._execute_run(context)

    async def _execute_run(self, context: RunContext) -> None:
        """Execute a single agent run."""
        from clarion.tools.executor import ToolExecutor

        llm_client = OpenAIStreamingClient()
        adapters = self._build_adapters()
        executor = ToolExecutor(
            agent_id=context.agent_id,
            agent_config=context.config,
            workspace_root=Path(context.workspace_root),
            delivery_adapters=adapters,
            schedule_timezone=context.config.schedule_timezone,
        )

        result = await run_agent(context, llm_client, executor)

        # Post-run: sync cron state for agent-initiated rescheduling
        self._sync_cron_state(context.agent_id)

        log.info(
            "daemon.run_complete",
            agent_id=context.agent_id,
            run_id=context.run_id,
            status=result.status.value,
        )

    def _sync_cron_state(self, agent_id: str) -> None:
        """Re-read agent's cron state after a run and update the scheduler."""
        workspace = self._data_root / "agents" / agent_id
        jobs = load_cron_state(workspace)
        log.debug(
            "daemon.cron_sync",
            agent_id=agent_id,
            job_count=len(jobs),
        )

    def _build_adapters(self) -> dict[OutputType, object]:
        """Build delivery adapters from environment."""
        from clarion.adapters.telegram import TelegramAdapter

        adapters: dict[OutputType, object] = {}
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        if bot_token:
            adapters[OutputType.TELEGRAM] = TelegramAdapter(bot_token)
        return adapters

    # -- file watching --------------------------------------------------------

    async def _watch_files(self) -> None:
        """Watch agents/ directory for config changes."""
        import watchfiles

        try:
            async for changes in watchfiles.awatch(self._agents_dir):
                for change_type, path_str in changes:
                    path = Path(path_str)

                    if path.name == "agent.yaml":
                        agent_id = path.parent.name
                        if change_type == watchfiles.Change.deleted:
                            self._unregister_agent(agent_id)
                        else:
                            self._handle_config_change(agent_id)

                    # mission.md changes don't need handling here —
                    # mission is read fresh at the start of each run
        except asyncio.CancelledError:
            pass

    def _handle_config_change(self, agent_id: str) -> None:
        """Handle a change to an agent's config file."""
        old_config = self._registry.get(agent_id)
        new_config = self._registry.reload_agent(agent_id)

        if new_config is None:
            return

        # If schedule changed, re-register with the scheduler
        if old_config is None or old_config.schedule_cron != new_config.schedule_cron:
            self._scheduler.unregister(agent_id)
            self._register_schedule(agent_id, new_config)
            log.info(
                "daemon.schedule_updated",
                agent_id=agent_id,
                cron=new_config.schedule_cron,
            )
