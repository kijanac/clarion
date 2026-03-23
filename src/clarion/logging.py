"""Structured logging configuration for Clarion.

Call configure_logging() once at startup. Then use
structlog.get_logger() throughout the codebase.
"""

from __future__ import annotations

import logging

import structlog


def configure_logging(*, json: bool = True, level: str = "INFO") -> None:
    """Configure structlog processors and output format.

    Args:
        json: If True, output JSON lines (production). If False, output
              human-readable colored output (development).
        level: Minimum log level.
    """
    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if json:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.UnicodeDecoder(),
            renderer,
        ],
        logger_factory=structlog.PrintLoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(level.upper()),
        ),
        cache_logger_on_first_use=True,
    )


def bind_context(**kwargs: object) -> None:
    """Bind key-value pairs to the current context (asyncio-safe).

    Use this to set correlation IDs, agent_id, run_id, etc. at the
    start of a run. All subsequent log calls in that async context
    will include these fields.
    """
    structlog.contextvars.bind_contextvars(**kwargs)


def clear_context() -> None:
    """Clear all context bindings."""
    structlog.contextvars.clear_contextvars()
