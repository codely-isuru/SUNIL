"""Shared fixtures for the T19 security suite (docs/M1_BUILD_PLAN.md §5 T19).

Two deliberate properties of this suite:

1. **No test here needs a real credential.** Every value is an obvious fake.
   That is a security property, not a limitation — `M1_BUILD_PLAN.md` §5 T21:
   "A CI job that needs a secret to pass is a CI job that will leak one."
   The single exception is marked `@pytest.mark.live` and is deselected by
   CI's `-m "not live"`.

2. **A missing feature fails; it never skips.** `require()` below calls
   `pytest.fail`, not `pytest.skip`. A skipped security test reports green,
   which is T21's exit-code-5 trap wearing a different hat. While a control
   is unbuilt, its test is RED and says so in the failure message.
"""

from __future__ import annotations

import importlib
import io
import logging
import pathlib
from collections.abc import Iterator
from types import ModuleType

import pytest

# apps/api/tests/security/conftest.py -> security -> tests -> api -> apps -> repo root
REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
SUNIL_PKG = REPO_ROOT / "apps" / "api" / "sunil"

# Obviously-fake values. None of these is, or resembles, a real credential.
FAKE_ENV: dict[str, str] = {
    "ANTHROPIC_API_KEY": "sk-ant-fake-security-suite-value",
    "GITHUB_TOKEN": "github_pat_fake-security-suite-value",
    "SESSION_SECRET": "fake-security-suite-session-secret",
    "OWNER_USERNAME": "security-suite-owner",
    "OWNER_PASSWORD": "fake-security-suite-owner-password",
}


def require(module_path: str, owed_by: str) -> ModuleType:
    """Import a module a later task owns, or fail loudly and legibly."""
    try:
        return importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"RED — control absent, test intact: `{module_path}` does not exist yet "
            f"(owed by {owed_by}). Underlying import error: {exc}"
        )


def require_dir(path: pathlib.Path, owed_by: str) -> pathlib.Path:
    """Assert a package directory exists.

    Import-boundary tests are negative assertions ("no file outside X imports
    Y"). With zero files they pass vacuously, which is a false green. This
    gate makes them RED until the package they police actually exists.
    """
    if not path.is_dir():
        pytest.fail(
            f"RED — control absent, test intact: `{path.relative_to(REPO_ROOT)}` does not "
            f"exist yet (owed by {owed_by}), so this boundary is unproven rather than clean."
        )
    return path


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Every required variable set to an obvious fake, `.env` bypassed."""
    for key, value in FAKE_ENV.items():
        monkeypatch.setenv(key, value)
    return dict(FAKE_ENV)


@pytest.fixture
def log_capture() -> Iterator[io.StringIO]:
    """Capture what T1's real structlog chain renders, formatter included."""
    from sunil.logging import configure_logging

    configure_logging(log_level="DEBUG", json_output=True)
    root = logging.getLogger()
    original = list(root.handlers)
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    if original:
        handler.setFormatter(original[0].formatter)
    root.handlers = [handler]
    try:
        yield buffer
    finally:
        root.handlers = original
