# Plan 02 — Algorithms (Layer 1)

## Goal

Implement the tool registry, all tool implementations, the LLM client,
and background task management. After this plan, every tool can execute
in isolation, the LLM client can stream responses from any OpenAI-
compatible endpoint, and the tool executor can dispatch and stage
side effects.

This layer depends on foundation (layer 0) only.

---

## Dependencies from layer 0

```python
from clarion.models import (
    AgentConfig, ToolCallRequest, AgentTurn, DeliveryAdapter,
    OutputDefinition, OutputType, ResourceEnvelope,
)
from clarion.boundary_validation import (
    validate_tool_call, validate_tool_result, validate_agent_path,
    validate_url, validate_sql, BoundaryValidationError,
    MAX_FETCH_CONTENT_LEN,
)
from clarion.secret_store import load_secret
from clarion.cron_state import CronJob, load_cron_state, add_job, remove_job, edit_job
from clarion.cancellation import CancellationToken, CancellationError
```

---

## Module: `tool_registry.py`

**Purpose:** Single source of truth for every tool. Each tool is defined
as a `ToolSpec` that co-locates its OpenAI JSON schema, execution policy,
and LLM prompt hint.

**Source:** Adopted from redclaw's `tool_registry.py` pattern. New tool
specs for Clarion.

### Pattern (from redclaw)

```python
from pydantic import BaseModel, ConfigDict


class ToolExecutionPolicy(BaseModel):
    model_config = ConfigDict(frozen=True)
    memoize_duplicate_calls_within_turn: bool = True
    side_effecting: bool = False


class ToolSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    schema: dict          # OpenAI function-calling JSON schema
    policy: ToolExecutionPolicy
    prompt_hint: str      # injected into system prompt
```

### Tools to define

Define a `ToolSpec` for each of these. Reference redclaw's
`tool_registry.py` for the schema structure (OpenAI function format) and
prompt_hint content. Adapt descriptions as needed for Clarion's context.

| Tool | Source for schema | Policy | Notes |
|------|-------------------|--------|-------|
| `current_datetime` | redclaw verbatim | default | No args |
| `web_search` | redclaw verbatim | default | query param |
| `web_fetch` | redclaw verbatim | default | url + mode params |
| `web_extract` | redclaw verbatim | default | url + selector + selector_type |
| `deep_research` | redclaw verbatim | default | question + max_sources |
| `execute_sql` | redclaw verbatim | no-memo, side-effecting | name + sql + params |
| `list_databases` | redclaw verbatim | default | no args |
| `cron` | redclaw verbatim | side-effecting | action + schedule params |
| `write_file` | **new** | side-effecting | path + content |
| `deliver_output` | **new** | side-effecting | output_name + content |

### New tool specs

**write_file:**
```python
ToolSpec(
    name="write_file",
    schema={
        "type": "function",
        "function": {
            "name": "write_file",
            "description": (
                "Write content to a file in your workspace. "
                "Creates the file if it doesn't exist. Use for "
                "saving reports, data exports, or intermediate "
                "results."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative path within your workspace",
                        "maxLength": 256,
                    },
                    "content": {
                        "type": "string",
                        "description": "File content to write",
                        "maxLength": 50000,
                    },
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    policy=ToolExecutionPolicy(side_effecting=True),
    prompt_hint=(
        "Use write_file to save reports, data exports, or intermediate "
        "results to your workspace. Provide a relative path and content."
    ),
)
```

**deliver_output:**
```python
ToolSpec(
    name="deliver_output",
    schema={
        "type": "function",
        "function": {
            "name": "deliver_output",
            "description": (
                "Deliver a named output to its configured channel. "
                "The output name must match one of the outputs "
                "defined in your run context."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "output_name": {
                        "type": "string",
                        "description": "Name of the output to deliver (must match run context)",
                        "maxLength": 64,
                    },
                    "content": {
                        "type": "string",
                        "description": "The output content to deliver",
                        "maxLength": 50000,
                    },
                },
                "required": ["output_name", "content"],
                "additionalProperties": False,
            },
        },
    },
    policy=ToolExecutionPolicy(
        memoize_duplicate_calls_within_turn=False,
        side_effecting=True,
    ),
    prompt_hint=(
        "Use deliver_output to send a named output to its configured "
        "delivery channel. The output_name must match one of the outputs "
        "listed in your run context. The platform handles routing — you "
        "don't need to know the delivery channel."
    ),
)
```

### Registry and filtering

```python
TOOL_REGISTRY: tuple[ToolSpec, ...] = (...)  # all specs

_SPEC_BY_NAME: dict[str, ToolSpec] = {s.name: s for s in TOOL_REGISTRY}

def get_spec(name: str) -> ToolSpec | None: ...
def get_tool_schemas(tool_names: list[str]) -> list[dict]: ...
def get_execution_policy(name: str) -> ToolExecutionPolicy: ...
def build_tool_instructions(tool_names: list[str]) -> str: ...
```

Key difference from redclaw: `get_tool_schemas()` and
`build_tool_instructions()` take a `tool_names` filter list. Only tools
in the agent's template are returned. Redclaw returns all tools always.

### Tests

- Test that all tool specs have valid OpenAI schema structure
- Test get_tool_schemas filters correctly
- Test build_tool_instructions only includes hints for listed tools
- Test get_spec returns None for unknown tool

---

## Module: `tools/search.py`

**Purpose:** Web search with DDG → Brave → Perplexity fallback chain.

**Source:** Copy from `~/Documents/Code/redclaw/src/redclaw/tools/search.py`.

### Changes from redclaw

- Change `from redclaw.` imports to `from clarion.`
- Replace `log_event()` calls with structlog:
  `log = structlog.get_logger()` then `log.info(...)` etc.
- The secret_store interface is the same (load_secret for Brave/Perplexity
  API keys), just different import path.

### Public API

```python
async def resolve_search(
    query: str,
    *,
    workspace_root: Path | None = None,
    agent_id: str = "",
) -> str:
    """Search the web. Falls back through providers."""
```

Note: parameter renamed from `user_id` to `agent_id`.

---

## Module: `tools/fetch.py`

**Purpose:** URL fetch with SSRF protection, IP pinning, content
extraction via readability, markdown conversion.

**Source:** Copy from `~/Documents/Code/redclaw/src/redclaw/tools/fetch.py`.

### Changes from redclaw

- Change imports from `redclaw.` to `clarion.`
- Replace log_event with structlog
- Keep `_wrap_untrusted_web_content()` — this is critical for prompt
  injection protection. It wraps fetched content in
  `[UNTRUSTED WEB CONTENT START]...[UNTRUSTED WEB CONTENT END]` tags.
- Handle missing `scrapling` gracefully: if `scrapling` is not installed,
  `stealth` and `browser` modes should fall back to `fast` mode with a
  warning log, not crash.

### Public API

```python
DEFAULT_FETCH_MODE = "fast"
DEFAULT_SELECTOR_TYPE = "css"

async def web_fetch_url(url: str, *, mode: str = "fast", cache=None) -> str: ...
async def web_extract_content(url: str, selector: str, *, selector_type: str = "css") -> str: ...
def _wrap_untrusted_web_content(text: str, max_len: int = ...) -> str: ...
```

---

## Module: `tools/fetch_cache.py`

**Purpose:** Per-agent URL fetch cache backed by SQLite.

**Source:** Copy from `~/Documents/Code/redclaw/src/redclaw/tools/fetch_cache.py`.

### Changes from redclaw

- Change imports
- Replace `user_id` with `agent_id` in constructor and path resolution
- Cache lives at `data/agents/<agent_id>/cache/`

---

## Module: `tools/research.py`

**Purpose:** Deep research — parallel search + fetch + structured report.

**Source:** Copy from `~/Documents/Code/redclaw/src/redclaw/tools/research.py`.

### Changes from redclaw

- Change imports
- Replace `user_id` with `agent_id`
- Replace log_event with structlog

### Public API

```python
DEFAULT_MAX_SOURCES = 5

async def deep_research(
    question: str,
    *,
    max_sources: int = 5,
    workspace_root: Path | None = None,
    agent_id: str = "",
    cache=None,
) -> str:
```

---

## Module: `tools/sql.py`

**Purpose:** Scoped SQLite access. WAL mode, blocked dangerous patterns,
row limits.

**Source:** Copy from `~/Documents/Code/redclaw/src/redclaw/tools/sql.py`.

### Changes from redclaw

- Change imports
- Replace `user_id` with `agent_id`
- Databases live at `data/agents/<agent_id>/databases/`
- Replace log_event with structlog

### Public API

```python
def execute_sql(
    arguments: dict,
    correlation_id: str,
    workspace_root: Path,
    agent_id: str,
) -> dict[str, str]: ...

def execute_list_databases(
    workspace_root: Path,
    agent_id: str,
) -> dict[str, str]: ...
```

Note: redclaw passes a `logger` parameter. Remove it — use
`structlog.get_logger()` inside the function instead.

### Security

- ATTACH, LOAD_EXTENSION blocked via regex
- Parameterized queries via `conn.execute(sql, params)`
- Max 500 rows returned
- 30s execution timeout
- WAL mode for concurrent reads

---

## Module: `tools/cron.py`

**Purpose:** Cron tool — lets the agent manage its own scheduled jobs.

**Source:** Adapted from `~/Documents/Code/redclaw/src/redclaw/tools/cron.py`.

### Changes from redclaw

- Change imports
- Replace `user_id` with `agent_id`
- Update workspace paths

### Public API

```python
@dataclass
class CronEffects:
    registrations: list[CronJob]
    unregistrations: list[str]

def execute_cron(
    arguments: dict,
    correlation_id: str,
    workspace_root: Path,
    agent_id: str,
) -> tuple[dict[str, str], CronEffects]: ...
```

Returns both the tool result (for the LLM) and side effects (for the
executor to stage).

---

## Module: `tools/workspace.py`

**Purpose:** File operations within the agent's workspace.

**Source:** New (inspired by redclaw's `tools/workspace.py` but simpler).

### Implementation

```python
"""Workspace file operations for Clarion agents."""

from __future__ import annotations

from pathlib import Path

from clarion.boundary_validation import validate_agent_path


def execute_write_file(
    arguments: dict[str, object],
    workspace_root: Path,
    agent_id: str,
) -> dict[str, str]:
    """Write content to a file in the agent's workspace."""
    path_str = str(arguments["path"])
    content = str(arguments["content"])

    resolved = validate_agent_path(agent_id, path_str, workspace_root)
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content)

    return {"text": f"Written {len(content)} bytes to {path_str}"}
```

### Constraints

- Max content size: 50KB (validated in boundary_validation)
- Path must resolve within `data/agents/<agent_id>/`
- Creates parent directories automatically
- Overwrites existing files (not append)

---

## Module: `tools/deliver_output.py`

**Purpose:** The tool the agent calls to produce outputs. Routes to the
appropriate delivery adapter based on the output definition.

**Source:** New.

### Implementation

```python
"""Output delivery tool for Clarion agents.

The agent calls deliver_output with an output_name and content.
The tool looks up the OutputDefinition from the agent config,
finds the appropriate DeliveryAdapter, and delivers.
"""

from __future__ import annotations

import structlog

from clarion.models import AgentConfig, DeliveryAdapter, OutputType

log = structlog.get_logger()


async def execute_deliver_output(
    arguments: dict[str, object],
    agent_config: AgentConfig,
    delivery_adapters: dict[OutputType, DeliveryAdapter],
    correlation_id: str,
) -> dict[str, str]:
    """Deliver a named output to its configured channel."""
    output_name = str(arguments["output_name"])
    content = str(arguments["content"])

    # Find the output definition
    output_def = next(
        (o for o in agent_config.outputs if o.name == output_name),
        None,
    )
    if output_def is None:
        available = [o.name for o in agent_config.outputs]
        return {
            "text": f"Unknown output: {output_name!r}. "
                    f"Available: {available}"
        }

    adapter = delivery_adapters.get(output_def.type)
    if adapter is None:
        return {
            "text": f"No delivery adapter configured for "
                    f"output type: {output_def.type.value}"
        }

    try:
        result = await adapter.deliver(
            destination=output_def.destination,
            content=content,
            output_name=output_name,
        )
        log.info(
            "deliver_output.success",
            output_name=output_name,
            output_type=output_def.type.value,
            correlation_id=correlation_id,
        )
        return {"text": result}
    except Exception as exc:
        log.error(
            "deliver_output.error",
            output_name=output_name,
            error=str(exc),
            correlation_id=correlation_id,
        )
        return {"text": f"Delivery failed: {exc}"}
```

### Key design

- The agent is channel-agnostic: it calls deliver_output with a name,
  the platform routes it.
- DeliveryAdapter is a Protocol from models.py — dependency inversion.
- delivery_adapters dict is injected by whoever creates the ToolExecutor
  (CLI or daemon).
- If no adapter is configured for an output type, the tool returns a
  clear error (doesn't crash the run).

---

## Module: `tools/executor.py`

**Purpose:** Dispatch facade, turn staging, and execution policies.
Routes tool calls to the correct implementation.

**Source:** Heavily adapted from
`~/Documents/Code/redclaw/src/redclaw/tools/executor.py`.

### What to keep from redclaw

- **Turn staging pattern:** `start_turn()`, `commit_turn()`,
  `discard_turn()`. Side effects are staged during a turn and committed
  atomically.
- **Duplicate call memoization:** Within a turn, identical tool calls
  (same name + same arguments) return the cached result instead of
  re-executing.
- **Execution policy enforcement:** Check `ToolExecutionPolicy` before
  executing.
- **validate_tool_call / validate_tool_result** boundary checks.

### What to change

- **Replace dispatch table** entirely. Remove all redclaw-specific tools
  (note_save, note_search, file_update, credential_setup, media tools,
  transcribe, documents). Add Clarion's tools.
- **Constructor takes different deps:**

```python
class ToolExecutor:
    def __init__(
        self,
        *,
        agent_id: str,
        agent_config: AgentConfig,
        workspace_root: Path,
        delivery_adapters: dict[OutputType, DeliveryAdapter] | None = None,
        schedule_timezone: str = "UTC",
    ) -> None:
        self._agent_id = agent_id
        self._agent_config = agent_config
        self._workspace_root = workspace_root
        self._delivery_adapters = delivery_adapters or {}
        self._schedule_timezone = schedule_timezone
        # Create FetchCache for this agent's workspace
        self._fetch_cache: FetchCache | None = None
        try:
            self._fetch_cache = FetchCache(workspace_root, agent_id)
        except Exception:
            structlog.get_logger().warning("fetch_cache_init_failed")
```

- **Side effects type** — Clarion's TurnSideEffects:

```python
@dataclass
class TurnSideEffects:
    cron_registrations: list[CronJob]
    cron_unregistrations: list[str]
    outputs_delivered: list[str]  # output names

    @staticmethod
    def empty() -> TurnSideEffects: ...
```

### Dispatch table

All arguments shown explicitly. `self._workspace_root`, `self._agent_id`,
`self._fetch_cache` etc. are instance attributes from the constructor.

```python
async def _dispatch(self, name, arguments, correlation_id):
    from clarion.tools import cron, deliver_output, fetch, research, search, sql, workspace

    if name == "current_datetime":
        import zoneinfo
        tz_name = self._schedule_timezone
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            tz = UTC
            tz_name = "UTC"
        now = datetime.now(tz)
        return {"text": now.strftime(f"%A, %B %d, %Y — %I:%M %p ({tz_name})")}

    elif name == "web_search":
        text = await search.resolve_search(
            str(arguments["query"]),
            workspace_root=self._workspace_root,
            agent_id=self._agent_id,
        )
        return {"text": fetch._wrap_untrusted_web_content(text)}

    elif name == "web_fetch":
        fetch_mode = str(arguments.get("mode", fetch.DEFAULT_FETCH_MODE))
        text = await fetch.web_fetch_url(
            str(arguments["url"]),
            mode=fetch_mode,
            cache=self._fetch_cache,
        )
        return {"text": fetch._wrap_untrusted_web_content(text, max_len=MAX_FETCH_CONTENT_LEN)}

    elif name == "web_extract":
        selector_type = str(arguments.get("selector_type", fetch.DEFAULT_SELECTOR_TYPE))
        text = await fetch.web_extract_content(
            str(arguments["url"]),
            str(arguments["selector"]),
            selector_type=selector_type,
        )
        return {"text": fetch._wrap_untrusted_web_content(text, max_len=MAX_FETCH_CONTENT_LEN)}

    elif name == "deep_research":
        max_sources = int(str(arguments.get("max_sources", research.DEFAULT_MAX_SOURCES)))
        text = await research.deep_research(
            str(arguments["question"]),
            max_sources=max_sources,
            workspace_root=self._workspace_root,
            agent_id=self._agent_id,
            cache=self._fetch_cache,
        )
        return {"text": fetch._wrap_untrusted_web_content(text, max_len=MAX_FETCH_CONTENT_LEN)}

    elif name == "execute_sql":
        return sql.execute_sql(
            arguments,
            correlation_id,
            self._workspace_root,
            self._agent_id,
        )

    elif name == "list_databases":
        return sql.execute_list_databases(
            self._workspace_root,
            self._agent_id,
        )

    elif name == "cron":
        result, effects = cron.execute_cron(
            arguments,
            correlation_id,
            self._workspace_root,
            self._agent_id,
        )
        target = self._target()
        target.cron_registrations.extend(effects.registrations)
        target.cron_unregistrations.extend(effects.unregistrations)
        return result

    elif name == "write_file":
        return workspace.execute_write_file(
            arguments,
            self._workspace_root,
            self._agent_id,
        )

    elif name == "deliver_output":
        result = await deliver_output.execute_deliver_output(
            arguments,
            self._agent_config,
            self._delivery_adapters,
            correlation_id,
        )
        output_name = str(arguments.get("output_name", ""))
        if output_name and "failed" not in result.get("text", "").lower():
            self._target().outputs_delivered.append(output_name)
        return result

    else:
        raise RuntimeError(f"unknown tool: {name}")
```

### Tests

- Test dispatch routes to correct tool (mock tool implementations)
- Test turn staging: start → execute → commit returns side effects
- Test discard_turn clears staged effects
- Test memoization: same call twice in one turn returns cached result
- Test non-memoized tools (execute_sql) always re-execute
- Test unknown tool raises RuntimeError

---

## Module: `llm_client.py`

**Purpose:** OpenAI-compatible LLM client with SSE streaming. Model-
generic — works with any provider that speaks the OpenAI chat completions
format.

**Source:** Adapted from `~/Documents/Code/redclaw/src/redclaw/openai_client.py`
and `~/Documents/Code/redclaw/src/redclaw/llm_client.py`.

### Key change: simpler interface

Redclaw's LlmClient takes `AgentContextInput` (which bundles SOUL.md,
USER.md, etc.) and internally calls `build_system_prompt()`. Clarion's
client is dumber — it takes pre-built messages and tool schemas:

```python
from typing import Protocol


class LlmClient(Protocol):
    async def respond(
        self,
        *,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        model: str,
        max_tokens: int,
    ) -> AgentTurn: ...


class LlmTimeoutError(TimeoutError):
    """Raised when an LLM call exceeds the timeout."""


class OpenAIStreamingClient:
    """Native OpenAI-compatible streaming client.

    Works with any provider that implements /chat/completions:
    OpenAI, DeepSeek, OpenRouter, Anthropic (via proxy), Ollama, etc.
    """

    def __init__(
        self,
        *,
        base_url: str = "",    # from LLM_BASE_URL env var if empty
        api_key: str = "",     # from LLM_API_KEY env var if empty
        timeout_s: float = 90.0,
    ) -> None: ...

    async def respond(
        self,
        *,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        model: str,
        max_tokens: int,
    ) -> AgentTurn: ...
```

### What to keep from redclaw's openai_client.py

- `_stream_sse_response()` — the SSE parser that accumulates content and
  tool_calls from streaming deltas. This is the most valuable code.
  Copy it nearly verbatim.
- `_parse_tool_calls_from_response()` — parses accumulated tool_calls
  into ToolCallRequest objects. Copy verbatim.
- Retry on blank response (one retry). Copy the pattern.
- `LlmTimeoutError` with proper asyncio.timeout handling. Copy.
- `_PARSE_FAILURE_TEXT` fallback. Copy.

### What to change

- **Remove** `_build_messages()` — the caller (agent_runner) builds
  messages now. The client receives them pre-built.
- **Remove** imports of `prompt_assembly`, `tool_schemas`,
  `AgentContextInput`
- **Simplify** `respond()` to just construct the request body from the
  provided arguments and stream the response.
- **Remove** `reasoning_content` handling (DeepSeek-specific). Keep the
  code path but don't break if the field is absent. If the field is
  present, include it in AgentTurn for models that support it.
  Actually — check if AgentTurn needs a reasoning_content field. For now,
  leave it out of the Pydantic model since it's not needed for Phase 1.
- **Remove** `ensure_openai_generic_env()` — Clarion reads env vars
  directly in __init__.

### Request body construction

```python
request_body: dict[str, Any] = {
    "model": model,
    "messages": [
        {"role": "system", "content": system_prompt},
        *messages,
    ],
    "stream": True,
    "max_tokens": max_tokens,
}
# Only include tools key if tools are provided.
# Some OpenAI-compatible endpoints error on an empty tools array.
if tools:
    request_body["tools"] = tools
```

### Environment variables

- `LLM_BASE_URL` — the API endpoint base URL
- `LLM_API_KEY` — the API key
- Constructor reads these if not provided explicitly

### Tests

- Test SSE parsing with mock response stream (success case)
- Test SSE parsing with tool_calls in response
- Test blank response triggers retry
- Test timeout raises LlmTimeoutError
- Test parse failure returns AgentTurn with parse_failure=True

---

## Module: `background_tasks.py`

**Purpose:** Asyncio background task manager with semaphore for
concurrency control and timeout enforcement.

**Source:** Copy from `~/Documents/Code/redclaw/src/redclaw/background_tasks.py`.

### Changes from redclaw

- Change imports (structlog instead of structured_logging)
- This module is ~152 lines and completely generic. Minimal changes.

### Public API

```python
class BackgroundTaskManager:
    def __init__(self, *, max_concurrent: int = 5, logger=None): ...
    async def spawn(self, coro, *, name: str = "", timeout_s: float = 0): ...
    async def shutdown(self): ...
```

Not strictly needed for Phase 1 (single run, no daemon), but including
it now since it's a trivial port and Phase 2 needs it immediately.

---

## Build order within this layer

1. `tool_registry.py` — defines schemas other modules reference
2. `tools/search.py`, `tools/fetch.py`, `tools/fetch_cache.py` — in parallel
3. `tools/research.py` — depends on search + fetch
4. `tools/sql.py` — independent
5. `tools/cron.py` — depends on cron_state
6. `tools/workspace.py` — independent
7. `tools/deliver_output.py` — depends on models (DeliveryAdapter)
8. `tools/executor.py` — depends on all tool modules
9. `llm_client.py` — independent
10. `background_tasks.py` — independent

---

## Verification

```bash
# All imports work
uv run python -c "
from clarion.tool_registry import get_tool_schemas, build_tool_instructions
from clarion.tools.executor import ToolExecutor
from clarion.llm_client import OpenAIStreamingClient
from clarion.background_tasks import BackgroundTaskManager
print('All algorithms imports OK')
"

# Tests pass
uv run pytest tests/ -x -v
```
