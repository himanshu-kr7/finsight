"""Structured logging configuration for finsight.

Built on `structlog` with two output modes:
  - `console`: human-readable colored output for local development
  - `json`: machine-parseable JSON for production log aggregators

Usage:
    from finsight.logging import configure_logging, get_logger

    configure_logging()                    # call once at app startup
    log = get_logger(__name__)             # in any module
    log.info("user_query_received", user_id=42, query="hello")

Structured logging best practice: log events as snake_case verbs/nouns and
pass context as keyword arguments rather than f-strings. This makes logs
filterable and queryable.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.types import Processor

from finsight.config import LogFormat, LogLevel, get_settings


def configure_logging() -> None:
    """Configure structlog and the stdlib logging module.

    Should be called exactly once at application startup (e.g., in the
    FastAPI lifespan handler). Safe to call multiple times; subsequent
    calls are idempotent.
    """
    settings = get_settings()
    log_level = _resolve_log_level(settings.app.log_level)

    # Shared processors run on every log event regardless of output format.
    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,  # request-scoped context
        structlog.stdlib.add_log_level,  # adds level to event dict
        structlog.stdlib.add_logger_name,  # adds logger name
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Format-specific renderer at the end of the pipeline.
    renderer: Processor
    if settings.app.log_format == LogFormat.JSON:
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=[*shared_processors, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Route stdlib logging (used by third-party libs like uvicorn, httpx)
    # through the same structlog pipeline so all logs share one format.
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=log_level,
    )

    # Silence noisy libraries
    for noisy in ("httpx", "httpcore", "urllib3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str | None = None, **initial_values: Any) -> structlog.stdlib.BoundLogger:
    """Return a structlog logger bound with optional initial context.

    Args:
        name: Usually `__name__` from the calling module.
        **initial_values: Key-value pairs added to every event from this logger.

    Example:
        log = get_logger(__name__, service="retrieval")
        log.info("query_executed", duration_ms=42)
    """
    logger: structlog.stdlib.BoundLogger = structlog.get_logger(name, **initial_values)
    return logger


def _resolve_log_level(level: LogLevel) -> int:
    """Convert our LogLevel enum to the stdlib logging integer constant."""
    value: int = getattr(logging, level.value)
    return value
