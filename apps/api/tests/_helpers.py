"""The one mechanism every exit test uses to stay RED for the right reason.

At hour 0 of the M1 build, none of `sunil.*` exists yet. A test file that does
`from sunil.core.orchestrator.turn import run_turn` at module scope would fail to
*import*, and pytest would report that as a **collection error** for the whole file —
no individual test names, no per-test traceback, and (per docs/M1_BUILD_PLAN.md T1's
own warning) the kind of failure that is easy to mistake for "the harness is broken"
rather than "the feature does not exist".

`import_or_fail()` is a plain function, never a fixture, and it must always be called
from *inside* a test's own body (or from a helper the test body calls directly) —
never from module scope and never from a `@pytest.fixture`. That placement is what
turns a missing module into a normal, informative, per-test **FAILED** result (raised
during test execution) instead of a collection error or a fixture-setup ERROR (raised
during collection/setup, and reported in a different section of pytest's output).

See docs/ARCHITECTURE_V1.md and docs/M1_BUILD_PLAN.md §6 for what each dotted path is
expected to resolve to once the corresponding task lands.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest


def import_or_fail(dotted_path: str, *, blocked_on: str) -> Any:
    """Import ``pkg.mod.attr`` and return ``attr``.

    On any import failure, fail the *currently running* test with a message naming
    the exact path that is missing and which build-plan task is expected to supply
    it. Must be called from within a test body — see module docstring.
    """
    module_path, _, attr_name = dotted_path.rpartition(".")
    if not module_path:
        pytest.fail(
            f"import_or_fail() needs a dotted `module.attr` path, got {dotted_path!r}",
            pytrace=False,
        )
    try:
        module = importlib.import_module(module_path)
    except ModuleNotFoundError as exc:
        pytest.fail(
            f"NOT YET BUILT: module `{module_path}` does not exist yet "
            f"({exc.__class__.__name__}: {exc}). Blocked on {blocked_on}. "
            f"This is the correct RED state before that task merges — re-run after it lands.",
            pytrace=False,
        )
    except ImportError as exc:
        pytest.fail(
            f"NOT YET BUILT: `{module_path}` exists but failed to import cleanly "
            f"({exc.__class__.__name__}: {exc}). Blocked on {blocked_on}.",
            pytrace=False,
        )
    try:
        return getattr(module, attr_name)
    except AttributeError as exc:
        pytest.fail(
            f"NOT YET BUILT: `{module_path}` exists but has no attribute `{attr_name}` yet "
            f"({exc}). Blocked on {blocked_on}. If this fires *after* {blocked_on} has "
            f"landed, the frozen contract and the real code have drifted — that is a real "
            f"defect, report it, don't adjust the test to match.",
            pytrace=False,
        )


def fail_not_built(reason: str, *, blocked_on: str) -> None:
    """Explicit red failure for a test body that cannot even attempt an import yet
    (e.g. it needs a mechanism the frozen contract does not document — see the T18
    report's "ambiguity" list). Still a FAILED test, never a collection/setup error.
    """
    pytest.fail(f"NOT YET BUILT: {reason}. Blocked on {blocked_on}.", pytrace=False)
