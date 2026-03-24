"""Tool handler base types — the behavioral counterpart to ToolSpec.

ToolSpec (in tool_registry.py) is pure data: schema, policy, prompt_hint.
ToolHandler (here) is behavior: validate and execute.

Each tool module defines a ToolHandler subclass. The executor looks up
the handler by name and calls validate() then execute().
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from clarion.cron_state import CronJob
    from clarion.models import AgentConfig, DeliveryAdapter, OutputType
    from clarion.tools.fetch_cache import FetchCache


@dataclass(frozen=True)
class ToolContext:
    """Everything a tool might need from the executor."""

    workspace_root: Path
    agent_id: str
    agent_config: "AgentConfig"
    delivery_adapters: "dict[OutputType, DeliveryAdapter]"
    fetch_cache: "FetchCache | None"
    timezone: str
    correlation_id: str


@dataclass
class ToolResult:
    """What a tool returns to the executor."""

    text: str
    wraps_untrusted_content: bool = False
    cron_registrations: list[CronJob] = field(default_factory=list)
    cron_unregistrations: list[str] = field(default_factory=list)
    outputs_delivered: list[str] = field(default_factory=list)


class ToolHandler(ABC):
    """Base class for all tool handlers.

    Subclass this, implement execute(), and optionally override validate().
    """

    async def validate(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> dict[str, Any]:
        """Validate arguments before execution.

        Default: pass through unchanged. Override to add boundary checks.
        Raise BoundaryValidationError on failure.
        """
        return arguments

    @abstractmethod
    async def execute(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        """Execute the tool and return a result."""
        ...
