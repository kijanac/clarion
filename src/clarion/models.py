"""Core Pydantic models — layer 0.

All system types flow from here. No business logic — just data shapes.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


class OutputTrigger(str, Enum):
    SCHEDULED = "scheduled"
    AGENT_DECIDES = "agent_decides"


class OutputType(str, Enum):
    TELEGRAM = "telegram"
    EMAIL = "email"
    WEBHOOK = "webhook"


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

    max_runs_per_day: int = Field(ge=0, default=12)
    max_search_calls_per_run: int = Field(ge=0, default=30)
    max_fetch_calls_per_run: int = Field(ge=0, default=15)
    max_deep_research_calls_per_run: int = Field(ge=0, default=3)
    max_sql_calls_per_run: int = Field(ge=0, default=50)
    run_timeout_seconds: int = Field(gt=0, default=600)
    max_database_mb: int = Field(gt=0, default=1000)
    max_self_scheduled_runs_per_day: int = Field(ge=0, default=6)


class AgentConfig(BaseModel):
    """Parsed and validated agent config. What the platform works with
    at runtime. The agent (LLM) never sees this directly."""

    model_config = ConfigDict(frozen=True)

    agent_id: str
    name: str
    description: str
    owner: str
    version: int = Field(ge=1)
    template: str
    schedule_cron: str
    schedule_timezone: str
    outputs: list[OutputDefinition]
    database_enabled: bool
    resources: ResourceEnvelope
    tools: list[str]
    model: str = "claude-sonnet-4-6"
    max_tokens: int = Field(gt=0, default=8192)
    base_system_prompt: str = ""


class AgentRun(BaseModel):
    """A single execution of an agent."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    agent_id: str
    started_at: datetime
    status: RunStatus
    trigger: str
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
    mission_md: str
    workspace_root: str
    trigger: str
    current_datetime: datetime


class ConversationTurn(BaseModel):
    """A single turn in an agent run's conversation history."""

    model_config = ConfigDict(frozen=True)

    step: int
    timestamp: datetime
    role: str  # "assistant" | "tool"
    text: str | None = None
    tool_calls: list[ToolCallRequest] = Field(default_factory=list)
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_error: bool = False


class DeliveryAdapter(Protocol):
    """Protocol for output delivery adapters."""

    async def deliver(
        self,
        destination: str,
        content: str,
        output_name: str,
    ) -> str:
        """Deliver content to destination. Returns confirmation message."""
        ...
