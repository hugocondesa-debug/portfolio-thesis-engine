"""Structured logging via structlog, driven by :mod:`shared.config`."""

import logging
import sys
from typing import Any

import structlog

from portfolio_thesis_engine.shared.config import settings


def setup_logging() -> None:
    """Configure structlog + stdlib logging using current settings.

    Safe to call multiple times; structlog's ``cache_logger_on_first_use``
    means loggers obtained after reconfiguration pick up the new processors.
    """
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=settings.log_level,
        force=True,
    )

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    if settings.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=True))

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, settings.log_level)),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> Any:
    """Return a structlog logger bound to ``name``.

    Typed as ``Any`` because structlog's lazy proxy is dynamic and does not
    match :class:`structlog.stdlib.BoundLogger` until the first bind call.
    """
    return structlog.get_logger(name)
