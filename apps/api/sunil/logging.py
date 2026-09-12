"""Structured logging: structlog with a JSON renderer, and uvicorn's own loggers
routed into the same processor chain — exactly one log format, because the trace
spine's "reconstructable from stored records alone" claim leans on it.

`scrub_processor` (ADR-006 / C5 §3) is a **hard-wired, non-optional** part of
both chains, not something a caller opts into by mutating a list after the fact.
`configure_logging()` builds one fresh processor list per call and hands the
*same* list object to both `structlog.configure()` and
`ProcessorFormatter(foreign_pre_chain=...)`, so the two cannot drift apart.

**The M1 defect this shape exists to prevent** (recorded, because it is subtle):
a public mutable `shared_processors` list that callers appended to after
`configure_logging()` had run reached the foreign (uvicorn) chain — which still
held a live reference — but silently missed structlog's own chain, because
`structlog.configure(processors=[*shared_processors, ...])` unpacks into a NEW
list at call time. `cache_logger_on_first_use=True` compounds it: already-bound
loggers never see a later reconfiguration at all. Processors are therefore
supplied at the one point the whole chain is built (`extra_processors=`), never
appended to a list only one consumer still sees.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence

import structlog

from sunil.redaction import scrub_processor

# Every log line passes through these unconditionally, whether it comes from
# structlog (`get_logger()`) or from stdlib logging (uvicorn, routed through
# `ProcessorFormatter`). `scrub_processor` is part of this base list, not an
# opt-in extra, so a secret cannot reach a log line by construction.
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

    Called once per application, from `create_app()`. Safe to call again (tests,
    a second app in the same process): it rebuilds the root handler rather than
    accumulating handlers, and always builds a fresh processor list rather than
    depending on one a prior call may have mutated.
    """
    level = getattr(logging, log_level.upper(), logging.INFO)

    # Built once, used as the SAME object by both consumers below.
    processors: list[structlog.types.Processor] = [*_BASE_PROCESSORS, *extra_processors]

    structlog.configure(
        processors=[*processors, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=False,
    )

    renderer: structlog.types.Processor = (
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer()
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

    # Route uvicorn's loggers into the same chain instead of letting uvicorn
    # install its own differently-formatted handlers.
    _route_into_root(("uvicorn", "uvicorn.error", "uvicorn.access"))


def _route_into_root(logger_names: Sequence[str]) -> None:
    for name in logger_names:
        logger = logging.getLogger(name)
        logger.handlers = []
        logger.propagate = True


def get_logger(*args: object, **kwargs: object) -> structlog.stdlib.BoundLogger:
    """Thin re-export, so call sites depend on `sunil.logging` rather than on
    `structlog` directly everywhere."""
    return structlog.get_logger(*args, **kwargs)
