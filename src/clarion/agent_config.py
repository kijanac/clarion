"""Agent config loader and validator — layer 0.

Parses agent.yaml + resolves the referenced template into a fully
populated AgentConfig.
"""

from __future__ import annotations

import zoneinfo
from pathlib import Path
from typing import Any

import yaml
from croniter import croniter

from clarion.boundary_validation import expand_env_vars
from clarion.models import (
    AgentConfig,
    OutputDefinition,
    OutputTrigger,
    OutputType,
    ResourceEnvelope,
    TriggerDefinition,
    TriggerType,
)


class ConfigValidationError(ValueError):
    """Raised when agent.yaml or template is invalid."""


def load_agent_config(
    agent_dir: Path,
    agent_id: str,
    templates_dir: Path | None = None,
) -> AgentConfig:
    """Load, validate, and return a fully resolved AgentConfig."""
    # 1. Read agent.yaml
    agent_yaml = agent_dir / "agent.yaml"
    if not agent_yaml.exists():
        raise ConfigValidationError(f"No agent.yaml found in {agent_dir}")
    raw = yaml.safe_load(agent_yaml.read_text())
    if not isinstance(raw, dict):
        raise ConfigValidationError("agent.yaml must be a YAML mapping")

    # 2. Resolve templates_dir
    if templates_dir is None:
        templates_dir = _find_templates_dir(agent_dir)

    # 3. Load template
    template_name = raw.get("template")
    if not template_name:
        raise ConfigValidationError("agent.yaml must specify a 'template'")
    template = load_template(template_name, templates_dir)

    # 4. Extract meta
    meta = raw.get("meta", {})
    if not isinstance(meta, dict):
        raise ConfigValidationError("'meta' must be a mapping")
    name = meta.get("name", agent_id)
    description = meta.get("description", "")
    owner = meta.get("owner", "")
    version = meta.get("version", 1)

    # 5. Triggers
    raw_triggers = raw.get("triggers", [])
    if not isinstance(raw_triggers, list):
        raise ConfigValidationError("'triggers' must be a list")
    triggers = parse_triggers(raw_triggers)

    # 6. Outputs
    raw_outputs = raw.get("outputs", [])
    if not isinstance(raw_outputs, list):
        raise ConfigValidationError("'outputs' must be a list")
    outputs = _parse_outputs(raw_outputs)

    # 7. Resources — merge template defaults with agent overrides
    resources = _resolve_resources(
        template.get("resources", {}),
        raw.get("resources", {}),
    )

    # 8. Database
    database_section = raw.get("database", {})
    if not isinstance(database_section, dict):
        raise ConfigValidationError("'database' must be a mapping")
    database_enabled = database_section.get("enabled", True)

    # 9. Tools from template
    tools = template.get("tools", [])
    if not isinstance(tools, list):
        raise ConfigValidationError("Template 'tools' must be a list")
    from clarion.tool_registry import get_spec

    unknown_tools = [t for t in tools if not isinstance(t, str) or get_spec(t) is None]
    if unknown_tools:
        raise ConfigValidationError(f"Unknown tools in template: {unknown_tools}")

    # 10. Model and max_tokens (template defaults, agent can override)
    model = raw.get("model", template.get("model", "claude-sonnet-4-6"))
    max_tokens = raw.get("max_tokens", template.get("max_tokens", 8192))

    # 11. Base system prompt from template
    base_system_prompt = template.get("system_prompt", "")

    return AgentConfig(
        agent_id=agent_id,
        name=name,
        description=description,
        owner=owner,
        version=version,
        template=template_name,
        triggers=triggers,
        outputs=outputs,
        database_enabled=database_enabled,
        resources=resources,
        tools=tools,
        model=model,
        max_tokens=max_tokens,
        base_system_prompt=base_system_prompt,
    )


def load_template(template_name: str, templates_dir: Path) -> dict[str, Any]:
    """Load and parse a template YAML file."""
    template_file = templates_dir / f"{template_name}.yaml"
    if not template_file.exists():
        raise ConfigValidationError(
            f"Template {template_name!r} not found at {template_file}"
        )
    data = yaml.safe_load(template_file.read_text())
    if not isinstance(data, dict):
        raise ConfigValidationError(f"Template {template_name!r} must be a YAML mapping")
    return data


def _find_templates_dir(agent_dir: Path) -> Path:
    """Find the templates/ directory by walking up from agent_dir."""
    current = agent_dir.resolve()
    for _ in range(10):  # safety limit
        for marker in ("architecture.toml", "pyproject.toml"):
            if (current / marker).exists():
                tpl_dir = current / "templates"
                if tpl_dir.is_dir():
                    return tpl_dir
        parent = current.parent
        if parent == current:
            break
        current = parent
    raise ConfigValidationError(
        "Could not find templates/ directory (looked for architecture.toml or pyproject.toml)"
    )


def validate_cron(expr: str) -> None:
    """Validate a cron expression. Raises ConfigValidationError."""
    if not croniter.is_valid(expr):
        raise ConfigValidationError(f"Invalid cron expression: {expr!r}")


def validate_timezone(tz: str) -> None:
    """Validate a timezone string. Raises ConfigValidationError."""
    try:
        zoneinfo.ZoneInfo(tz)
    except (KeyError, zoneinfo.ZoneInfoNotFoundError):
        raise ConfigValidationError(f"Invalid timezone: {tz!r}")


def _parse_outputs(raw_outputs: list[dict[str, Any]]) -> list[OutputDefinition]:
    """Parse and validate output definitions."""
    outputs = []
    seen_names: set[str] = set()
    for out in raw_outputs:
        if not isinstance(out, dict):
            raise ConfigValidationError("Each output must be a mapping")
        name = out.get("name")
        if not name:
            raise ConfigValidationError("Each output must have a 'name'")
        if name in seen_names:
            raise ConfigValidationError(f"Duplicate output name: {name!r}")
        seen_names.add(name)
        try:
            trigger = OutputTrigger(out.get("trigger", ""))
        except ValueError:
            raise ConfigValidationError(
                f"Output {name!r}: invalid trigger {out.get('trigger')!r}"
            )
        try:
            output_type = OutputType(out.get("type", ""))
        except ValueError:
            raise ConfigValidationError(
                f"Output {name!r}: invalid type {out.get('type')!r}"
            )
        # Expand env vars only in destination
        destination = out.get("destination", "")
        destination = expand_env_vars(destination)

        outputs.append(
            OutputDefinition(
                name=name,
                description=out.get("description", ""),
                trigger=trigger,
                type=output_type,
                destination=destination,
                format=out.get("format", ""),
            )
        )
    return outputs


def parse_triggers(raw_triggers: list[Any]) -> list[TriggerDefinition]:
    """Parse and validate trigger definitions."""
    triggers = []
    for raw in raw_triggers:
        if not isinstance(raw, dict):
            raise ConfigValidationError("Each trigger must be a mapping")
        try:
            trigger_type = TriggerType(raw.get("type", ""))
        except ValueError:
            raise ConfigValidationError(
                f"Invalid trigger type: {raw.get('type')!r}. Must be one of: {[t.value for t in TriggerType]}"
            )

        if trigger_type == TriggerType.CRON:
            expression = raw.get("expression", "")
            if not expression:
                raise ConfigValidationError("Cron trigger must have an 'expression'")
            validate_cron(expression)
            tz = raw.get("timezone", "UTC")
            validate_timezone(tz)
            triggers.append(TriggerDefinition(type=trigger_type, expression=expression, timezone=tz))

        elif trigger_type == TriggerType.AGENT_OUTPUT:
            source_agent = raw.get("source_agent", "")
            output_name = raw.get("output_name", "")
            if not source_agent or not output_name:
                raise ConfigValidationError(
                    "agent_output trigger must have 'source_agent' and 'output_name'"
                )
            triggers.append(TriggerDefinition(
                type=trigger_type,
                source_agent=source_agent,
                output_name=output_name,
            ))

    return triggers


def _resolve_resources(
    template: dict[str, Any],
    agent_overrides: dict[str, Any],
) -> ResourceEnvelope:
    """Merge template defaults with agent overrides.

    Agent values cannot exceed template maximums.
    """
    merged = dict(template)
    for key, value in agent_overrides.items():
        template_max = template.get(key)
        if template_max is not None and isinstance(value, int) and value > template_max:
            raise ConfigValidationError(
                f"Resource override {key}={value} exceeds template maximum {template_max}"
            )
        merged[key] = value
    return ResourceEnvelope(**merged)
