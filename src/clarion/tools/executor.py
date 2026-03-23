"""Tool executor — dispatches tool calls via handler registry, stages side effects."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import structlog

from clarion.boundary_validation import (
    MAX_FETCH_CONTENT_LEN,
    BoundaryValidationError,
    validate_tool_result,
)
from clarion.cron_state import CronJob
from clarion.models import AgentConfig, DeliveryAdapter, OutputType
from clarion.tool_registry import get_execution_policy
from clarion.tools import build_handler_registry
from clarion.tools.base import ToolContext
from clarion.tools.fetch import wrap_untrusted_web_content
from clarion.tools.fetch_cache import FetchCache

log = structlog.get_logger()


@dataclass
class TurnSideEffects:
    cron_registrations: list[CronJob] = field(default_factory=list)
    cron_unregistrations: list[str] = field(default_factory=list)
    outputs_delivered: list[str] = field(default_factory=list)



class ToolExecutor:
    """Runs tool calls with boundary validation, memoization, and turn staging."""

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
        self._fetch_cache: FetchCache | None = None
        try:
            self._fetch_cache = FetchCache(workspace_root, agent_id)
        except Exception:
            log.warning("fetch_cache_init_failed")
        self._handlers = build_handler_registry()
        self._staged: TurnSideEffects | None = None
        self._memo: dict[str, dict[str, str]] = {}

    def _target(self) -> TurnSideEffects:
        if self._staged is None:
            self._staged = TurnSideEffects()
        return self._staged

    # -- turn staging ---------------------------------------------------------

    def start_turn(self) -> None:
        if self._staged is not None:
            raise RuntimeError("tool turn already in progress")
        self._staged = TurnSideEffects()
        self._memo.clear()

    def commit_turn(self) -> TurnSideEffects:
        if self._staged is None:
            return TurnSideEffects()
        staged = self._staged
        self._staged = None
        self._memo.clear()
        return staged

    def discard_turn(self) -> None:
        self._staged = None
        self._memo.clear()

    # -- execute --------------------------------------------------------------

    async def execute(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        correlation_id: str,
    ) -> dict[str, str]:
        if not correlation_id:
            raise BoundaryValidationError("correlation_id must be a non-empty string")

        handler = self._handlers[name]

        policy = get_execution_policy(name)
        if policy.memoize_duplicate_calls_within_turn:
            memo_key = f"{name}:{json.dumps(arguments, sort_keys=True, default=str)}"
            if memo_key in self._memo:
                return self._memo[memo_key]

        ctx = ToolContext(
            workspace_root=self._workspace_root,
            agent_id=self._agent_id,
            agent_config=self._agent_config,
            delivery_adapters=self._delivery_adapters,
            fetch_cache=self._fetch_cache,
            schedule_timezone=self._schedule_timezone,
            correlation_id=correlation_id,
        )

        await handler.validate(arguments, ctx)

        log.info("tool.execute.start", correlation_id=correlation_id, tool_name=name)

        try:
            result = await handler.execute(arguments, ctx)
        except Exception as exc:
            log.error(
                "tool.execute.error",
                correlation_id=correlation_id,
                tool_name=name,
                error=str(exc),
            )
            raise

        text = result.text
        if result.wraps_untrusted_content:
            text = wrap_untrusted_web_content(text, max_len=MAX_FETCH_CONTENT_LEN)

        validated_text = validate_tool_result(text)
        validated_result = {"text": validated_text}

        target = self._target()
        target.cron_registrations.extend(result.cron_registrations)
        target.cron_unregistrations.extend(result.cron_unregistrations)
        target.outputs_delivered.extend(result.outputs_delivered)

        if policy.memoize_duplicate_calls_within_turn:
            self._memo[memo_key] = validated_result

        log.info(
            "tool.execute.complete",
            correlation_id=correlation_id,
            tool_name=name,
            result_text_len=len(validated_text),
        )
        return validated_result
