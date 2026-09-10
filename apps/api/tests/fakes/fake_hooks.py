"""``FakePermissionHook`` and ``RecordingAuditHook`` — C1 §6.1 / §6.2, verbatim.

Source of truth: ``docs/contracts/C1-tool-adapter.md`` §6 (v1.0.0, FROZEN
2026-09-10). These are two of the four seams the Tool Manager is constructed
with; the other two are ``FakeToolAdapter`` (§6.3) and C4 §6's
``FakeApprovalsService``.
"""

from __future__ import annotations

from typing import Literal

from sunil.core.tool_framework.base import (
    AuditHook,
    PermissionDecision,
    PermissionHook,
    PermissionResult,
    ToolCallAttempt,
)


class FakePermissionHook(PermissionHook):
    """C1 §6.1 — empty grant registry, default-deny structure.

    ``FakePermissionHook()`` starts with an empty
    ``dict[tuple[str, str, str], PermissionDecision]``.
    """

    def __init__(self) -> None:
        self.grants: dict[tuple[str, str, str], PermissionDecision] = {}

    def grant(
        self,
        agent_id: str,
        tool: str,
        operation: str,
        decision: Literal["allow", "deny", "ask_user"],
    ) -> None:
        """C1 §6.1's grant-registration API (the one C1 tests 3–5 use)."""
        self.grants[(agent_id, tool, operation)] = PermissionDecision(decision)

    def __call__(
        self, *, agent_id: str, tool: str, operation: str
    ) -> PermissionResult:
        """Deterministic: registered triple → the granted decision with
        ``reason="granted"``; absent triple → DENY (default-deny is the fake's
        structure too, mirroring the engine)."""
        granted = self.grants.get((agent_id, tool, operation))
        if granted is not None:
            return PermissionResult(
                decision=granted,
                reason="granted",
                source=f"fake:{agent_id}.{tool}.{operation}",
            )
        return PermissionResult(
            decision=PermissionDecision.DENY,
            reason="no grant for this triple (default deny)",
            source="fake:default",
        )


class RecordingAuditHook(AuditHook):
    """C1 §6.2 — records the two-phase audit and refuses a double finalise."""

    def __init__(self) -> None:
        self.attempts: list[ToolCallAttempt] = []
        self.finalised: dict[str, dict] = {}

    async def attempt(self, record: ToolCallAttempt) -> str:
        """Appends and returns ``f"audit-{len(self.attempts)}"`` (``audit-1``,
        ``audit-2``, …)."""
        self.attempts.append(record)
        return f"audit-{len(self.attempts)}"

    async def finalise(
        self,
        audit_id: str,
        *,
        outcome: Literal["ok", "error"],
        error_kind: str | None,
        duration_ms: int,
    ) -> None:
        """Stores the outcome under ``audit_id``; a second ``finalise`` for the
        same id raises ``AssertionError("double finalise")``."""
        if audit_id in self.finalised:
            raise AssertionError("double finalise")
        self.finalised[audit_id] = {
            "outcome": outcome,
            "error_kind": error_kind,
            "duration_ms": duration_ms,
        }
