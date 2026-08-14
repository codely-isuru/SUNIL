"""Detect duplicate pytest test-module basenames under apps/api/tests/.

Guards against the collection-error defect class T22 was raised to fix: two
lanes each ship a file with the same basename (e.g. two `test_capture.py` in
different directories), neither directory is a package (no `__init__.py`),
and pytest's default ("prepend") import mode imports test files by their
bare filename. The second file collides with the first at import time and
pytest ABORTS COLLECTION FOR THE ENTIRE SUITE ("import file mismatch",
`pytest` exit code 2) -- a merged tree that runs zero tests, not just the
two colliding files.

This is invisible inside any single lane's own branch: two lanes can each
be 100% green in isolation and only collide the moment they are merged
together, which is exactly the moment nobody is re-reading either lane's
diff. A CI job that only reacts to pytest's own exit code still catches
this (exit 2 is nonzero), but the failure reads as a cryptic pytest internal
message unless something names the actual defect. This script is that
naming: a fast, static, dependency-free pre-check that runs before pytest is
even invoked, and points at the exact colliding paths.

It is deliberately NOT a substitute for a passing test suite -- it only
catches this one shape of collision. It also deliberately does not assert
a minimum collected-test count: with six lanes merging over a three-day
build, any fixed number is stale within hours and either flags real,
smaller-than-expected merges as false failures or is never tightened enough
to mean anything. A duplicate-basename scan has no such decay -- it is
correct on day one and still correct on the last day of the milestone.

Exit 0: no collision (or the tests directory does not exist yet).
Exit 1: at least one collision found; every offending path is printed.
"""

from __future__ import annotations

import sys
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TESTS_ROOT = REPO_ROOT / "apps" / "api" / "tests"


def find_duplicate_basenames(tests_root: Path) -> dict[str, list[Path]]:
    by_basename: dict[str, list[Path]] = defaultdict(list)
    for path in tests_root.rglob("test_*.py"):
        by_basename[path.name].append(path)
    return {name: paths for name, paths in by_basename.items() if len(paths) > 1}


def main() -> int:
    if not TESTS_ROOT.exists():
        print(f"OK: {TESTS_ROOT} does not exist yet -- nothing to check.")
        return 0

    duplicates = find_duplicate_basenames(TESTS_ROOT)
    if not duplicates:
        collected = sum(1 for _ in TESTS_ROOT.rglob("test_*.py"))
        print(f"OK: no duplicate test-module basenames ({collected} test files scanned).")
        return 0

    print("FAIL: duplicate test-module basenames found under apps/api/tests/.")
    print(
        "Two files sharing a basename can abort pytest's entire collection\n"
        "(exit code 2, 'import file mismatch') the moment both land on the\n"
        "same branch, even though each passed in its own lane. Fix options,\n"
        "in order of preference:\n"
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

    return 1


if __name__ == "__main__":
    sys.exit(main())
