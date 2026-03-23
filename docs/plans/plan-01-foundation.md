# Plan 01 — Foundation (Layer 0)

## Goal

Implement all foundation modules. After this plan, the core types exist,
logging works, agent configs can be loaded and validated, and the
infrastructure primitives (cron state, cancellation, boundary validation,
secrets, run history) are in place.

No module in this layer imports from any higher layer.

---

## Dependencies from external packages

- `pydantic` — model validation
- `structlog` — structured logging
- `croniter` — cron expression parsing/validation
- `pyyaml` — YAML parsing for agent configs and templates

---

## Module: `models.py`

**Purpose:** Core Pydantic models used throughout the system. All system
types flow from here. No business logic — just data shapes.

**Source:** New (replaces the dataclass sketch from earlier design work).

### Types to define

```python
from __future__ import annotations

import re
from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class OutputTrigger(Enum):
    SCHEDULED = "scheduled"
    AGENT_DECIDES = "agent_decides"


class OutputType(Enum):
    TELEGRAM = "telegram"
    EMAIL = "email"           # future
    WEBHOOK = "webhook"       # future


class OutputDefinition(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str = ""
    trigger: OutputTrigger
    type: OutputType
    destination: str
    format: str = ""


class ResourceEnvelope(BaseModel):
    model_config = ConfigDict(frozen=True)

    max_runs_per_day: int = 12
    max_search_calls_per_run: int = 30
    max_fetch_calls_per_run: int = 15
    max_deep_research_calls_per_run: int = 3
    max_sql_calls_per_run: int = 50
    run_timeout_seconds: int = 600
    max_database_mb: int = 1000
    max_self_scheduled_runs_per_day: int = 6


class AgentConfig(BaseModel):
    """Parsed and validated agent config. What the platform works with
    at runtime. The agent (LLM) never sees this directly."""

    model_config = ConfigDict(frozen=True)

    agent_id: str               # derived from directory name
    name: str                   # human-readable display name
    description: str
    owner: str
    version: int
    template: str
    schedule_cron: str
    schedule_timezone: str
    outputs: list[OutputDefinition]
    database_enabled: bool
    resources: ResourceEnvelope
    tools: list[str]            # resolved from template
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 8192
    base_system_prompt: str = ""


class AgentRun(BaseModel):
    """A single execution of an agent."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    agent_id: str
    started_at: datetime
    status: RunStatus
    trigger: str                # "scheduled", "manual", "self_scheduled"
    completed_at: datetime | None = None
    error: str | None = None
    outputs_produced: list[str] = Field(default_factory=list)
    tool_call_counts: dict[str, int] = Field(default_factory=dict)


class ToolCallRequest(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    id: str = ""


class AgentTurn(BaseModel):
    model_config = ConfigDict(frozen=True)

    text: str | None = None
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    parse_failure: bool = False


class RunContext(BaseModel):
    """Everything the agent runner needs to execute a run.
    Assembled by the CLI or daemon before handing off to agent_runner."""

    model_config = ConfigDict(frozen=True)

    agent_id: str
    run_id: str
    config: AgentConfig
    mission_md: str             # raw contents of mission.md
    workspace_root: str         # path to data/agents/<agent_id>/
    trigger: str
    current_datetime: datetime


class DeliveryAdapter(Protocol):
    """Protocol for output delivery adapters.

    Defined here so both the tool layer (algorithms) and adapter layer
    can reference it without circular imports.
    """

    async def deliver(
        self,
        destination: str,
        content: str,
        output_name: str,
    ) -> str:
        """Deliver content to destination. Returns confirmation message."""
        ...
```

### Key decisions

- All models use `ConfigDict(frozen=True)` for immutability.
- `OutputType` includes `TELEGRAM` (Phase 1), `EMAIL` and `WEBHOOK` (future).
  No `WRITE_FILE` — write_file is a separate tool, not an output channel.
- `DeliveryAdapter` protocol lives here so tools/ and adapters/ can both
  reference it. This is dependency inversion: the tool layer depends on
  the protocol, not the concrete adapter.
- `AgentConfig` (not `AgentCharter`) — renamed per naming decision.
- `mission_md` (not `brief_md`) in RunContext — renamed per naming decision.

### Tests

- Test that all models can be instantiated with valid data
- Test that frozen models reject mutation
- Test that enums serialize/deserialize correctly
- Test ResourceEnvelope defaults

---

## Module: `logging.py`

**Purpose:** Configure structlog for JSON-line structured logging with
correlation IDs.

**Source:** New (replaces redclaw's hand-rolled `structured_logging.py`).

### Implementation

```python
"""Structured logging configuration for Clarion.

Call configure_logging() once at startup. Then use
structlog.get_logger() throughout the codebase.
"""

from __future__ import annotations

import structlog


def configure_logging(*, json: bool = True, level: str = "INFO") -> None:
    """Configure structlog processors and output format.

    Args:
        json: If True, output JSON lines (production). If False, output
              human-readable colored output (development).
        level: Minimum log level.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            structlog.get_level_from_name(level),
        ),
        cache_logger_on_first_use=True,
    )


def bind_context(**kwargs: object) -> None:
    """Bind key-value pairs to the current context (asyncio-safe).

    Use this to set correlation IDs, agent_id, run_id, etc. at the
    start of a run. All subsequent log calls in that async context
    will include these fields.
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all context bindings."""
    structlog.contextvars.clear_contextvars()
```

### Usage pattern

```python
import structlog
from clarion.logging import configure_logging, bind_context

configure_logging(json=False)  # dev mode
log = structlog.get_logger()

bind_context(agent_id="example-research", run_id="run_abc123")
log.info("agent_run.start", trigger="manual")
# Output includes agent_id and run_id automatically
```

### Why structlog over redclaw's structured_logging.py

Redclaw's module does the same thing manually (~280 lines): JSON formatting,
correlation IDs via `enrich()`, `timed_op()` context manager. Structlog
provides all of this out of the box with better async support via
contextvars. No reason to maintain custom code.

### Tests

- Test that configure_logging runs without error in both json and dev modes
- Test that bind_context adds fields to log output

---

## Module: `cancellation.py`

**Purpose:** Asyncio cancellation primitive. Lightweight cooperative
cancellation for long-running operations.

**Source:** Copy verbatim from `~/Documents/Code/redclaw/src/redclaw/cancellation.py`.

### Changes from redclaw

None. This module is ~46 lines, completely generic, no redclaw-specific
imports. Copy it exactly, changing only the module docstring package
reference from `redclaw` to `clarion`.

### Public API

```python
class CancellationToken:
    cancelled: bool
    def abort(self) -> None: ...

class CancellationError(Exception): ...
```

### Tests

- Test that CancellationToken starts uncancelled
- Test that abort() sets cancelled to True
- Test that CancellationError is raisable

---

## Module: `boundary_validation.py`

**Purpose:** Input sanitization, path validation, and security boundaries.
All tool calls pass through this before execution.

**Source:** Adapted from `~/Documents/Code/redclaw/src/redclaw/boundary_validation.py`.

### What to keep from redclaw

- All constants: `MAX_QUERY_LEN`, `MAX_URL_LEN`, `MAX_SQL_LEN`,
  `MAX_FETCH_CONTENT_LEN`, `FETCH_MODES`, `EXTRACT_SELECTOR_TYPES`,
  `BLOCKED_SQL_PATTERNS`, etc.
- `validate_url()` — URL format and SSRF checks
- `validate_sql()` — blocks ATTACH, LOAD_EXTENSION, etc.
- `validate_tool_call()` — dispatches per-tool validation
- `validate_tool_result()` — size-limits tool output
- `BoundaryValidationError` exception class
- SSRF protection: `is_private_ip()`, DNS resolution checks

### What to change

- **Remove** `validate_user_path()` — redclaw concept, not needed
- **Replace** `validate_agent_path()` with a new version scoped to
  `data/agents/<agent_id>/`:

```python
def validate_agent_path(agent_id: str, path: str, workspace_root: Path) -> Path:
    """Resolve and validate that a path is within the agent's workspace.

    Raises BoundaryValidationError if the path escapes the workspace.
    """
    resolved = (workspace_root / path).resolve()
    workspace_resolved = workspace_root.resolve()
    if not str(resolved).startswith(str(workspace_resolved)):
        raise BoundaryValidationError(
            f"Path {path!r} escapes agent workspace"
        )
    return resolved
```

- **Remove** `parse_inbound_payload()` / `InboundMessage` validation —
  Clarion agents don't receive inbound messages
- **Remove** `CREDENTIAL_SETUP_TOOLS` constant — no credential_setup tool
  in Clarion
- **Add** validation for `deliver_output` tool arguments (output_name as
  string, content within size limit)
- **Add** validation for `write_file` tool arguments
- **Add** validation for `list_databases` tool arguments (no arguments,
  but validate the call)
- **Update** `validate_tool_call()` dispatch to cover Clarion's tool set

### Environment variable substitution

Add a utility function for expanding `${VAR}` in config strings:

```python
import os
import re

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")

def expand_env_vars(value: str) -> str:
    """Expand ${VAR} references in a string using os.environ.

    Raises BoundaryValidationError if a referenced variable is not set.
    """
    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        val = os.environ.get(var_name)
        if val is None:
            raise BoundaryValidationError(
                f"Environment variable {var_name!r} is not set"
            )
        return val
    return _ENV_VAR_PATTERN.sub(_replace, value)
```

This is used by `agent_config.py` when loading output destinations.

### Tests

- Test path validation: valid paths pass, traversal attacks rejected
- Test SQL validation: ATTACH blocked, normal SQL passes
- Test URL validation: valid URLs pass, private IPs rejected
- Test env var expansion: valid vars expanded, missing vars raise error
- Test tool call validation for each Clarion tool

---

## Module: `secret_store.py`

**Purpose:** Per-agent credential storage. File-per-credential with
0600 permissions.

**Source:** Adapted from `~/Documents/Code/redclaw/src/redclaw/secret_store.py`.

### What to change from redclaw

- Replace `user_id` parameter with `agent_id` throughout
- Update path resolution: secrets live at `data/agents/<agent_id>/.secrets/`
- Update `KNOWN_TOOLS` to Clarion's credential set:
  - `brave_search` — Brave Search API key
  - `perplexity` — Perplexity API key
  - (future: others as needed)

### Public API

```python
def store_secret(agent_id: str, tool_name: str, value: str, workspace_root: Path) -> None:
    """Store a credential. Creates .secrets/ dir if needed. Sets 0600 perms."""

def load_secret(agent_id: str, tool_name: str, workspace_root: Path) -> str | None:
    """Load a credential, or None if not set."""
```

### Tests

- Test store + load roundtrip
- Test load returns None for missing secret
- Test file permissions are 0600 (on Unix)

---

## Module: `cron_state.py`

**Purpose:** Persistent per-agent cron job state. Stores job definitions
and fire history to a JSON file in the agent's cron/ directory.

**Source:** Adapted from `~/Documents/Code/redclaw/src/redclaw/cron_state.py`.

### What to change from redclaw

- Replace all `user_id` parameters with `agent_id`
- Update path resolution: cron state lives at `data/agents/<agent_id>/cron/`
- Keep everything else: `CronJob` dataclass, `load_cron_state()`,
  `add_job()`, `edit_job()`, `mark_fired()`, `remove_job()`, `advance()`
  for recurring jobs with exponential backoff

### Key types (from redclaw)

```python
@dataclass
class CronJob:
    job_id: str
    name: str
    kind: str           # "at", "every", "cron"
    at: str | None       # ISO 8601 for one-time
    every_ms: int | None # interval for recurring
    cron_expr: str | None # 5-field cron
    enabled: bool
    created_at: str
    last_fired: str | None
    next_fire: str | None
```

Note: cron_state.py uses plain dataclasses (not Pydantic) because it's
ported from redclaw. This is fine — it's an internal persistence module,
not a public API boundary.

### Tests

- Test add/remove/edit/list roundtrip
- Test mark_fired updates last_fired and advances next_fire
- Test persistence: save to file, reload, state preserved

---

## Module: `cron_scheduler.py`

**Purpose:** Background scheduler that checks for due cron jobs and
fires callbacks. Runs as an asyncio task in the daemon (Phase 2) but
the module itself is a standalone primitive.

**Source:** Copy verbatim from `~/Documents/Code/redclaw/src/redclaw/cron_scheduler.py`.

### Changes from redclaw

Minimal. This module is ~197 lines and depends only on `croniter` and
`structured_logging`. Changes:

- Import `structlog` instead of `redclaw.structured_logging`
- Replace `log_event()` calls with structlog equivalents:
  `log.info("cron.event_name", field=value)` instead of
  `log_event(logger, event="cron.event_name", field=value)`
- Everything else (CronScheduler class, register(), advance(),
  get_due_jobs(), tick loop) stays the same

### Public API

```python
class CronScheduler:
    def register(self, agent_id: str, job: CronJob, callback) -> None: ...
    def unregister(self, agent_id: str, job_id: str) -> None: ...
    async def tick(self) -> None: ...      # check and fire due jobs
    async def run(self) -> None: ...       # infinite tick loop
```

### Tests

- Test register + tick fires callback when job is due
- Test advance correctly calculates next fire time
- Test unregister removes job from scheduler

---

## Module: `agent_state.py`

**Purpose:** Per-agent run history. Append-only JSONL file at
`data/agents/<agent_id>/runs/history.jsonl`. No platform database needed.

**Source:** New.

### Implementation

```python
"""Per-agent run history — append-only JSONL."""

from __future__ import annotations

import json
from pathlib import Path

from clarion.models import AgentRun


def record_run(run: AgentRun, workspace_root: Path) -> None:
    """Append a completed AgentRun to the agent's run history."""
    runs_dir = Path(workspace_root) / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    history_file = runs_dir / "history.jsonl"
    with open(history_file, "a") as f:
        f.write(run.model_dump_json() + "\n")


def load_run_history(workspace_root: Path, limit: int = 50) -> list[AgentRun]:
    """Load the most recent runs from history, newest first."""
    history_file = Path(workspace_root) / "runs" / "history.jsonl"
    if not history_file.exists():
        return []
    lines = history_file.read_text().strip().split("\n")
    runs = []
    for line in reversed(lines):
        if not line.strip():
            continue
        runs.append(AgentRun.model_validate_json(line))
        if len(runs) >= limit:
            break
    return runs


def last_run(workspace_root: Path) -> AgentRun | None:
    """Return the most recent run, or None if no history."""
    history = load_run_history(workspace_root, limit=1)
    return history[0] if history else None
```

### Tests

- Test record_run creates file and appends JSONL
- Test load_run_history returns runs in reverse order
- Test last_run returns None on empty history
- Test roundtrip: record → load → compare

---

## Module: `agent_config.py`

**Purpose:** Load and validate agent.yaml + resolve template into a
fully populated AgentConfig. Validation happens here so the runtime
can assume the config is valid.

**Source:** New (replaces the charter.py sketch, using Pydantic v2 instead
of hand-rolled validation).

### Implementation outline

```python
"""Agent config loader and validator.

Parses agent.yaml + resolves the referenced template into a fully
populated AgentConfig. The agent (LLM) never sees this module or
its outputs directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from clarion.boundary_validation import expand_env_vars
from clarion.models import (
    AgentConfig,
    OutputDefinition,
    OutputTrigger,
    OutputType,
    ResourceEnvelope,
)


class ConfigValidationError(ValueError):
    """Raised when agent.yaml or template is invalid."""
    pass


def load_agent_config(
    agent_dir: Path,
    agent_id: str,
    templates_dir: Path | None = None,
) -> AgentConfig:
    """Load, validate, and return a fully resolved AgentConfig.

    Args:
        agent_dir: Directory containing agent.yaml
        agent_id: The agent identifier (derived from directory name)
        templates_dir: Where to find templates. Defaults to
                       <repo_root>/templates/

    Raises:
        ConfigValidationError: If agent.yaml or template is invalid
    """
    ...


def load_template(template_name: str, templates_dir: Path) -> dict[str, Any]:
    """Load and parse a template YAML file."""
    ...


def _resolve_resources(template: dict, agent_overrides: dict) -> ResourceEnvelope:
    """Merge template defaults with agent overrides.

    Agent values cannot exceed template maximums.
    Raises ConfigValidationError if an override exceeds the template max.
    """
    ...
```

### Key behaviors

1. **Template resolution:** `agent.yaml` has `template: research`. The
   loader finds `templates/research.yaml`, parses it, and uses its values
   as defaults for tools, model, max_tokens, base_system_prompt, and
   resources.

2. **Resource merging:** Agent can override resource values downward only.
   If agent says `max_search_calls_per_run: 20` and template says `30`,
   the agent gets `20`. If agent says `40`, ConfigValidationError.

3. **Env var expansion:** The `${VAR}` syntax is supported but scoped
   narrowly. Expansion via `expand_env_vars()` from boundary_validation.py
   is applied **only to `OutputDefinition.destination` fields** — not to
   meta.name, description, or other strings. This keeps secrets out of
   version-controlled files without surprising behavior elsewhere.

4. **Cron validation:** The `schedule.default` field is validated as a
   proper cron expression using `croniter.is_valid()`.

5. **Output validation:** Each output must have a valid trigger, type,
   destination, and name.

6. **agent_id from directory:** The `agent_id` is always derived from
   the directory name, never from the YAML contents. `meta.name` is a
   human-readable display name.

### Templates directory resolution

Default: look for `templates/` relative to the repo root. The repo root
is found by walking up from `agent_dir` looking for `architecture.toml`
or `pyproject.toml`. If `templates_dir` is explicitly provided (useful
for testing), use that instead.

### Tests

- Test loading a valid agent.yaml + template → correct AgentConfig
- Test resource override downward → accepted
- Test resource override upward → ConfigValidationError
- Test missing template → ConfigValidationError
- Test invalid cron expression → ConfigValidationError
- Test env var expansion in destination
- Test missing env var → ConfigValidationError
- Test agent_id comes from directory name, not meta.name

---

## Build order within this layer

All foundation modules can be built in parallel since they have minimal
interdependencies, with these exceptions:

1. `models.py` first — everything depends on it
2. `boundary_validation.py` before `agent_config.py` — config loader
   uses `expand_env_vars()`
3. `logging.py` early — used by many modules for debug output

Suggested order:
1. `models.py`
2. `logging.py`
3. `cancellation.py`
4. `boundary_validation.py`
5. `secret_store.py`
6. `cron_state.py`
7. `cron_scheduler.py`
8. `agent_state.py`
9. `agent_config.py`

---

## Verification

After implementing all foundation modules:

```bash
# All imports work
uv run python -c "
from clarion.models import AgentConfig, RunContext, AgentRun
from clarion.logging import configure_logging
from clarion.cancellation import CancellationToken
from clarion.boundary_validation import validate_agent_path, expand_env_vars
from clarion.secret_store import store_secret, load_secret
from clarion.cron_state import load_cron_state, add_job
from clarion.cron_scheduler import CronScheduler
from clarion.agent_state import record_run, load_run_history
from clarion.agent_config import load_agent_config
print('All foundation imports OK')
"

# Tests pass
uv run pytest tests/ -x -v
```
