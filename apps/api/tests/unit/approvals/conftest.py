"""Windows event-loop policy for the approvals suite ONLY (load-bearing, not
hygiene).

psycopg 3's async mode refuses asyncio's default Windows ``ProactorEventLoop``,
and ``postgresql+psycopg`` is ARCHITECTURE_V2 §5's normative driver (ruling
S-1), so every async Postgres test on a Windows build machine needs the
``SelectorEventLoop`` policy below. Without it the Postgres leg errors out and
the suite passes on SQLite alone — the "green against nothing" outcome a
compare-and-swap proof must not be allowed to reach. CI runs Linux, where the
default policy is already selector-based, so this file is a no-op there.

**Why it lives here and not in ``tests/unit/conftest.py``.** The policy is
scoped to the directory whose tests reach Postgres (``factory.engine_urls()``
adds ``SUNIL_TEST_DATABASE_URL`` to every engine-parametrised test in this
package). Unit-wide it collides with ``tests/unit/tools/``: a
``SelectorEventLoop`` cannot ``subprocess_exec`` on Windows
(``NotImplementedError`` from ``asyncio/base_events.py``), and the MCP stdio
adapter spawns a child process. See the note at the old site.
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
