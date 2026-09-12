"""Fixtures for the unit suite only. (integration-w1 union of the spine and
Stream D conftests — both were additive; nothing here may change how the frozen
contract suites in ``tests/contracts/`` collect or run.)

Spine half: fixtures imported by name rather than via ``pytest_plugins`` —
see ``tests/spine_harness.py``.

Stream D half — Windows event-loop policy (load-bearing, not hygiene):
psycopg 3's async mode refuses asyncio's default Windows ``ProactorEventLoop``,
and ``postgresql+psycopg`` is ARCHITECTURE_V2 §5's normative driver (ruling
S-1), so every async Postgres test on a Windows build machine needs the
``SelectorEventLoop`` policy below. Without it the Postgres leg errors out and
the suite passes on SQLite alone — the "green against nothing" outcome a
compare-and-swap proof must not be allowed to reach. CI runs Linux, where the
default policy is already selector-based.
"""

from __future__ import annotations

import asyncio
import sys

import pytest

from tests.spine_harness import (  # noqa: F401 - re-exported as fixtures
    _clean_redaction_registry,
    build_settings,
    session_factory,
)


@pytest.fixture(scope="session")
def event_loop_policy():
    """pytest-asyncio's policy hook — see the module docstring."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()
