"""Current datetime tool."""

from __future__ import annotations

import zoneinfo
from datetime import UTC, datetime
from typing import Any

from clarion.tools.base import ToolContext, ToolHandler, ToolResult


class CurrentDatetimeHandler(ToolHandler):
    async def execute(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        tz_name = ctx.schedule_timezone
        try:
            tz = zoneinfo.ZoneInfo(tz_name)
        except Exception:
            tz = UTC
            tz_name = "UTC"
        now = datetime.now(tz)
        return ToolResult(
            text=now.strftime(f"%A, %B %d, %Y — %I:%M %p ({tz_name})"),
        )
