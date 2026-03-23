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


def _section(title: str, content: str) -> str:
    return f"## {title}\n\n{content}"


def _format_datetime(dt: datetime) -> str:
    return dt.strftime("%A, %B %d, %Y — %I:%M %p %Z")
