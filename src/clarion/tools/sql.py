"""SQLite database tools."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger()

_MAX_SQL_ROWS = 500
_SQL_TIMEOUT_S = 30


def _databases_dir(workspace_root: Path, agent_id: str) -> Path:
    d = workspace_root / "databases"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _open_db(workspace_root: Path, agent_id: str, name: str) -> sqlite3.Connection:
    db_path = _databases_dir(workspace_root, agent_id) / f"{name}.db"
    conn = sqlite3.connect(str(db_path), timeout=_SQL_TIMEOUT_S)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def execute_sql(
    arguments: dict[str, object],
    correlation_id: str,
    workspace_root: Path,
    agent_id: str,
) -> str:
    name = str(arguments["name"])
    sql = str(arguments["sql"])
    params = arguments.get("params", [])
    if not isinstance(params, list):
        params = []

    try:
        conn = _open_db(workspace_root, agent_id, name)
    except Exception as exc:
        log.error(
            "tool.execute.error",
            correlation_id=correlation_id,
            tool_name="execute_sql",
            error=str(exc),
        )
        return f"Database error: {exc}"

    try:
        cursor = conn.execute(sql, params)
        if cursor.description is not None:
            columns = [d[0] for d in cursor.description]
            rows = cursor.fetchmany(_MAX_SQL_ROWS)
            result_data = [dict(zip(columns, row, strict=False)) for row in rows]
            return json.dumps(
                {
                    "columns": columns,
                    "rows": result_data,
                    "count": len(result_data),
                    "truncated": len(rows) >= _MAX_SQL_ROWS,
                },
                default=str,
            )
        else:
            conn.commit()
            return json.dumps({"rows_affected": cursor.rowcount})
    except sqlite3.Error as exc:
        return f"SQL error: {exc}"
    finally:
        conn.close()


def execute_list_databases(workspace_root: Path, agent_id: str) -> str:
    db_dir = _databases_dir(workspace_root, agent_id)
    names = sorted(p.stem for p in db_dir.glob("*.db"))
    return json.dumps({"databases": names})


# ---------------------------------------------------------------------------
# ToolHandlers
# ---------------------------------------------------------------------------

from clarion.boundary_validation import validate_sql
from clarion.tools.base import ToolContext, ToolHandler, ToolResult


class ExecuteSqlHandler(ToolHandler):
    async def validate(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> dict[str, Any]:
        validate_sql(str(arguments.get("sql", "")))
        return arguments

    async def execute(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        return ToolResult(text=execute_sql(
            arguments, ctx.correlation_id, ctx.workspace_root, ctx.agent_id
        ))


class ListDatabasesHandler(ToolHandler):
    async def execute(
        self, arguments: dict[str, Any], ctx: ToolContext
    ) -> ToolResult:
        return ToolResult(text=execute_list_databases(ctx.workspace_root, ctx.agent_id))
