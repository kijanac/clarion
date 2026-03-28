"""Clarion daemon — layer 3.

The always-on process. Manages agent lifecycle: scan agents,
register triggers with APScheduler + EventBus, fire runs,
emit output_produced events, watch for config changes.
"""

from __future__ import annotations

import asyncio
import os
from datetime import UTC, datetime
from pathlib import Path

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from clarion.agent_registry import AgentRegistry
from clarion.agent_runner import new_run_id, run_agent
from clarion.agent_state import count_runs_since, ensure_workspace
from clarion.event_bus import Event, EventBus, EventType
from clarion.llm_client import OpenAIStreamingClient
from clarion.models import AgentConfig, OutputType, RunContext, TriggerType
from clarion.tools.executor import ToolExecutor

log = structlog.get_logger()


class Daemon:
    """The Clarion daemon — runs agents on their triggers."""

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
        self._event_bus = EventBus(fire_callback=self._fire_run)
        self._scheduler = AsyncIOScheduler()
        self._max_concurrent = max_concurrent_runs
        self._run_semaphore = asyncio.Semaphore(max_concurrent_runs)
        self._active_runs: dict[str, asyncio.Task[None]] = {}

        self._shutdown_event = asyncio.Event()
        self._watcher_task: asyncio.Task[None] | None = None
        self._bus_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        """Start the daemon. Runs until interrupted."""
        self._registry.scan()
        agents = self._registry.all_agents()
        log.info("daemon.scan_complete", agents=len(agents))

        for agent_id, config in agents.items():
            if config.enabled:
                self._register_agent(agent_id, config)
            else:
                log.info("daemon.agent_paused", agent_id=agent_id)

        self._scheduler.start()
        self._bus_task = asyncio.create_task(self._event_bus.run())
        self._watcher_task = asyncio.create_task(self._watch_files())

        await self._shutdown_event.wait()

    async def shutdown(self) -> None:
        """Graceful shutdown."""
        log.info("daemon.shutdown_start")
        self._shutdown_event.set()

        self._scheduler.shutdown(wait=False)
        self._event_bus.stop()

        if self._watcher_task is not None:
            self._watcher_task.cancel()
        if self._bus_task is not None:
            self._bus_task.cancel()

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

    # -- trigger registration -------------------------------------------------

    def _register_agent(self, agent_id: str, config: AgentConfig) -> None:
        """Register an agent's triggers with APScheduler and EventBus."""
        ensure_workspace(self._data_root / "agents" / agent_id)
        self._event_bus.register(agent_id, config.triggers)

        for i, trigger in enumerate(config.triggers):
            if trigger.type == TriggerType.CRON and trigger.expression:
                job_id = f"{agent_id}__cron_{i}"
                cron_trigger = CronTrigger.from_crontab(
                    trigger.expression,
                    timezone=trigger.timezone,
                )
                self._scheduler.add_job(
                    self._emit_cron_event,
                    trigger=cron_trigger,
                    args=[agent_id],
                    id=job_id,
                    replace_existing=True,
                )
                log.info(
                    "daemon.cron_registered",
                    agent_id=agent_id,
                    expression=trigger.expression,
                    timezone=trigger.timezone,
                )

    def _remove_scheduler_jobs(self, agent_id: str) -> None:
        """Remove all APScheduler jobs for an agent."""
        for job in self._scheduler.get_jobs():
            if job.id.startswith(f"{agent_id}__"):
                job.remove()

    def _unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from registry, scheduler, and event bus."""
        self._registry.remove_agent(agent_id)
        self._event_bus.unregister(agent_id)
        self._remove_scheduler_jobs(agent_id)
        log.info("daemon.agent_unregistered", agent_id=agent_id)

    async def trigger_run(self, agent_id: str, trigger: str = "manual_web") -> None:
        """Public API for triggering a run. Used by the web API."""
        await self._fire_run(agent_id, trigger)

    async def _emit_cron_event(self, agent_id: str) -> None:
        """Called by APScheduler when a cron trigger fires."""
        await self._event_bus.emit(Event(type=EventType.CRON_FIRED, agent_id=agent_id))

    # -- run budget -----------------------------------------------------------

    def _can_run(self, agent_id: str) -> bool:
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

        return True

    # -- run assembly and execution -------------------------------------------

    async def _fire_run(self, agent_id: str, trigger: str = "cron") -> None:
        """Assemble and spawn a single agent run."""
        config = self._registry.get(agent_id)
        if config is None:
            log.warning("daemon.fire_skip", agent_id=agent_id, reason="not registered")
            return

        if not config.enabled:
            log.info("daemon.fire_skip", agent_id=agent_id, reason="paused")
            return

        if not self._can_run(agent_id):
            return

        workspace = self._data_root / "agents" / agent_id
        mission_path = workspace / "mission.md"
        if not mission_path.exists():
            log.error("daemon.fire_skip", agent_id=agent_id, reason="no mission.md")
            return
        mission_md = mission_path.read_text()

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

        task = asyncio.create_task(self._guarded_run(context))
        task_key = f"{agent_id}-{run_id}"
        self._active_runs[task_key] = task
        task.add_done_callback(lambda _: self._active_runs.pop(task_key, None))

    async def _guarded_run(self, context: RunContext) -> None:
        """Execute a run under the concurrency semaphore."""
        async with self._run_semaphore:
            await self._execute_run(context)

    async def _execute_run(self, context: RunContext) -> None:
        """Execute a single agent run, then emit output events."""
        adapters = self._build_adapters()
        llm_client = OpenAIStreamingClient()
        executor = ToolExecutor(
            agent_id=context.agent_id,
            agent_config=context.config,
            workspace_root=Path(context.workspace_root),
            delivery_adapters=adapters,
        )

        result = await run_agent(context, llm_client, executor)

        # Emit output_produced events so agent_output triggers fire
        for output_name in result.outputs_produced:
            await self._event_bus.emit(Event(
                type=EventType.OUTPUT_PRODUCED,
                agent_id=context.agent_id,
                output_name=output_name,
            ))

        log.info(
            "daemon.run_complete",
            agent_id=context.agent_id,
            run_id=context.run_id,
            status=result.status.value,
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
        except asyncio.CancelledError:
            pass

    def _handle_config_change(self, agent_id: str) -> None:
        """Handle a change to an agent's config file."""
        old_config = self._registry.get(agent_id)
        new_config = self._registry.reload_agent(agent_id)

        if new_config is None:
            return

        needs_reregister = (
            old_config is None
            or old_config.triggers != new_config.triggers
            or old_config.enabled != new_config.enabled
        )
        if needs_reregister:
            self._remove_scheduler_jobs(agent_id)
            self._event_bus.unregister(agent_id)
            if new_config.enabled:
                self._register_agent(agent_id, new_config)
                log.info("daemon.agent_resumed", agent_id=agent_id)
            else:
                log.info("daemon.agent_paused", agent_id=agent_id)
