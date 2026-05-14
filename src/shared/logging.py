"""Structured logging via structlog.

JSON output in prod, pretty in dev. Correlation IDs flow via contextvars.
"""
from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import cast

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from shared.config import get_settings

# correlation id flows through requests and jobs
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)


def _inject_context(_: WrappedLogger, __: str, event_dict: EventDict) -> EventDict:
    rid = request_id_var.get()
    jid = job_id_var.get()
    if rid:
        event_dict["request_id"] = rid
    if jid:
        event_dict["job_id"] = jid
    return event_dict


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout,
        level=level,
    )

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_context,
    ]

    renderer: Processor
    if settings.app_env == "dev":
        renderer = structlog.dev.ConsoleRenderer(colors=True)
    else:
        renderer = structlog.processors.JSONRenderer()

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return cast("structlog.stdlib.BoundLogger", structlog.get_logger(name))
