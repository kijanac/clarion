"""Boundary validation utilities — layer 0.

Primitive validators for paths, URLs, SQL, and env vars.
Per-tool validation lives in each tool's ToolHandler.validate().
"""

from __future__ import annotations

import asyncio
import ipaddress
import os
import re
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


# ── Exception ───────────────────────────────────────────────────────────────


class BoundaryValidationError(ValueError):
    """Raised when a boundary check fails."""


# ── Constants ───────────────────────────────────────────────────────────────

MAX_QUERY_LEN = 2000
MAX_URL_LEN = 2048
MAX_SQL_LEN = 5000
MAX_FETCH_CONTENT_LEN = 500_000
MAX_SEARCH_RESULT_LEN = 30_000
MAX_RESEARCH_SOURCES = 10
FETCH_MODES = {"fast", "stealth", "browser"}
EXTRACT_SELECTOR_TYPES = {"css", "xpath"}
BLOCKED_SQL_PATTERNS = [
    r"\bATTACH\b",
    r"\bLOAD_EXTENSION\b",
    r"\bPRAGMA\s+(?!table_info|table_list)",
]

_ENV_VAR_PATTERN = re.compile(r"\$\{([A-Z_][A-Z0-9_]*)\}")


# ── Path validation ────────────────────────────────────────────────────────


def validate_agent_path(agent_id: str, path: str, workspace_root: Path) -> Path:
    """Resolve and validate that a path is within the agent's workspace.

    Raises BoundaryValidationError if the path escapes the workspace.
    """
    resolved = (workspace_root / path).resolve()
    workspace_resolved = workspace_root.resolve()
    if not resolved.is_relative_to(workspace_resolved):
        raise BoundaryValidationError(f"Path {path!r} escapes agent workspace")
    return resolved


# ── URL validation ──────────────────────────────────────────────────────────


async def validate_url(url: str) -> str:
    """Validate a URL for format, length, and SSRF safety.

    Returns the URL unchanged if valid.
    Raises BoundaryValidationError on any failure.
    """
    if not url:
        raise BoundaryValidationError("URL must not be empty")
    if len(url) > MAX_URL_LEN:
        raise BoundaryValidationError(
            f"URL exceeds maximum length of {MAX_URL_LEN} characters"
        )
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise BoundaryValidationError(
            f"URL must use http or https scheme, got {parsed.scheme!r}"
        )
    hostname = parsed.hostname
    if not hostname:
        raise BoundaryValidationError("URL has no hostname")
    try:
        addr_info = await asyncio.to_thread(socket.getaddrinfo, hostname, None)
    except OSError:
        raise BoundaryValidationError(f"Cannot resolve hostname {hostname!r}")
    for family, _type, _proto, _canonname, sockaddr in addr_info:
        ip = ipaddress.ip_address(sockaddr[0])
        if not ip.is_global:
            raise BoundaryValidationError(
                f"URL resolves to non-global IP {ip} (SSRF protection)"
            )
    return url


# ── SQL validation ──────────────────────────────────────────────────────────


def validate_sql(sql: str) -> str:
    """Validate a SQL statement against length and blocked patterns.

    Returns the SQL unchanged if valid.
    Raises BoundaryValidationError on any failure.
    """
    if len(sql) > MAX_SQL_LEN:
        raise BoundaryValidationError(
            f"SQL exceeds maximum length of {MAX_SQL_LEN} characters"
        )
    for pattern in BLOCKED_SQL_PATTERNS:
        if re.search(pattern, sql, re.IGNORECASE):
            raise BoundaryValidationError(
                f"SQL contains blocked pattern: {pattern}"
            )
    return sql


# ── Environment variable expansion ──────────────────────────────────────────


def expand_env_vars(value: str) -> str:
    """Expand ${VAR} references in a string using os.environ.

    Raises BoundaryValidationError if a referenced variable is not set.
    """
    def _replace(match: re.Match) -> str:
        var_name = match.group(1)
        val = os.environ.get(var_name)
        if val is None:
            raise BoundaryValidationError(
                f"Environment variable {var_name!r} is not set"
            )
        return val

    return _ENV_VAR_PATTERN.sub(_replace, value)


# ── Tool result validation ──────────────────────────────────────────────────


def validate_tool_result(result: str) -> str:
    """Size-limit tool output to MAX_FETCH_CONTENT_LEN.

    Truncates the result if it exceeds the limit.
    """
    if len(result) > MAX_FETCH_CONTENT_LEN:
        return result[:MAX_FETCH_CONTENT_LEN]
    return result
