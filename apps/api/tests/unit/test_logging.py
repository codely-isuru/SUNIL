"""``sunil.logging`` — one processor chain, redaction baked in.

The M1 defect this module's shape exists to prevent is worth a test rather than
a comment: a public mutable `shared_processors` list that callers append to
reaches the foreign (uvicorn) chain by reference but silently misses structlog's
own chain, which `structlog.configure(processors=[*shared, ...])` already
snapshotted.
"""

from __future__ import annotations

import logging

from sunil.logging import configure_logging, get_logger
from sunil.redaction import scrub_processor


def test_redaction_is_part_of_the_base_chain_not_an_opt_in() -> None:
    from sunil.logging import _BASE_PROCESSORS

    assert scrub_processor in _BASE_PROCESSORS


def test_configure_logging_is_idempotent_and_does_not_accumulate_handlers() -> None:
    configure_logging(log_level="INFO")
    first = len(logging.getLogger().handlers)

    configure_logging(log_level="DEBUG")

    assert len(logging.getLogger().handlers) == first == 1


def test_uvicorns_loggers_are_routed_into_the_one_chain() -> None:
    configure_logging(log_level="INFO")

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logger = logging.getLogger(name)
        assert logger.handlers == [] and logger.propagate is True


def test_a_registered_secret_never_reaches_a_rendered_log_line(capsys) -> None:
    from sunil.redaction import register, reset_registry_for_tests

    reset_registry_for_tests()
    register("log-leak-secret-value", name="probe")
    configure_logging(log_level="INFO")

    get_logger("test").info("probe_event", note="carrying log-leak-secret-value inline")

    captured = capsys.readouterr()
    assert "log-leak-secret-value" not in captured.out + captured.err
    reset_registry_for_tests()
