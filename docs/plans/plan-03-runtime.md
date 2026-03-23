# Plan 03 — Runtime (Layer 2)

## Goal

Implement the agent execution loop and prompt assembly. After this plan,
`run_agent()` can take a RunContext, an LlmClient, and a ToolExecutor,
and execute a complete agent run — the think → act → store → schedule →
sleep loop.

This layer depends on foundation (layer 0) and algorithms (layer 1).

---

## Dependencies from lower layers

```python
# From layer 0
from clarion.models import (
    AgentConfig, AgentRun, AgentTurn, RunContext, RunStatus,
    ResourceEnvelope, OutputTrigger, ToolCallRequest,
)
from clarion.agent_state import record_run
from clarion.logging import bind_context, clear_context

# From layer 1
from clarion.tool_registry import get_tool_schemas, build_tool_instructions
from clarion.tools.executor import ToolExecutor
from clarion.llm_client import LlmClient, LlmTimeoutError
```

---

## Module: `prompt_assembly.py`

**Purpose:** Build the system prompt that the agent receives at the
start of each run. Combines the template's base system prompt, the
agent's mission, and the run context (outputs due, resource limits,
datetime).

**Source:** New (based on the sketch from design discussions).

### Implementation

```python
"""Prompt assembly for Clarion agents.

Builds the system prompt from:
  1. The template's base system prompt (role, tools, behavioral rules)
  2. The agent's mission (domain, goals, output intent)
  3. The run context (outputs due, resource limits, current datetime)
  4. Tool instructions (assembled from the tool registry)

The agent never sees agent.yaml. It sees the assembled prompt.
"""

from __future__ import annotations

from datetime import datetime

from clarion.models import AgentConfig, OutputTrigger, RunContext
from clarion.tool_registry import build_tool_instructions


def build_system_prompt(context: RunContext) -> str:
    """Assemble the full system prompt for an agent run."""
    config = context.config
    sections: list[str] = []

    # 1. Base system prompt from template
    if config.base_system_prompt.strip():
        sections.append(config.base_system_prompt.strip())

    # 2. Agent's mission — loaded from mission.md, injected as-is
    if context.mission_md.strip():
        sections.append(_section("Your Mission", context.mission_md.strip()))

    # 3. Run context — outputs due, current time, trigger
    sections.append(_build_run_context(context))

    # 4. Tool instructions — from tool registry prompt_hints
    tool_instructions = build_tool_instructions(config.tools)
    if tool_instructions.strip():
        sections.append(_section("Tool Usage", tool_instructions.strip()))

    return "\n\n".join(sections)
```

### Run context section

```python
def _build_run_context(context: RunContext) -> str:
    config = context.config
    lines: list[str] = []

    lines.append("## This Run")
    lines.append(f"- Run ID: {context.run_id}")
    lines.append(f"- Triggered by: {context.trigger}")
    lines.append(f"- Current time: {_format_datetime(context.current_datetime)}")
    lines.append(f"- Timezone: {config.schedule_timezone}")

    # Scheduled outputs — must be produced this run
    scheduled = [o for o in config.outputs if o.trigger == OutputTrigger.SCHEDULED]
    optional = [o for o in config.outputs if o.trigger == OutputTrigger.AGENT_DECIDES]

    if scheduled:
        lines.append("\n## Outputs Due This Run")
        for output in scheduled:
            lines.append(f"\n### {output.name}")
            if output.description:
                lines.append(f"Description: {output.description}")
            if output.format:
                lines.append(f"Format instructions:\n{output.format}")

    if optional:
        lines.append("\n## Outputs You Can Trigger If Warranted")
        for output in optional:
            lines.append(f"\n### {output.name}")
            if output.description:
                lines.append(f"Description: {output.description}")
            if output.format:
                lines.append(f"Format instructions:\n{output.format}")

    # Resource awareness — let the agent plan around its limits
    r = config.resources
    lines.append("\n## Resource Limits This Run")
    lines.append(f"- Search calls: max {r.max_search_calls_per_run}")
    lines.append(f"- Fetch calls: max {r.max_fetch_calls_per_run}")
    lines.append(f"- Deep research calls: max {r.max_deep_research_calls_per_run}")
    lines.append(f"- SQL calls: max {r.max_sql_calls_per_run}")
    lines.append(f"- Run timeout: {r.run_timeout_seconds}s")

    return "\n".join(lines)
```

### Helper functions

```python
def _section(title: str, content: str) -> str:
    return f"## {title}\n\n{content}"


def _format_datetime(dt: datetime) -> str:
    return dt.strftime("%A, %B %d, %Y — %I:%M %p %Z")
```

### Key decisions

- **Output definitions are injected but NOT the destination or type.**
  The agent sees output names, descriptions, and format instructions.
  It does NOT see "telegram" or chat_ids — those are platform concerns.
  The agent just calls `deliver_output(output_name=..., content=...)`.
- **Resource limits shown to the agent** so it can plan (e.g., "I have
  20 search calls, I'll do 5 searches on each of my 4 topics").
  The platform still enforces limits via ResourceTracker regardless.
- **Tool instructions appended** from the tool registry's prompt_hints,
  filtered to only the tools in this agent's template.

### Tests

- Test with a full RunContext: all sections present in output
- Test with empty mission: mission section omitted
- Test output definitions rendered correctly (scheduled vs optional)
- Test resource limits section present
- Test tool instructions filtered to agent's tools

---

## Module: `agent_runner.py`

**Purpose:** The core execution loop. Think → act → store → schedule →
sleep. Takes a RunContext, LlmClient, and ToolExecutor, runs the agent
loop, enforces resource limits, and returns a completed AgentRun.

This module knows nothing about scheduling, delivery adapters, or the
daemon. Those are handled by the layers above.

**Source:** New (based on the sketch, incorporating patterns from
redclaw's `agent_turn_runner.py`).

### ResourceTracker

```python
class ResourceLimitError(RuntimeError):
    """Raised when a tool call would exceed resource limits."""
    pass


class ResourceTracker:
    """Tracks tool call counts against the resource envelope."""

    def __init__(self, envelope: ResourceEnvelope) -> None:
        self._envelope = envelope
        self._counts: dict[str, int] = defaultdict(int)

    def check_and_record(self, tool_name: str) -> None:
        """Record a tool call. Raises ResourceLimitError if over limit."""
        self._counts[tool_name] += 1
        self._enforce(tool_name)

    def _enforce(self, tool_name: str) -> None:
        e = self._envelope
        limits: dict[str, tuple[str, int]] = {
            "web_search": ("max_search_calls_per_run", e.max_search_calls_per_run),
            "web_fetch": ("max_fetch_calls_per_run", e.max_fetch_calls_per_run),
            "web_extract": ("max_fetch_calls_per_run", e.max_fetch_calls_per_run),
            "deep_research": ("max_deep_research_calls_per_run", e.max_deep_research_calls_per_run),
            "execute_sql": ("max_sql_calls_per_run", e.max_sql_calls_per_run),
        }
        if tool_name in limits:
            limit_name, limit_val = limits[tool_name]
            if self._counts[tool_name] > limit_val:
                raise ResourceLimitError(
                    f"Resource limit exceeded: {limit_name} "
                    f"({self._counts[tool_name]} > {limit_val})"
                )

    @property
    def counts(self) -> dict[str, int]:
        return dict(self._counts)
```

Note: `web_extract` counts against fetch limits. `deep_research` counts
against its own dedicated limit. Internal search/fetch calls within
deep_research do NOT count against the separate limits — deep_research
is its own budget.

### Utility

```python
from uuid import uuid4

def new_run_id() -> str:
    """Generate a unique run ID."""
    return f"run_{uuid4().hex[:16]}"
```

### Main entry point

```python
import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import structlog

from clarion.agent_state import record_run
from clarion.logging import bind_context, clear_context
from clarion.models import AgentRun, AgentTurn, ResourceEnvelope, RunContext, RunStatus
from clarion.prompt_assembly import build_system_prompt
from clarion.tool_registry import get_tool_schemas

log = structlog.get_logger()

MAX_TOOL_STEPS = 40

async def run_agent(
    context: RunContext,
    llm_client: LlmClient,
    tool_executor: ToolExecutor,
) -> AgentRun:
    """Execute a single agent run and return the completed AgentRun."""
    run_id = context.run_id
    started_at = datetime.now(UTC)
    tracker = ResourceTracker(context.config.resources)
    outputs_produced: list[str] = []

    # Bind logging context for this run
    bind_context(agent_id=context.agent_id, run_id=run_id)

    log.info("agent_run.start", trigger=context.trigger)

    try:
        await asyncio.wait_for(
            _run_loop(context, llm_client, tool_executor, tracker, outputs_produced),
            timeout=context.config.resources.run_timeout_seconds,
        )
        status = RunStatus.SUCCESS
        error = None

    except TimeoutError:
        status = RunStatus.TIMEOUT
        error = f"Run timed out after {context.config.resources.run_timeout_seconds}s"
        log.warning("agent_run.timeout")

    except ResourceLimitError as exc:
        status = RunStatus.FAILED
        error = str(exc)
        log.warning("agent_run.resource_limit", error=error)

    except Exception as exc:
        status = RunStatus.FAILED
        error = str(exc)
        log.error("agent_run.error", error=error)

    completed_at = datetime.now(UTC)

    run = AgentRun(
        run_id=run_id,
        agent_id=context.agent_id,
        started_at=started_at,
        completed_at=completed_at,
        status=status,
        trigger=context.trigger,
        error=error,
        outputs_produced=outputs_produced,
        tool_call_counts=tracker.counts,
    )

    # Record to run history
    record_run(run, Path(context.workspace_root))

    log.info(
        "agent_run.complete",
        status=status.value,
        duration_s=(completed_at - started_at).total_seconds(),
        tool_calls=tracker.counts,
        outputs_produced=outputs_produced,
    )

    clear_context()
    return run
```

### The inner loop

```python
async def _run_loop(
    context: RunContext,
    llm_client: LlmClient,
    tool_executor: ToolExecutor,
    tracker: ResourceTracker,
    outputs_produced: list[str],
) -> None:
    """The inner think → act loop."""
    system_prompt = build_system_prompt(context)
    tool_schemas = get_tool_schemas(context.config.tools)
    messages: list[dict] = []
    step = 0

    while step < MAX_TOOL_STEPS:
        step += 1

        # Ask the LLM
        turn: AgentTurn = await llm_client.respond(
            system_prompt=system_prompt,
            messages=messages,
            tools=tool_schemas,
            model=context.config.model,
            max_tokens=context.config.max_tokens,
        )

        if turn.parse_failure:
            log.warning("agent_run.parse_failure", step=step)
            break

        # Build assistant message for history
        assistant_msg: dict = {"role": "assistant"}
        if turn.text:
            assistant_msg["content"] = turn.text
        if turn.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in turn.tool_calls
            ]
        messages.append(assistant_msg)

        # If no tool calls, the agent is done
        if not turn.tool_calls:
            break

        # Execute tool calls
        tool_executor.start_turn()
        for tc in turn.tool_calls:
            try:
                tracker.check_and_record(tc.name)
                result = await tool_executor.execute(
                    name=tc.name,
                    arguments=tc.arguments,
                    correlation_id=context.run_id,
                )
            except ResourceLimitError:
                # Let it propagate — run_agent catches it
                tool_executor.discard_turn()
                raise
            except Exception as exc:
                # Tool error → tell the LLM, don't crash the run
                result = {"text": f"Tool error: {exc}"}

            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result.get("text", ""),
            })

        # Commit side effects
        side_effects = tool_executor.commit_turn()
        outputs_produced.extend(side_effects.outputs_delivered)

    else:
        log.warning("agent_run.tool_loop_exhausted", steps=step)
```

### Key design decisions

1. **ResourceLimitError is a hard stop.** When hit, the current turn's
   side effects are discarded and the run is marked FAILED. Revisit
   later if graceful wind-down is needed (give agent one more turn to
   summarize).

2. **Tool errors become messages to the LLM.** If a tool raises an
   exception (e.g., network error in fetch), the error message is passed
   back as a tool result. The LLM can decide to retry, skip, or handle
   gracefully. Only ResourceLimitError and TimeoutError crash the run.

3. **Turn staging per tool-call batch.** Each set of tool calls from one
   LLM turn is a staged "turn" in the executor. This means if the LLM
   requests 3 tool calls and the 2nd one hits a resource limit, the
   1st one's side effects are also discarded. This is the safe default.

4. **Messages accumulate.** The full history of the run (all LLM turns
   and tool results) is passed to the LLM each time. There is no
   compaction — runs are bounded tasks, not open-ended conversations.

5. **Record run to JSONL** after completion, regardless of status.

### Tests

- **Success path:** Mock LLM returns text → AgentRun.status == SUCCESS
- **Tool call path:** Mock LLM returns tool calls, then text → tools
  executed, outputs tracked
- **Resource limit:** Mock LLM calls tool N+1 times → ResourceLimitError,
  run status FAILED
- **Timeout:** Mock LLM hangs → TimeoutError, run status TIMEOUT
- **Tool error:** Mock tool raises → error message passed to LLM,
  run continues
- **Parse failure:** Mock LLM returns parse_failure → run exits cleanly
- **Max steps:** Mock LLM always returns tool calls → exits at
  MAX_TOOL_STEPS
- **Run recorded:** After any completion, agent_state.record_run called

---

## Build order

1. `prompt_assembly.py` first — it's simpler and agent_runner depends on it
2. `agent_runner.py` second

---

## Verification

```bash
# Integration test: mock LLM + mock tools → full run
uv run pytest tests/test_agent_runner.py -x -v

# Smoke test with real prompt assembly
uv run python -c "
from clarion.prompt_assembly import build_system_prompt
from clarion.models import RunContext, AgentConfig, ResourceEnvelope, OutputDefinition, OutputTrigger, OutputType
from datetime import datetime, UTC

config = AgentConfig(
    agent_id='test',
    name='Test Agent',
    description='test',
    owner='test',
    version=1,
    template='research',
    schedule_cron='0 6 * * 1',
    schedule_timezone='UTC',
    outputs=[
        OutputDefinition(
            name='weekly-briefing',
            trigger=OutputTrigger.SCHEDULED,
            type=OutputType.TELEGRAM,
            destination='123',
            format='Short summary.',
        ),
    ],
    database_enabled=True,
    resources=ResourceEnvelope(),
    tools=['web_search', 'execute_sql'],
    base_system_prompt='You are a research agent.',
)
ctx = RunContext(
    agent_id='test',
    run_id='run_test',
    config=config,
    mission_md='# Test Mission\nDo research.',
    workspace_root='/tmp/test',
    trigger='manual',
    current_datetime=datetime.now(UTC),
)
prompt = build_system_prompt(ctx)
print(prompt[:500])
print('...')
print(f'Total length: {len(prompt)} chars')
"
```
