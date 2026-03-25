"""Current datetime tool."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from clarion.tools.base import ToolContext, ToolHandler, ToolResult


class CurrentDatetimeHandler(ToolHandler):
    async def execute(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        now = datetime.now(UTC)
        return ToolResult(
            text=now.strftime("%A, %B %d, %Y — %H:%M UTC"),
        )
