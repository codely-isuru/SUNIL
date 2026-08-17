"""Shared constants and gates for the T19 security suite.

**Why this module exists, and why it is not `conftest.py`.** pytest resolves
`conftest.py` by *directory scope* and injects fixtures with no import
statement at all. Importing the conftest module by name bypasses that and does a
plain module import, which resolves to whichever `conftest.py` reached
`sys.path` first — so the moment a second one is collected in the same run
(`tests/unit/tool_framework/conftest.py`, T8) the security suite fails with
`ImportError: cannot import name 'REPO_ROOT' from 'conftest'`. Both suites
pass when run separately by path, which is exactly what makes it dangerous:
the security suite goes green in isolation and red only in the full run.

So: fixtures stay in `conftest.py` (injected, never imported); constants and
gates live here under a name that cannot collide, and are imported explicitly.
"""

from __future__ import annotations

import importlib
import pathlib
from types import ModuleType

import pytest

# apps/api/tests/security/security_helpers.py -> security -> tests -> api -> apps -> repo root
REPO_ROOT = pathlib.Path(__file__).resolve().parents[4]
SUNIL_PKG = REPO_ROOT / "apps" / "api" / "sunil"

# Obviously-fake values. None of these is, or resembles, a real credential.
FAKE_ENV: dict[str, str] = {
    "ANTHROPIC_API_KEY": "sk-ant-fake-security-suite-value",
    "GITHUB_TOKEN": "github_pat_fake-security-suite-value",
    "OPENAI_API_KEY": "sk-fake-security-suite-value-for-openai",
    "SESSION_SECRET": "fake-security-suite-session-secret",
    "OWNER_USERNAME": "security-suite-owner",
    "OWNER_PASSWORD": "fake-security-suite-owner-password",
}


def require(module_path: str, owed_by: str) -> ModuleType:
    """Import a module a later task owns, or fail loudly and legibly.

    `pytest.fail`, never `pytest.skip`: a skipped security test reports green,
    which is T21's exit-code-5 trap wearing a different hat.

    **Distinguishes an absent control from a broken environment.** A
    `ModuleNotFoundError` raised while importing `module_path` may be for a
    *different* module entirely — a missing third-party dependency that
    `module_path` imports transitively. Reporting that as "control absent,
    owed by T10" is precisely the misattribution that made 24 of these tests
    unreadable once before, so the two cases now say different things.
    """
    try:
        return importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        missing = exc.name or ""
        requested_root = module_path.split(".")[0]
        if missing and not (missing == module_path or module_path.startswith(f"{missing}.")):
            if missing.split(".")[0] != requested_root:
                pytest.fail(
                    f"ENVIRONMENT, not a finding: `{module_path}` exists but could not be "
                    f"imported because the dependency `{missing}` is not installed. Install the "
                    'backend dev extras (`pip install -e ".[dev]"` in apps/api) and re-run; '
                    "this is not an absent control."
                )
        pytest.fail(
            f"RED - control absent, test intact: `{module_path}` does not exist yet "
            f"(owed by {owed_by}). Underlying import error: {exc}"
        )


def require_dir(path: pathlib.Path, owed_by: str) -> pathlib.Path:
    """Assert a package directory exists.

    Import-boundary tests are negative assertions ("no file outside X imports
    Y"). With zero files they pass vacuously, which is a false green. This gate
    makes them RED until the package they police actually exists.
    """
    if not path.is_dir():
        pytest.fail(
            f"RED - control absent, test intact: `{path.relative_to(REPO_ROOT)}` does not "
            f"exist yet (owed by {owed_by}), so this boundary is unproven rather than clean."
        )
    return path
