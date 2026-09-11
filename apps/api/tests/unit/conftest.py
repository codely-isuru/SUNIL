"""Unit-test fixtures for Stream D's lanes (``tests/unit/**``).

**Windows event-loop policy (load-bearing, not hygiene).** psycopg 3's async
mode refuses to run on asyncio's default Windows loop:

    psycopg.InterfaceError: Psycopg cannot use the 'ProactorEventLoop' to run
    in async mode.

``ProactorEventLoop`` is the default event loop on Windows from Python 3.8, and
``postgresql+psycopg`` is ARCHITECTURE_V2 §5's normative driver token (ruling
S-1), so every async Postgres test on a Windows build machine hits this. The
override below hands pytest-asyncio a ``SelectorEventLoop`` policy on win32 and
changes nothing anywhere else — CI runs Linux, where the default policy is
already selector-based.

Without it the Postgres leg of the parity suite errors out and the suite passes
on SQLite alone, which is precisely the "green against nothing" outcome a
compare-and-swap proof must not be allowed to reach.
"""

from __future__ import annotations

import asyncio
import sys

import pytest


@pytest.fixture(scope="session")
def event_loop_policy():
    """pytest-asyncio's policy hook — see the module docstring."""
    if sys.platform == "win32":
        return asyncio.WindowsSelectorEventLoopPolicy()
    return asyncio.get_event_loop_policy()
