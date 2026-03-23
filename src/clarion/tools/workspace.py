"""Workspace file operations for Clarion agents."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from clarion.boundary_validation import validate_agent_path


def execute_write_file(
    arguments: dict[str, object],
    workspace_root: Path,
    agent_id: str,
) -> str:
    """Write content to a file in the agent's workspace.

    Path validation is handled by WriteFileHandler.validate().
    """
    path_str = str(arguments["path"])
    content = str(arguments["content"])

    resolved = (workspace_root / path_str).resolve()
    resolved.parent.mkdir(parents=True, exist_ok=True)
    resolved.write_text(content)

    return f"Written {len(content)} bytes to {path_str}"


# ---------------------------------------------------------------------------
# ToolHandler
# ---------------------------------------------------------------------------

from clarion.tools.base import ToolContext, ToolHandler, ToolResult


class WriteFileHandler(ToolHandler):
    async def validate(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> dict[str, Any]:
        validate_agent_path(ctx.agent_id, str(arguments.get("path", "")), ctx.workspace_root)
        return arguments

    async def execute(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        return ToolResult(text=execute_write_file(arguments, ctx.workspace_root, ctx.agent_id))
