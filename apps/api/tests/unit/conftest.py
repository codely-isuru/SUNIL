"""Fixtures for the unit suite only. (integration-w1 union of the spine and
Stream D conftests — both were additive; nothing here may change how the frozen
contract suites in ``tests/contracts/`` collect or run.)

Spine half: fixtures imported by name rather than via ``pytest_plugins`` —
see ``tests/spine_harness.py``.

**Stream D's Windows event-loop policy is NOT here, and must never be put here.**
It now lives in ``tests/unit/approvals/conftest.py``, the one package whose tests
reach Postgres. Unit-wide it is a collision, not a convenience: psycopg 3 needs
the ``SelectorEventLoop``, but a ``SelectorEventLoop`` cannot ``subprocess_exec``
on Windows (``NotImplementedError``, ``asyncio/base_events.py``), and
``tests/unit/tools/test_mcp_stdio.py`` spawns a real MCP child process over
stdio (C1 §5). Session-scoping the selector policy across ``tests/unit`` turns
all ten of those tests red — each lane was green alone, and the merge is where
the two requirements met. Scope the policy to the suite that needs it.
"""

from __future__ import annotations

from tests.spine_harness import (  # noqa: F401 - re-exported as fixtures
    _clean_redaction_registry,
    build_settings,
    session_factory,
)
