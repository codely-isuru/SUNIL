"""Shared fixtures for the whole apps/api/tests suite.

Everything in this file is deliberately free of any `sunil.*` import, so this file
itself always collects cleanly regardless of how much of the backend exists yet.
Anything that *does* need `sunil` (building the app, running migrations, calling the
orchestrator) is a plain function called from inside a test body via
`tests._helpers.import_or_fail`, never a fixture — see that module's docstring for why.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest


def pytest_configure(config: pytest.Config) -> None:
    # Registered here (not in a pyproject.toml/pytest.ini we don't own) so `--strict-markers`
    # never trips on `live`, and so T21's CI can `-m "not live"` deselect exactly the tests
    # that need ANTHROPIC_API_KEY / GITHUB_TOKEN, per docs/M1_BUILD_PLAN.md T21.
    config.addinivalue_line(
        "markers",
        "live: needs real ANTHROPIC_API_KEY and/or GITHUB_TOKEN and live network access; "
        'CI deselects these with `-m "not live"`. Skipped (not failed) when secrets are absent.',
    )


# --------------------------------------------------------------------------------------
# Pure, sunil-free fixtures. Safe as real pytest fixtures because nothing here can fail
# for the reason "the backend doesn't exist yet" -- see _helpers.py for why that
# distinction governs what may and may not be a fixture in this suite.
# --------------------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolate_stdlib_logger_registry() -> Iterator[None]:
    """Cross-lane test-isolation fix, not a rename.

    `tests/security/test_secret_exposure.py` and `tests/unit/test_redaction.py` both
    call `get_logger("t")` -- the same literal name -- and Python's stdlib `logging`
    module keeps ONE process-wide registry of named `Logger` objects
    (`logging.Logger.manager.loggerDict`) that `structlog.configure()` does not reset.
    Whichever test runs first can leave state (handlers/level/propagate/disabled) on
    that shared object for the other to inherit. Confirmed by reproduction, not by
    the report alone: `test_scrub_through_the_real_structlog_chain_redacts_an_exception_value`
    passed standalone (`pytest tests/unit/test_redaction.py::test_..._exception_value`)
    and failed only as part of the full suite (`json.decoder.JSONDecodeError: Expecting
    value` -- the captured buffer was empty, meaning the "t" logger's handler by the
    time this test ran was not the one the test had just installed).

    This is the general form of memory lesson L-002 (never let one run's leftover
    state look like another run's evidence) applied to the stdlib logging registry
    itself. A two-line rename in the two colliding files fixes these two names; it
    does not fix the class -- a third test reusing either name later reintroduces
    the identical bug. An autouse fixture here, in the one conftest QA owns at the
    root of the whole suite, closes the class for every test without editing a line
    in either of the two files that exhibited it (both belong to other lanes).

    Deliberately conservative in what it touches:
    - Only loggers *created during this test* are removed afterward, so a logger
      pytest's own logging plugin (or anything else) set up before any test ran is
      never touched.
    - Every logger that already existed has its mutable state snapshotted and
      restored, so a test that mutates a shared logger's configuration can never
      leak that mutation forward into a later test either.
    - The root logger is untouched entirely -- `logging.Logger.manager.loggerDict`
      holds only *named* loggers (`getLogger("some-name")`); the root logger is a
      separate object this fixture never reaches, so `configure_logging()`'s normal
      handler setup on the root logger is unaffected.
    """
    manager = logging.Logger.manager
    pre_existing_names = set(manager.loggerDict.keys())
    saved_state = {
        name: (list(logger.handlers), logger.level, logger.propagate, logger.disabled)
        for name, logger in manager.loggerDict.items()
        if isinstance(logger, logging.Logger)
    }
    try:
        yield
    finally:
        for name in set(manager.loggerDict.keys()) - pre_existing_names:
            del manager.loggerDict[name]
        for name, (handlers, level, propagate, disabled) in saved_state.items():
            logger = manager.loggerDict.get(name)
            if isinstance(logger, logging.Logger):
                logger.handlers = handlers
                logger.level = level
                logger.propagate = propagate
                logger.disabled = disabled


@pytest.fixture
def request_id() -> str:
    """A fresh UUID4 per test.

    Every exit test scopes its DB assertions to this one value (WHERE request_id = ?),
    never to table totals — see .minions/memory/backend_engineer.md L-002. Row counts
    from any other run, or from another test in the same session, are never evidence.
    """
    return str(uuid.uuid4())


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A SQLite file unique to this test. Never shared, never reused across tests or
    across runs -- the isolation itself is part of what makes L-002 unrepeatable here.
    """
    return tmp_path / "sunil_test.db"


@pytest.fixture
def database_url(db_path: Path) -> str:
    return f"sqlite+aiosqlite:///{db_path.as_posix()}"


@pytest.fixture
def qa_config_dir() -> Path:
    """QA's OWN config/*.yaml fixture tree (apps/api/tests/exit/fixtures/config/),
    deliberately separate from the real `config/` directory T3 owns. Pointed at via the
    documented `SUNIL_CONFIG_DIR` env var (ARCHITECTURE_V1.md §14.4/§14.5), so these
    tests never depend on T3's files existing, their exact content, or their timing.
    """
    return Path(__file__).parent / "exit" / "fixtures" / "config"


@pytest.fixture
def live_env() -> dict[str, str] | None:
    """Real ANTHROPIC_API_KEY / GITHUB_TOKEN from the ambient OS environment, if both
    are present. `None` means live-marked tests must skip (see `require_live_credentials`
    below) -- this is the one place that decides "blocked on secrets" vs "can run".
    """
    key = os.environ.get("ANTHROPIC_API_KEY")
    token = os.environ.get("GITHUB_TOKEN")
    if key and token:
        return {"ANTHROPIC_API_KEY": key, "GITHUB_TOKEN": token}
    return None


def require_live_credentials(live_env: dict[str, str] | None) -> dict[str, str]:
    """Call from inside a `live`-marked test body. Skips (does not fail) when secrets
    are absent -- per the brief, tests blocked purely on missing Day-3 secrets are a
    different state to a RED test blocked on missing code, and must be reported as such.
    """
    if live_env is None:
        pytest.skip(
            "blocked on secrets, not on code: needs a real ANTHROPIC_API_KEY and GITHUB_TOKEN "
            "in the environment (arriving Day 3 per the brief). Not a red test result."
        )
    return live_env
