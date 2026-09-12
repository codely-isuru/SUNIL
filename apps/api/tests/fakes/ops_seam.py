"""The C6 §5 in-process seam, transcribed for the fake's conformance witness.

``docs/contracts/C6-ops-reads.md`` §5 declares ``OpsReadStore`` as the Protocol
the three ops routes call. The production module that will hold it
(``sunil/core/ops/base.py``, ARCHITECTURE_V2 §2 Amendment 1) is Phase 2 work and
does not exist yet, and QA does not write production code — so the Protocol is
transcribed here, in the test package, purely as the yardstick for
``fake_ops_store``'s ``_check`` witness (F2: no fake inherits its Protocol).

**When Stream D lands the real seam**, delete this module's class body and make
it a re-export::

    from sunil.core.ops.base import OpsReadStore  # noqa: F401

Nothing else has to change: ``fake_ops_store`` and ``test_fake_conformance``
both import the name from here, so the substitution is one line and the
conformance test immediately starts checking the fake against the REAL seam. If
the real signatures differ from this transcription, that test fails — which is
the point.

The signatures below are C6 §5 verbatim, including keyword-only markers and the
``from_at``/``to_at`` naming (``from`` is a Python reserved word; the route layer
maps the wire names).
"""

from __future__ import annotations

from typing import Any, Protocol

#: The four response shapes C6 §5 names. They are the OpenAPI response objects
#: (``{tasks, next_cursor}``, ``{running, parked, recent}``, ``{turns,
#: next_cursor}``, ``{events, approval_events}``) and are plain dicts here: C6
#: froze a JSON surface, not a Python model, and inventing Pydantic models for
#: it would be QA guessing at an implementer's choice.
TaskPage = dict[str, Any]
TaskDetail = dict[str, Any]
ActivitySnapshot = dict[str, Any]
AuditTurnPage = dict[str, Any]
AuditTurnDetail = dict[str, Any]


class OpsReadStore(Protocol):
    """C6 §5. Read-only; five operations; no mutating verb exists."""

    async def list_tasks(
        self,
        *,
        status: str | None = None,
        project_key: str | None = None,
        q: str | None = None,
        order: str = "newest",
        limit: int = 50,
        cursor: str | None = None,
    ) -> TaskPage: ...

    async def get_task(self, task_id: str) -> TaskDetail | None: ...

    async def activity(self) -> ActivitySnapshot: ...

    async def list_audit_turns(
        self,
        *,
        request_id: str | None = None,
        from_at: str | None = None,
        to_at: str | None = None,
        outcome: str | None = None,
        agent: str | None = None,
        limit: int = 50,
        cursor: str | None = None,
    ) -> AuditTurnPage: ...

    async def get_audit_turn(self, request_id: str) -> AuditTurnDetail | None: ...
