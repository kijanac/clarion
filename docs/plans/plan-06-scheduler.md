# Plan 06 — Scheduler (Layer 3) — Phase 2

## Goal

Implement the daemon and agent registry. After this plan, `clarion daemon`
runs as a persistent process that discovers agents, watches for config
changes, fires agent runs on schedule, handles agent-initiated
rescheduling, and manages concurrent runs via the BackgroundTaskManager.

This layer depends on foundation (0), algorithms (1), runtime (2), and
adapters (4).

---

## Prerequisites

All Phase 1 layers (plans 01-05) must be complete and working. The
`clarion run --agent <id>` command must execute successful end-to-end
runs.

---

## Dependencies from lower layers

```python
# Layer 0
from clarion.models import AgentConfig, RunContext, OutputType
from clarion.logging import configure_logging, bind_context, clear_context
from clarion.agent_config import load_agent_config, ConfigValidationError
from clarion.cron_scheduler import CronScheduler
from clarion.cron_state import load_cron_state, CronJob

# Layer 1
from clarion.tools.executor import ToolExecutor
from clarion.llm_client import OpenAIStreamingClient
from clarion.background_tasks import BackgroundTaskManager

# Layer 2
from clarion.agent_runner import run_agent, new_run_id

# Layer 4
from clarion.adapters.telegram import TelegramAdapter
```

---

## Module: `agent_registry.py`

**Purpose:** Scans the `agents/` directory, loads and validates all
agent configs, maintains the active registry in memory. Handles
re-registration when configs change.

**Source:** New.

### Public API

```python
class AgentRegistry:
    """In-memory registry of all configured agents.

    Scans agents/ directory at startup, watches for changes.
    Maintains last-valid config for each agent — if an edit to
    agent.yaml is invalid, the previous valid config continues
    to be used (with an error logged).
    """

    def __init__(
        self,
        agents_dir: Path,
        templates_dir: Path,
        data_root: Path,
    ) -> None: ...

    def scan(self) -> None:
        """Scan agents/ directory and register all valid agents."""

    def get(self, agent_id: str) -> AgentConfig | None:
        """Get the current config for an agent, or None."""

    def all_agents(self) -> dict[str, AgentConfig]:
        """Return all registered agents."""

    def reload_agent(self, agent_id: str) -> AgentConfig | None:
        """Re-read and re-validate an agent's config.

        If the new config is valid, update the registry.
        If invalid, keep the old config and log an error.
        Returns the active config (old or new).
        """

    def reload_mission(self, agent_id: str) -> str | None:
        """Re-read an agent's mission.md from disk.

        Returns the updated mission text, or None if not found.
        """

    def remove_agent(self, agent_id: str) -> None:
        """Unregister an agent (directory was removed)."""
```

### Key behaviors

1. **Startup scan:** Walk `agents/` dir. For each subdirectory containing
   `agent.yaml`, call `load_agent_config()`. Valid agents are registered.
   Invalid ones are logged as errors and skipped.

2. **Last-valid config preservation:** The registry stores the last valid
   `AgentConfig` per agent. If `agent.yaml` is edited to an invalid state,
   the agent keeps running on its previous config. The error is logged
   clearly. This follows the nginx pattern: test before apply, don't
   break what's working.

3. **Mission hot-reload:** `mission.md` is re-read from disk at the start
   of each run (in the daemon's run assembly, not in the registry). The
   registry provides `reload_mission()` as a convenience but the daemon
   can also just read the file directly.

4. **No persistence:** The registry is entirely in-memory. On restart,
   it rescans from disk. The filesystem is the source of truth.

### Tests

- Test scan finds valid agents
- Test scan skips invalid agents with error log
- Test reload_agent with valid edit → config updated
- Test reload_agent with invalid edit → old config preserved
- Test remove_agent → agent gone from registry

---

## Module: `daemon.py`

**Purpose:** The always-on process. Manages the lifecycle: scan agents,
register schedules, fire runs, handle rescheduling, watch for changes.

**Source:** New.

### Architecture

```
clarion daemon
  └── AgentRegistry          # knows all configured agents
  └── CronScheduler          # fires runs when due
  └── BackgroundTaskManager   # concurrency semaphore, timeouts
  └── FileWatcher            # watches agents/ for changes
        │
        ├── asyncio Task: scheduler tick loop
        ├── asyncio Task: file watcher loop
        └── asyncio Tasks: agent runs (spawned on schedule)
```

### Public API

```python
class Daemon:
    """The Clarion daemon — runs agents on their schedules."""

    def __init__(
        self,
        *,
        agents_dir: Path,
        templates_dir: Path,
        data_root: Path,
        max_concurrent_runs: int = 5,
    ) -> None: ...

    async def start(self) -> None:
        """Start the daemon. Runs until interrupted."""

    async def shutdown(self) -> None:
        """Graceful shutdown. Wait for in-flight runs to complete."""
```

### Startup sequence

```python
async def start(self):
    # 1. Scan agents/ directory
    self._registry.scan()
    log.info("daemon.scan_complete", agents=len(self._registry.all_agents()))

    # 2. Register schedules with CronScheduler
    for agent_id, config in self._registry.all_agents().items():
        self._register_schedule(agent_id, config)

    # 3. Start file watcher
    self._watcher_task = asyncio.create_task(self._watch_files())

    # 4. Start scheduler tick loop
    self._scheduler_task = asyncio.create_task(self._scheduler.run())

    # 5. Wait for shutdown signal
    await self._shutdown_event.wait()

    # 6. Graceful shutdown
    await self.shutdown()
```

### Run assembly

When the scheduler fires a run:

```python
async def _fire_run(self, agent_id: str) -> None:
    config = self._registry.get(agent_id)
    if config is None:
        log.warning("daemon.fire_skip", agent_id=agent_id, reason="not registered")
        return

    # Read mission fresh from disk (hot-reload)
    workspace = self._data_root / "agents" / agent_id
    mission_path = workspace / "mission.md"
    if not mission_path.exists():
        log.error("daemon.fire_skip", agent_id=agent_id, reason="no mission.md")
        return
    mission_md = mission_path.read_text()

    # Assemble RunContext
    context = RunContext(
        agent_id=agent_id,
        run_id=new_run_id(),
        config=config,
        mission_md=mission_md,
        workspace_root=str(workspace),
        trigger="scheduled",
        current_datetime=datetime.now(UTC),
    )

    # Spawn as background task
    await self._task_manager.spawn(
        self._execute_run(context),
        name=f"run-{agent_id}-{context.run_id}",
        timeout_s=config.resources.run_timeout_seconds,
    )
```

```python
async def _execute_run(self, context: RunContext) -> None:
    """Execute a single agent run in a background task."""
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

    # Handle agent-initiated rescheduling from cron side effects
    # (The executor's commit_turn returns cron registrations;
    #  those are surfaced through the AgentRun or a callback)
    log.info(
        "daemon.run_complete",
        agent_id=context.agent_id,
        run_id=context.run_id,
        status=result.status.value,
    )
```

### File watching

Use the `watchfiles` package (or `watchdog`) to monitor the `agents/`
directory for changes:

```python
async def _watch_files(self) -> None:
    """Watch agents/ directory for config and mission changes."""
    import watchfiles

    async for changes in watchfiles.awatch(self._agents_dir):
        for change_type, path in changes:
            path = Path(path)

            if path.name == "agent.yaml":
                agent_id = path.parent.name
                if change_type == watchfiles.Change.deleted:
                    self._unregister_agent(agent_id)
                else:
                    self._handle_config_change(agent_id)

            # mission.md changes don't need handling here —
            # mission is read fresh at the start of each run
```

Add `watchfiles` to pyproject.toml dependencies when implementing Phase 2.

### Agent-initiated rescheduling

When an agent calls the `cron` tool to schedule a follow-up run, the
cron registration is a side effect from `ToolExecutor.commit_turn()`.
The daemon needs a way to receive these registrations.

Two approaches:

1. **Callback injection:** The daemon passes a callback to the tool
   executor that receives cron side effects after each turn commit.
   The callback registers the new job with the CronScheduler.

2. **Post-run inspection:** After `run_agent()` completes, the daemon
   reads the agent's cron state from disk and syncs with the
   CronScheduler. Simpler but introduces a delay.

Recommended: approach 2 (post-run inspection) for simplicity. The cron
tool already writes state to disk via `cron_state.py` during the run.
After `run_agent()` returns, the daemon re-reads the agent's cron state
from `data/agents/<id>/cron/` and syncs any new jobs with the
CronScheduler. This avoids changing `run_agent()`'s return type or
threading callbacks through the executor.

The slight delay (cron state read after run completes, not during) is
acceptable because self-scheduled runs are at minimum minutes away, not
seconds. If real-time scheduling becomes necessary, refactor to approach
1 by adding a `cron_side_effects: list[CronJob]` field to `AgentRun`.

### Run frequency enforcement

The daemon enforces `max_runs_per_day` and
`max_self_scheduled_runs_per_day` at the scheduling level.

This requires a helper in `agent_state.py` (add when implementing
Phase 2):

```python
# In agent_state.py — add this function
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
```

Then the daemon uses it:

```python
def _can_run(self, agent_id: str, trigger: str) -> bool:
    """Check if the agent has budget for another run today."""
    workspace = self._data_root / "agents" / agent_id
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    config = self._registry.get(agent_id)
    if config is None:
        return False

    total_today = count_runs_since(workspace, since=today_start)
    if total_today >= config.resources.max_runs_per_day:
        return False

    if trigger == "self_scheduled":
        self_today = count_runs_since(
            workspace, since=today_start, trigger_filter="self_scheduled"
        )
        if self_today >= config.resources.max_self_scheduled_runs_per_day:
            return False

    return True
```

### Graceful shutdown

On SIGINT/SIGTERM:

1. Stop accepting new runs
2. Cancel the file watcher
3. Cancel the scheduler tick loop
4. Wait for in-flight runs to complete (with a grace period timeout)
5. Exit

```python
async def shutdown(self) -> None:
    log.info("daemon.shutdown_start")
    self._watcher_task.cancel()
    self._scheduler_task.cancel()
    await self._task_manager.shutdown()
    log.info("daemon.shutdown_complete")
```

### Tests

- Test startup scan registers valid agents
- Test scheduler tick fires run when due
- Test concurrent run limit enforced by BackgroundTaskManager
- Test max_runs_per_day enforcement
- Test config change triggers re-registration
- Test invalid config change preserves old config
- Test agent directory removal unregisters agent
- Test graceful shutdown waits for in-flight runs
- Test agent-initiated reschedule is picked up

---

## CLI addition: `clarion daemon`

Add to `cli.py`:

```python
@app.command()
def daemon(
    max_concurrent: int = typer.Option(
        5,
        "--max-concurrent",
        help="Maximum concurrent agent runs",
    ),
    json_logs: bool = typer.Option(
        True,
        "--json-logs/--no-json-logs",
        help="JSON log output (default for daemon)",
    ),
) -> None:
    """Start the Clarion daemon. Runs until interrupted."""
    import signal
    from clarion.logging import configure_logging
    from clarion.daemon import Daemon

    configure_logging(json=json_logs, level="INFO")

    repo_root = _find_repo_root()
    d = Daemon(
        agents_dir=repo_root / "agents",
        templates_dir=repo_root / "templates",
        data_root=_data_root(),
        max_concurrent_runs=max_concurrent,
    )

    loop = asyncio.new_event_loop()

    def _handle_signal():
        loop.create_task(d.shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _handle_signal)

    try:
        loop.run_until_complete(d.start())
    finally:
        loop.close()
```

---

## systemd unit (for deployment)

```ini
# /etc/systemd/system/clarion.service
[Unit]
Description=Clarion Intelligence Platform
After=network.target

[Service]
Type=simple
User=clarion
Group=clarion
WorkingDirectory=/opt/clarion
ExecStartPre=/opt/clarion/.venv/bin/clarion health
ExecStart=/opt/clarion/.venv/bin/clarion daemon
Restart=on-failure
RestartSec=10

# Resource limits
MemoryMax=2G
CPUQuota=200%

# Environment
EnvironmentFile=/opt/clarion/.env

[Install]
WantedBy=multi-user.target
```

Note: `ExecStartPre=clarion health` ensures the environment is valid
before the daemon starts. If health check fails, systemd won't start
the service.

---

## Additional dependency

Add to pyproject.toml when implementing Phase 2:

```toml
"watchfiles>=1.0",
```

---

## Build order

1. `agent_registry.py` first — the daemon depends on it
2. `daemon.py` second — depends on everything
3. Update `cli.py` with the `daemon` command

---

## Verification

```bash
# Start daemon in foreground
clarion daemon --no-json-logs

# In another terminal, verify agents are registered
# (Check logs for "daemon.scan_complete")

# Wait for a scheduled run to fire, or manually trigger one
# by setting a schedule to run every minute for testing:
# schedule:
#   default: "* * * * *"    # every minute (testing only)

# Verify run completes in daemon logs
# Verify run history in data/agents/<id>/runs/history.jsonl

# Test graceful shutdown
kill -SIGTERM <daemon_pid>
# Daemon should log shutdown and wait for in-flight runs
```
