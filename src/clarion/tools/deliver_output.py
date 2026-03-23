"""Output delivery tool for Clarion agents."""

from __future__ import annotations

from typing import Any

import structlog

from clarion.models import AgentConfig, DeliveryAdapter, OutputType

log = structlog.get_logger()


class DeliveryError(RuntimeError):
    """Raised when output delivery fails for any reason."""


async def execute_deliver_output(
    arguments: dict[str, object],
    agent_config: AgentConfig,
    delivery_adapters: dict[OutputType, DeliveryAdapter],
    correlation_id: str,
) -> str:
    """Deliver a named output to its configured channel."""
    output_name = str(arguments["output_name"])
    content = str(arguments["content"])

    output_def = next(
        (o for o in agent_config.outputs if o.name == output_name),
        None,
    )
    if output_def is None:
        available = [o.name for o in agent_config.outputs]
        raise DeliveryError(
            f"Unknown output: {output_name!r}. Available: {available}"
        )

    adapter = delivery_adapters.get(output_def.type)
    if adapter is None:
        raise DeliveryError(
            f"No delivery adapter configured for output type: {output_def.type.value}"
        )

    try:
        result = await adapter.deliver(
            destination=output_def.destination,
            content=content,
            output_name=output_name,
        )
    except DeliveryError:
        raise
    except Exception as exc:
        raise DeliveryError(f"Delivery failed: {exc}") from exc

    log.info(
        "deliver_output.success",
        output_name=output_name,
        output_type=output_def.type.value,
        correlation_id=correlation_id,
    )
    return result


# ---------------------------------------------------------------------------
# ToolHandler
# ---------------------------------------------------------------------------

from clarion.boundary_validation import MAX_FETCH_CONTENT_LEN, BoundaryValidationError
from clarion.tools.base import ToolContext, ToolHandler, ToolResult


class DeliverOutputHandler(ToolHandler):
    async def validate(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> dict[str, Any]:
        output_name = arguments.get("output_name")
        if not isinstance(output_name, str):
            raise BoundaryValidationError("output_name must be a string")
        content = arguments.get("content", "")
        if len(content) > MAX_FETCH_CONTENT_LEN:
            raise BoundaryValidationError(
                f"deliver_output content exceeds maximum length of "
                f"{MAX_FETCH_CONTENT_LEN} characters"
            )
        return arguments

    async def execute(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        text = await execute_deliver_output(
            arguments,
            ctx.agent_config,
            ctx.delivery_adapters,
            ctx.correlation_id,
        )
        output_name = str(arguments.get("output_name", ""))
        outputs_delivered = [output_name] if output_name else []
        return ToolResult(text=text, outputs_delivered=outputs_delivered)
