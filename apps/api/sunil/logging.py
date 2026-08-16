"""Structured logging: structlog with a JSON renderer, `contextvars` bound
per-request, and uvicorn's own loggers routed into the same processor chain
(FR-008; the trace spine (T4) and ET-6 both depend on there being exactly
one log format, not two).

`scrub_processor` (ADR-006/ET-10) is a **hard-wired, non-optional** part of
both chains — not something a caller opts into by mutating a list after
the fact. `configure_logging()` builds one fresh processor list per call
and hands the *same* list object to both `structlog.configure()` and
`ProcessorFormatter(foreign_pre_chain=...)`, so the two chains cannot drift
apart structurally.

**A prior revision of this module got this wrong in a way worth recording.**
It exposed a public, mutable `shared_processors` list and instructed
callers to append to it after the fact. That is a real bug, not a style
nit: `structlog.configure(processors=[*shared_processors, ...])` **unpacks
the list into a new one** at call time, while
`ProcessorFormatter(foreign_pre_chain=shared_processors)` keeps the
**same list object** by reference. An append *after* `configure_logging()`
had already run would reach the foreign (uvicorn) chain — because that
chain still held a live reference — but silently miss structlog's own
chain, which had already been snapshotted. `cache_logger_on_first_use=True`
compounds it further: already-bound loggers never see a later
reconfiguration at all. The fix is `configure_logging(extra_processors=...)`
below: processors are supplied at the one point the whole chain is built,
never appended to a list that only one of the two consumers still sees.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence

import structlog

from sunil.redaction import scrub_processor

# The processors every log line passes through unconditionally, whether it
# originates from structlog (`get_logger()`) or from stdlib `logging`
# (uvicorn's loggers, routed through `ProcessorFormatter` below).
# `scrub_processor` is part of this base list, not an opt-in extra, so a
# secret cannot reach a log line by construction — see the module
# docstring for why this must never become "append after configure".
_BASE_PROCESSORS: tuple[structlog.types.Processor, ...] = (
    structlog.contextvars.merge_contextvars,
    structlog.processors.add_log_level,
    structlog.processors.TimeStamper(fmt="iso", utc=True),
    structlog.processors.StackInfoRenderer(),
    structlog.processors.format_exc_info,
    scrub_processor,
)


def configure_logging(
    *,
    log_level: str = "INFO",
    json_output: bool = True,
    extra_processors: Sequence[structlog.types.Processor] = (),
) -> None:
    """Configure structlog and stdlib `logging` to render through one chain.

    Call once, at application startup (`sunil.main.create_app()`'s
    lifespan). Safe to call more than once (e.g. across tests) — it always
    rebuilds the root handler rather than accumulating handlers, and it
    always builds a fresh processor list rather than depending on one a
    prior call (or a prior test) may have mutated.

    `extra_processors` — appended after the base chain, before the
    formatter/renderer step — exists for a caller (a test, a future
    feature) that needs to add a processor for this one configuration
    without touching the base list at all.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Built once, used as the *same* object for both consumers below — the
    # structural guarantee that fixes the class of bug this module's
    # docstring describes.
    processors: list[structlog.types.Processor] = [*_BASE_PROCESSORS, *extra_processors]

    structlog.configure(
        processors=[*processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer() if json_output else structlog.dev.ConsoleRenderer()
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=processors,
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
