"""Structured logging: structlog with a JSON renderer, `contextvars` bound
per-request, and uvicorn's own loggers routed into the same processor chain
(FR-008; the trace spine (T4) and ET-6 both depend on there being exactly
one log format, not two).

T4 registers the redaction processor here (one line, same lane, per
`docs/M1_BUILD_PLAN.md` §2 T4's "Touches" note) by appending to
`shared_processors` below — untrusted content must never reach a log line
unredacted (T-32).
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence

import structlog

# Processors every log line passes through, whether it originates from
# structlog (`get_logger()`) or from stdlib `logging` (uvicorn's loggers,
# routed through `ProcessorFormatter` below). Keep this a plain list — T4
# appends its redaction processor here in one line.
shared_processors: list[structlog.types.Processor] = [
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
]


def configure_logging(*, log_level: str = "INFO", json_output: bool = True) -> None:
    """Configure structlog and stdlib `logging` to render through one chain.

    Call once, at application startup (`sunil.main.create_app()`). Safe to
    call more than once (e.g. across tests) — it always rebuilds the root
    handler rather than accumulating handlers.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(level)

    # Route uvicorn's own loggers into the same chain instead of letting
    # uvicorn install its own differently-formatted handlers — otherwise
    # access/error lines are unstructured text next to structured JSON.
    _route_into_root(("uvicorn", "uvicorn.error", "uvicorn.access"))


def _route_into_root(logger_names: Sequence[str]) -> None:
    for name in logger_names:
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True


def get_logger(*args: object, **kwargs: object) -> structlog.stdlib.BoundLogger:
    """Thin re-export so call sites do `from sunil.logging import get_logger`
    rather than depending on `structlog` directly everywhere."""
    return structlog.get_logger(*args, **kwargs)
