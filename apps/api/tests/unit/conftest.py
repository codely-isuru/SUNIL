"""Fixtures for the unit suite only.

Imported by name rather than declared via `pytest_plugins` (which pytest allows
only in a rootdir conftest) and deliberately NOT placed in a top-level
conftest — see `tests/spine_harness.py`: nothing here may change how the frozen
contract suites in `tests/contracts/` collect or run.
"""

from tests.spine_harness import (  # noqa: F401 - re-exported as fixtures
    _clean_redaction_registry,
    build_settings,
    session_factory,
)
