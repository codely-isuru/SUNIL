"""Detect the cross-lane test-collection collision family under apps/api/tests/.

Two related, independently-caused defects, both invisible inside any single
lane's own branch and both only visible once two lanes are merged together --
which is exactly the moment nobody is re-reading either lane's diff. Neither
is hypothetical: both were hit for real during M1's build (T22, 2026-08-14),
by two different lane pairs, one commit apart.

CHECK 1 -- duplicate test modules THAT PYTEST WOULD ACTUALLY COLLIDE ON (the
    original T22 incident, corrected after a false positive found the same
    day). Two lanes each ship a `test_*.py` with the same basename (T2's
    `tests/unit/test_capture.py`, T3's `tests/unit/registry/test_capture.py`).
    Neither directory was a package (no `__init__.py`) at the time, so
    pytest's default ("prepend") import mode imported both test files by
    their bare filename. The second file collided with the first at import
    time and pytest ABORTED COLLECTION FOR THE ENTIRE SUITE ("import file
    mismatch", exit code 2) -- a merged tree that runs zero tests, not just
    the two colliding files.

    THE FALSE POSITIVE (found by a lane, reported honestly instead of worked
    around): a bare-basename check flags ANY two `test_*.py` files sharing a
    name, but pytest does not actually collide on a shared basename when
    package structure (an `__init__.py` chain) disambiguates them --
    `tests/unit/providers/test_base.py` and
    `tests/unit/tool_framework/test_base.py` both have an `__init__.py` in
    their own directory, so pytest imports them as `providers.test_base` and
    `tool_framework.test_base` respectively: two distinct module objects,
    never a collision. A check that ignores this flags a real, working
    pairing as broken -- worse than missing a real collision, because it
    tells someone to rename a file that was never wrong.

    THE RULE: duplicate basenames matter only where package structure does
    not disambiguate them. This is checkable, not decaying, because it is a
    property of the tree (does an `__init__.py` chain exist above this file,
    all the way up from its own directory?) rather than of an invocation or
    a headcount. `_pytest_module_name()` below reconstructs the same dotted
    module name pytest's own prepend-mode import machinery would compute --
    walk up from the file through every ancestor directory that has an
    `__init__.py`, stop at the first one that does not, and join what was
    collected. Two files collide if and only if that computed name is
    identical. `test_capture.py`/`test_capture.py` with no `__init__.py`
    anywhere both reduce to the bare name `test_capture` -- collision, as
    before. `providers/test_base.py` and `tool_framework/test_base.py`, each
    packaged, reduce to `providers.test_base` and `tool_framework.test_base`
    -- distinct, no collision.

CHECK 2 -- a bare `from conftest import ...` / `import conftest` statement
    (the second T22 incident, one commit later). `conftest.py` is the ONE
    basename that appears in every test directory BY DESIGN -- pytest finds
    and scopes fixtures from every `conftest.py` on the path to a test file
    automatically, with no import statement at all, and having many of them
    is completely normal and never a collision risk by itself. Flagging
    every duplicate `conftest.py` the way check 1 flags `test_*.py` would
    therefore be pure noise on every lane, forever -- which is exactly why
    check 1's `test_*.py` glob does not match `conftest.py` in the first
    place (see "Why conftest.py is not in check 1" below).

    The actual defect is narrower and does not depend on how many
    `conftest.py` files exist: some test file bypasses pytest's fixture
    mechanism and imports a plain (non-fixture) name out of `conftest.py`
    directly -- `from conftest import FAKE_ENV`, say -- using a BARE,
    non-relative import. That import is resolved by plain Python import
    machinery, not by pytest's directory-scoped fixture lookup, and plain
    Python caches modules in `sys.modules` by name. The moment ANY other
    `conftest.py` anywhere in the merged tree is imported first (which, on
    a CI run of the whole suite, it always eventually is), `sys.modules
    ["conftest"]` may already hold a *different* directory's conftest
    module, and the bare import silently resolves to the wrong one --
    surfacing as `ImportError: cannot import name 'X'` for whatever name the
    wrong module doesn't happen to define. This is the same root cause as
    check 1 (prepend mode's flat, package-free module cache), reached
    through a manual import statement instead of pytest's own collector, so
    it needs its own check rather than being folded into check 1's count.

    This is flagged UNCONDITIONALLY -- regardless of how many `conftest.py`
    files currently exist in the tree -- for the same "no stale threshold"
    reason check 1 does not gate on a minimum test count: the pattern is a
    ticking time bomb the moment ANY second `conftest.py` lands anywhere in
    the merged tree, which is not knowable, or worth tracking, from the
    writing lane's own branch. Catching the bare import itself, rather than
    counting `conftest.py` files, has no expiry and needs no recalibration.

Why conftest.py is not in check 1: pytest's own conftest loading is not the
same code path as its test-module collection, and multiple `conftest.py`
files coexisting is the supported, by-design way to scope fixtures per
directory -- flagging that would be noise on every lane, every day, for a
shape that is never actually a problem by itself. The problem is only ever
the manual bare import in check 2, so that is what is scanned for.

Neither check is a substitute for a passing test suite -- each catches one
shape of collision, cheaply and statically, before pytest is even invoked.

Exit 0: neither defect found (or the tests directory does not exist yet).
Exit 1: at least one instance of either found; every offending path/line is
printed.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = REPO_ROOT / "apps" / "api" / "tests"

# Matches `from conftest import ...` / `import conftest` / `import conftest as x`,
# but NOT `from .conftest import ...` (relative) or
# `from tests.foo.conftest import ...` (package-qualified) -- both of those
# require real package structure to even run, and neither is ambiguous the
# way a bare "conftest" name is under prepend-mode's flat module cache.
_BARE_CONFTEST_IMPORT_RE = re.compile(
    r"^\s*(?:from\s+conftest\s+import\s+\S|import\s+conftest\b)"
)


def _pytest_module_name(path: Path, repo_root: Path) -> str:
    """Reconstruct the dotted module name pytest's default ("prepend")
    import mode would assign `path`: the file's own stem, prefixed by every
    ancestor directory name for as long as that ancestor has an
    `__init__.py` (making it a package pytest folds into the qualified
    name), stopping at the first ancestor that does not (which is where
    pytest inserts the "rootpath" onto `sys.path` instead of climbing
    further). Bounded at `repo_root` as a safety stop -- it will never have
    an `__init__.py` in this repo, so the loop always terminates there at
    the latest.
    """
    components = [path.stem]
    current = path.parent
    while current != repo_root and (current / "__init__.py").exists():
        components.append(current.name)
        current = current.parent
    return ".".join(reversed(components))


def find_duplicate_basenames(tests_root: Path) -> dict[str, list[Path]]:
    """Check 1: any `test_*.py` file whose pytest-resolved dotted module
    name collides with another's. A shared basename alone (e.g. two
    `test_base.py`) is NOT reported if package structure (an `__init__.py`
    chain on one or both sides) already gives them distinct qualified
    names -- that is a normal, working pytest layout, not a defect."""
    by_module_name: dict[str, list[Path]] = defaultdict(list)
    for path in tests_root.rglob("test_*.py"):
        module_name = _pytest_module_name(path, REPO_ROOT)
        by_module_name[module_name].append(path)
    return {name: paths for name, paths in by_module_name.items() if len(paths) > 1}


def find_bare_conftest_imports(tests_root: Path) -> dict[Path, list[str]]:
    """Check 2: any bare `from conftest import ...` / `import conftest` line,
    in ANY `.py` file under tests_root (test modules and conftest.py files
    alike -- one conftest.py importing a sibling conftest.py this way is
    exactly as fragile as a test file doing it)."""
    offenders: dict[Path, list[str]] = {}
    for path in tests_root.rglob("*.py"):
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        matches = [
            line.strip()
            for line in text.splitlines()
            if _BARE_CONFTEST_IMPORT_RE.match(line)
        ]
        if matches:
            offenders[path] = matches
    return offenders


def main() -> int:
    if not TESTS_ROOT.exists():
        print(f"OK: {TESTS_ROOT} does not exist yet -- nothing to check.")
        return 0

    ok = True

    duplicates = find_duplicate_basenames(TESTS_ROOT)
    if duplicates:
        ok = False
        print("FAIL: colliding test-module names found under apps/api/tests/.")
        print(
            "These files resolve to the SAME pytest module name, not merely the same\n"
            "basename -- package structure (__init__.py) does not already tell them\n"
            "apart, so pytest's default import mode will collide on them at import\n"
            "time and ABORT COLLECTION FOR THE ENTIRE SUITE (exit code 2, 'import file\n"
            "mismatch') the moment both land on the same branch, even though each\n"
            "passed in its own lane. Fix options, in order of preference:\n"
            "  1. Rename the file -- but ONLY within a lane/task you own\n"
            "     (docs/M1_BUILD_PLAN.md file-ownership rule). Never rename\n"
            "     another lane's file to work around your own collision.\n"
            "  2. Nest one of the files in a package with its own __init__.py\n"
            "     so it collects under a distinct dotted module name -- but\n"
            "     confirm first that nothing in that lane relies on prepend\n"
            "     mode's implicit sys.path insertion for a bare\n"
            "     `from conftest import ...`; packaging changes that import\n"
            "     shape too."
        )
        for name, paths in sorted(duplicates.items()):
            print(f"\n  {name}:")
            for p in paths:
                print(f"    - {p.relative_to(REPO_ROOT)}")
    else:
        collected = sum(1 for _ in TESTS_ROOT.rglob("test_*.py"))
        print(
            f"OK: no colliding test-module names ({collected} test files scanned; "
            f"shared basenames disambiguated by package structure are not a defect)."
        )

    bare_imports = find_bare_conftest_imports(TESTS_ROOT)
    if bare_imports:
        ok = False
        print("\nFAIL: bare `from conftest import ...` / `import conftest` found.")
        print(
            "conftest.py fixtures are found by pytest automatically -- by directory\n"
            "scope, with no import statement at all. A bare, non-relative import of a\n"
            "plain (non-fixture) name from `conftest` bypasses that mechanism and goes\n"
            "through plain Python's sys.modules cache instead, which is ambiguous the\n"
            "moment ANY other conftest.py exists anywhere in the merged tree -- it can\n"
            "silently resolve to the WRONG conftest module and fail with a confusing\n"
            "`ImportError: cannot import name '...'` far from the real cause. Fix,\n"
            "within the owning lane only: use a fixture parameter instead of a plain\n"
            "import for anything pytest can inject, or share the constant through a\n"
            "properly package-qualified/relative import if it truly is not a fixture."
        )
        for path, lines in sorted(bare_imports.items()):
            print(f"\n  {path.relative_to(REPO_ROOT)}:")
            for line in lines:
                print(f"    {line}")
    else:
        conftest_count = sum(1 for _ in TESTS_ROOT.rglob("conftest.py"))
        print(
            f"OK: no bare `from conftest import ...` / `import conftest` found "
            f"({conftest_count} conftest.py file(s) present -- fine, by design)."
        )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
