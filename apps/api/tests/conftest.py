"""Shared fixtures for the whole apps/api/tests suite.

Everything in this file is deliberately free of any `sunil.*` import at module level,
so this file itself always collects cleanly regardless of how much of the backend
exists yet. Anything that *does* need `sunil` (building the app, running migrations,
calling the orchestrator) is a plain function called from inside a test body via
`tests._helpers.import_or_fail`, never a fixture — see that module's docstring for why.

`live_env`/`require_live_settings` below are the one exception to "never a fixture" for
a `sunil` import, and only a lazy, function-body-local one guarded so a missing
`sunil.settings` degrades to "no live credentials" rather than an error — see that
fixture's own docstring.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError


def pytest_configure(config: pytest.Config) -> None:
    # Registered here (not in a pyproject.toml/pytest.ini we don't own) so `--strict-markers`
    # never trips on `live`, and so T21's CI can `-m "not live"` deselect exactly the tests
    # that need real credentials, per docs/M1_BUILD_PLAN.md T21.
    config.addinivalue_line(
        "markers",
        "live: needs GITHUB_TOKEN plus whichever provider key(s) the test itself names "
        "(see require_live_settings) and live network access; CI deselects these with "
        '`-m "not live"`. Skipped (not failed) when a required secret is absent.',
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
def live_env() -> Any | None:
    """The application's own view of live configuration: a real, unmodified
    `sunil.settings.Settings()` instance, read from `.env` at the repo root exactly the
    way the running app reads it. `None` means every `live`-marked test must skip (via
    `require_live_settings` below) -- this is the one place that decides "blocked on
    secrets/config" vs "can run".

    **Read through `Settings`, never `os.environ`** (constraint from the Delivery
    Manager, 2026-08-18): nothing exports these into the process environment -- they
    live in `.env` and `pydantic-settings` reads the file by path
    (`Settings.model_config["env_file"]`, an absolute, repo-root-relative path set in
    `sunil/settings.py` -- `Path(__file__).resolve().parents[3] / ".env"`, so this
    resolves correctly regardless of pytest's cwd). An `os.environ`-based version is
    blind to a credential that is plainly present in `.env` -- exactly the defect
    `tests/security/test_live_credential_scope.py` had before it was rebuilt; see that
    file's own module docstring for the incident.

    T26 added an autouse fixture that neutralises `Settings.model_config["env_file"]`
    for `tests/unit/` ONLY (`tests/unit/conftest.py`, a new file scoped to that
    directory, not an edit to this one) -- deliberately not this root conftest, per
    that fixture's own docstring, because everything under `tests/exit/` and
    `tests/security/` already builds its own `Settings` through an explicit,
    `_env_file=None`-disabled seam and has no bare `Settings()`/`create_app()` call
    site depending on the real file the way `tests/unit/test_main_app.py` does. A bare
    `Settings()` called from here is unaffected by that fixture and still reads the
    real file — verified directly (not assumed) against a throwaway `.env` during this
    fix; the temporary file never held anything but obviously-fake canary values and
    was deleted immediately after.

    Returns the whole `Settings` object, never a raw string or a dict of raw strings:
    every credential field on it is `SecretStr`, whose `repr` is `**********`. Handing
    back the object rather than unwrapped values means nothing downstream can
    accidentally interpolate, log, or `assert` on a raw secret — structurally, not by
    care. This is the exact property `test_live_credential_scope.py` had to be rebuilt
    to have, after `assert github and anthropic, "..."` rendered a live GitHub token
    through pytest's assertion-rewriting the moment `ANTHROPIC_API_KEY` correctly
    became optional (T25) and that assertion started failing; the token was revoked
    and rotated. `require_live_settings` below follows the same rule this file's
    logger-isolation fixture already follows for a different class of bug: fix the
    class structurally, not the two instances that happened to exhibit it.

    `None` only if `sunil.settings` does not exist yet, or a real `.env` exists but
    fails to construct a valid `Settings` at all (e.g. missing a mandatory field
    unrelated to which LLM provider is configured, such as `SESSION_SECRET`) — i.e.
    "cannot run this live test right now", never surfaced as a fixture error: every
    other test in the suite is equally unable to run in the first case, and the
    second is still "blocked on configuration", not a code defect this test should
    report as red.
    """
    try:
        from sunil.settings import Settings
    except ImportError:
        return None
    try:
        return Settings()
    except ValidationError:
        return None


def require_live_settings(live_env: Any | None, *, providers: tuple[str, ...] = ()) -> Any:
    """Call from inside a `live`-marked test body. Skips (never fails) unless
    `GITHUB_TOKEN` and every named provider's key are present on the real `Settings` —
    e.g. `require_live_settings(live_env, providers=("openai",))`.

    A per-provider ask, not a fixed trio (T25, 2026-08-18 fix): `ANTHROPIC_API_KEY` is
    now optional, and neither of ET-1/ET-11's live variants uses the Anthropic
    provider directly — `general_reasoning` resolves to `openai`
    (`config/models.yaml`, T24) — so neither test may block on a key it does not use.
    `GITHUB_TOKEN` is unconditional: the tool is not optional for M1
    (`sunil/settings.py`'s own field description). A future test that genuinely needs
    the Anthropic provider names it explicitly (`providers=("anthropic",)`) rather
    than this function guessing on every caller's behalf.

    Every check below unwraps a `SecretStr` only inline, inside a boolean expression —
    never bound to a local, never interpolated into the skip message, never an
    `assert` operand. This is the same structural rule
    `tests/security/test_live_credential_scope.py` follows (see that file's module
    docstring for why it is a rule rather than a style preference). Returns the
    `Settings` instance itself, never a raw string, so a test body that goes on to
    call `build_live_settings()` can only ever pass along a `SecretStr`.
    """
    if live_env is None:
        pytest.skip(
            "blocked on secrets/config, not on code: sunil.settings does not exist yet, "
            "or a real .env exists but Settings() could not construct from it. "
            "Not a red test result."
        )
    missing: list[str] = []
    if not live_env.github_token.get_secret_value():
        missing.append("GITHUB_TOKEN")
    for provider in providers:
        key = getattr(live_env, f"{provider}_api_key", None)
        if key is None or not key.get_secret_value():
            missing.append(f"{provider.upper()}_API_KEY")
    if missing:
        pytest.skip(
            "blocked on secrets, not on code: needs "
            f"{', '.join(missing)} in .env at the repo root. Not a red test result."
        )
    return live_env
