"""Agent execution loop — layer 2.

The core think → act → store → schedule → sleep loop.
Takes a RunContext, LlmClient, and ToolExecutor, runs the agent loop,
enforces resource limits, and returns a completed AgentRun.
"""

from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import structlog

from clarion.agent_state import record_run, record_turn
from clarion.logging import bind_context, clear_context
from clarion.models import (
    AgentRun,
    AgentTurn,
    ConversationTurn,
    ResourceEnvelope,
    RunContext,
    RunStatus,
)
from clarion.prompt_assembly import build_system_prompt
from clarion.tool_registry import get_tool_schemas
from clarion.tools.executor import ToolExecutor

log = structlog.get_logger()

MAX_TOOL_STEPS = 40


class ResourceLimitError(RuntimeError):
    """Raised when a tool call would exceed resource limits."""


class ParseFailureError(RuntimeError):
    """Raised when the LLM returns an unparseable response."""


class ToolLoopExhaustedError(RuntimeError):
    """Raised when the agent exceeds MAX_TOOL_STEPS."""


class ResourceTracker:
    """Tracks tool call counts against the resource envelope."""

    def __init__(self, envelope: ResourceEnvelope) -> None:
        self._envelope = envelope
        self._counts: dict[str, int] = defaultdict(int)

    def check_and_record(self, tool_name: str) -> None:
        """Record a tool call. Raises ResourceLimitError if at limit."""
        self._enforce(tool_name)
        self._counts[tool_name] += 1

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
            if self._counts[tool_name] >= limit_val:
                raise ResourceLimitError(
                    f"Resource limit exceeded: {limit_name} "
                    f"(used {self._counts[tool_name]}/{limit_val})"
                )

    @property
    def counts(self) -> dict[str, int]:
        return dict(self._counts)


def new_run_id() -> str:
    """Generate a unique run ID."""
    return f"run_{uuid4().hex[:16]}"


# Protocol-compatible type hint for the LLM client
class LlmClient:
    """Type stub — the real implementation is OpenAIStreamingClient."""

    async def respond(
        self,
        *,
        system_prompt: str,
        messages: list[dict],
        tools: list[dict],
        model: str,
        max_tokens: int,
    ) -> AgentTurn: ...


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

    except ParseFailureError as exc:
        status = RunStatus.FAILED
        error = str(exc)
        log.warning("agent_run.parse_failure")

    except ToolLoopExhaustedError as exc:
        status = RunStatus.FAILED
        error = str(exc)
        log.warning("agent_run.tool_loop_exhausted")

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
    workspace = Path(context.workspace_root)
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
            raise ParseFailureError("LLM returned an unparseable response")

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

        # Persist the assistant turn
        record_turn(
            ConversationTurn(
                step=step,
                timestamp=datetime.now(UTC),
                role="assistant",
                text=turn.text,
                tool_calls=turn.tool_calls,
            ),
            workspace,
            context.run_id,
        )

        # If no tool calls, the agent is done
        if not turn.tool_calls:
            break

        # Execute tool calls
        tool_executor.start_turn()
        for tc in turn.tool_calls:
            tool_error = False
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
                tool_error = True

            result_text = result.get("text", "")
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": result_text,
            })

            # Persist the tool result turn
            record_turn(
                ConversationTurn(
                    step=step,
                    timestamp=datetime.now(UTC),
                    role="tool",
                    text=result_text,
                    tool_call_id=tc.id,
                    tool_name=tc.name,
                    tool_error=tool_error,
                ),
                workspace,
                context.run_id,
            )

        # Commit side effects
        side_effects = tool_executor.commit_turn()
        outputs_produced.extend(side_effects.outputs_delivered)

    else:
        log.warning("agent_run.tool_loop_exhausted", steps=step)
        raise ToolLoopExhaustedError(f"Agent exceeded {MAX_TOOL_STEPS} tool steps")
