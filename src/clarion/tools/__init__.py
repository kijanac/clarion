"""Tool implementations for Clarion agents."""

from __future__ import annotations

from clarion.tools.base import ToolHandler
from clarion.tools.cron import CronHandler
from clarion.tools.datetime_tool import CurrentDatetimeHandler
from clarion.tools.deliver_output import DeliverOutputHandler
from clarion.tools.fetch import WebExtractHandler, WebFetchHandler
from clarion.tools.research import DeepResearchHandler
from clarion.tools.search import DdgRateLimiter, WebSearchHandler
from clarion.tools.sql import ExecuteSqlHandler, ListDatabasesHandler
from clarion.tools.workspace import WriteFileHandler


def build_handler_registry() -> dict[str, ToolHandler]:
    """Create handler instances with shared dependencies."""
    ddg_rate_limiter = DdgRateLimiter()
    return {
        "current_datetime": CurrentDatetimeHandler(),
        "web_search": WebSearchHandler(ddg_rate_limiter),
        "web_fetch": WebFetchHandler(),
        "web_extract": WebExtractHandler(),
        "deep_research": DeepResearchHandler(ddg_rate_limiter),
        "execute_sql": ExecuteSqlHandler(),
        "list_databases": ListDatabasesHandler(),
        "cron": CronHandler(),
        "write_file": WriteFileHandler(),
        "deliver_output": DeliverOutputHandler(),
    }
