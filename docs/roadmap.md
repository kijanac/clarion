# Clarion Roadmap

What's been discussed, designed, or partially built but isn't shipped yet.

## Not built but discussed

### Authentication and authorization

No auth exists. Anyone with the server URL can create agents, edit templates, delete data. The plan is a three-tier model:

- **Admin** — can edit templates, manage platform secrets, view all agents
- **Operator** — can create/edit/delete agents, trigger runs, edit missions
- **Viewer** — can see agents, runs, and outputs but not modify anything

Template editing should be locked to admins. Agent creation available to operators. The UI already separates templates from agents in the sidebar, so the permission boundary is natural.

### Webhook trigger type

The trigger model supports it (`TriggerType` enum is extensible), but no implementation exists. The design:

- Agent config declares `type: webhook` with a `path` field
- The API mounts a catch-all route at `/hooks/{path}`
- When a POST hits that path, the event bus emits an event
- The webhook payload is passed to the agent as context in the run

Use cases: form submissions, GitHub PR events, CMS publish hooks, Slack commands.

### Agent output triggers — side effect wiring

The event bus emits `output_produced` events after `deliver_output` runs. Other agents can subscribe to these via `agent_output` triggers. This works end-to-end.

What's missing: when an agent uses the `cron` tool to self-schedule (e.g., "check again in 2 hours"), the cron job is written to the filesystem but never registered with APScheduler. The old `CronScheduler` had a `_sync_cron_state` method that was supposed to handle this but was a no-op. The fix is: after a run completes, read the agent's cron state file and register any new jobs with APScheduler via the event bus.

### Email and webhook output adapters

Only Telegram delivery exists. The `DeliveryAdapter` protocol and `OutputType` enum already support email and webhook, but no implementations exist.

- **Email**: SMTP or a service like Resend/Postmark. The adapter would take a destination email address and send the output as the body.
- **Webhook**: POST the output content as JSON to a URL. Simple to implement — just an httpx POST with the content as the body.

### Dashboard / home view

The UI has no home screen. Landing shows "Select an agent" with no overview. A dashboard would show:

- Agent health summary (how many running, failed, paused)
- Recent activity feed (last N runs across all agents)
- Failed runs requiring attention
- Next scheduled runs
- Platform stats (total runs today, search calls used)

This is a frontend-only feature — the API endpoints already return the data needed.

## Known rough edges

### `list_agents` rescans filesystem on every request

The `GET /api/agents` endpoint iterates the `agents/` directory, parses every `agent.yaml` + its template YAML, reads each agent's run history, and counts today's runs — all on every request. With 10 agents, that's ~30 file reads per page load.

The daemon already maintains an in-memory `AgentRegistry` with all agent configs. When the API runs embedded in the daemon (which it does in production via `--web-port`), `list_agents` should read from the registry instead of rescanning disk. The `_agent_summary` function was already optimized to use `last_run()` + `count_runs_since()` instead of loading 100 runs, but the config loading is still the bottleneck.

For the standalone `clarion web` mode (no daemon), a short TTL cache (5-10 seconds) on the config scan would be sufficient.

### React hooks duplicate fetch boilerplate

All six data-fetching hooks (`use-agents`, `use-agent`, `use-runs`, `use-run-detail`, `use-templates`, `use-template`) repeat the same ~30 lines: `useState` for data/loading/error/tick, `useEffect` with a `cancelled` flag, `.then/.catch/.finally`, and a `refetch` callback via tick counter.

A generic `useFetch<T>(url: string | null)` hook would eliminate this duplication. Each specific hook becomes a one-liner wrapper. This also makes it trivial to add features like retry, stale-while-revalidate, or polling consistently across all hooks.

### No way to edit triggers after agent creation

The wizard lets you configure triggers at creation time, and the `PUT /api/agents/{id}` endpoint accepts `triggers` updates, but the agent detail UI has no trigger editing interface. To change an agent's schedule, you'd have to edit the YAML file on the server or use the API directly.

The fix: add a "Triggers" tab or section in the agent detail view that renders the same `TriggerEditor` component used in the wizard, wired to the PUT endpoint.

### Trash directory grows unbounded

Deleted agents are soft-deleted to `data/trash/` with a timestamp suffix. There's no cleanup mechanism — old trash accumulates indefinitely, including potentially large SQLite databases and run history files.

Options:
- CLI command: `clarion trash purge --older-than 30d`
- Automatic cleanup: daemon periodically removes trash older than a configurable retention period
- UI: show trash contents with a "permanently delete" option

### Agent self-scheduling not wired to APScheduler

When an agent calls the `cron` tool with `action: add`, the job is written to `data/agents/{id}/cron/state.json`. But the daemon doesn't read this file after runs complete, so agent-created cron jobs never actually fire.

The fix: in `daemon._execute_run`, after the run completes, read the cron state file and register any new jobs with APScheduler. Deregistered jobs should be removed. This was the intent of the old `_sync_cron_state` method which was deleted during the trigger system refactor.

### Trigger editor fetches full agent detail for output names

The `AgentOutputFields` component in the trigger editor calls `useAgent(sourceAgentId)` to get the source agent's output list. This loads the full agent detail (mission, runs, config) just to read the `outputs` array.

Options:
- Add a lightweight `GET /api/agents/{id}/outputs` endpoint
- Include output names in the `AgentSummary` response from `list_agents` (already has `outputs_count`, just add the names)

### `load_run_history` reads entire file into memory

`agent_state.load_run_history()` does `history_file.read_text().splitlines()` then reverses the full list, even when `limit=1`. For agents with thousands of runs, this loads the entire multi-megabyte file into memory per call.

For the common `limit=1` case (used by `last_run()`), reading the last line of the file via `seek` from the end would be much more efficient. For the general case, a reverse-line-reader or a fixed-size index file would scale better.
