"""Windows event-loop policy for the memory suite ONLY (load-bearing, not hygiene).

Identical in reason to ``tests/unit/approvals/conftest.py``: psycopg 3's async
mode refuses asyncio's default Windows ``ProactorEventLoop``, and
``postgresql+psycopg`` is ARCHITECTURE_V2 §5's normative driver. Without this
policy the Postgres leg of the parity suite errors out on a Windows build
machine and the suite passes on the fake alone — "green against nothing", which
is the exact outcome a parity proof must not be allowed to reach.

Scoped to this directory for the reason recorded at the approvals site: a
``SelectorEventLoop`` cannot ``subprocess_exec`` on Windows, and
``tests/unit/tools/`` spawns an MCP stdio child process.
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
