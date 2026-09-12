"""A `ToolManagerProtocol` double for the spine's integration tests.

**This is not the chokepoint.** The real Tool Manager is
`sunil/core/tool_framework/manager.py` — Stream A's file, and the single
execution chokepoint C1 §2.1 specifies. It does not exist yet, and the spine lane
must not write it: two implementations of the chokepoint is precisely the "second
path to a privileged call" the architecture forbids.

What this double is for: proving the *spine's* wiring — that a validated plan
step reaches a ToolManager through the seam, that a `PermissionResult` of
`ASK_USER` parks through the C4 approvals seam with a `ParkContext` the
orchestrator composed, and that the turn maps the result into the C5 envelope.
It implements only as much of C1 §2.1 as those assertions need, in the
contract's order:

    1 resolve tool/operation → 2 validate params (extra="forbid") →
    3 decide()/park/consume → 4 audit attempt → 5 execute → finalise

When Stream A lands, this file is deleted and the integration test constructs
`ToolManager(adapters, permission_hook, approvals, audit_hook)` instead — the
same constructor shape, which is why the swap is a one-line change.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from hashlib import sha256
from typing import Sequence

from pydantic import ValidationError

from sunil.core.approvals.base import ApprovalBinding, ApprovalsService, ParkRequest
from sunil.core.tool_framework.base import (
    ApprovalRef,
    AuditHook,
    ParkContext,
    PermissionDecision,
    PermissionHook,
    ToolAdapter,
    ToolCallAttempt,
    ToolErrorKind,
    ToolResult,
    ToolResultMeta,
    TraceContext,
)


def args_hash(params: dict) -> str:
    """sha256 of canonical JSON — the C4 binding's `args_hash`."""
    return sha256(json.dumps(params, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ToolManagerDouble:
    """C1 §2.1's call shape, enough of its pipeline for the spine's tests."""

    def __init__(
        self,
        adapters: Sequence[ToolAdapter],
        permission_hook: PermissionHook,
        approvals: ApprovalsService,
        audit_hook: AuditHook,
    ) -> None:
        self._adapters = {adapter.name: adapter for adapter in adapters}
        self._permission_hook = permission_hook
        self._approvals = approvals
        self._audit_hook = audit_hook

    async def execute(
        self,
        agent_id: str,
        tool: str,
        operation: str,
        params: dict,
        *,
        trace: TraceContext,
        approval: str | None = None,
        park_context: ParkContext | None = None,
    ) -> ToolResult:
        if approval is None and park_context is None:
            # C1: a caller contract violation, not a pipeline outcome — no
            # attempt row is written.
            raise TypeError("park_context is required on a first attempt")

        started = time.monotonic()
        # C1 §2.2: the trace ids travel on the TraceContext, and every audit
        # record this call writes carries them.
        self._request_id = trace.request_id
        self._task_id = trace.task_id
        adapter = self._adapters.get(tool)
        if adapter is None:
            return await self._exit(
                agent_id, tool, operation, ToolErrorKind.UNKNOWN_OPERATION,
                "unknown tool", None, None, started, adapter=None,
            )
        op = adapter.operations.get(operation)
        if op is None:
            return await self._exit(
                agent_id, tool, operation, ToolErrorKind.UNKNOWN_OPERATION,
                "unknown operation", None, None, started, adapter=adapter,
            )

        try:
            validated = op.params_model.model_validate(params)
        except ValidationError:
            return await self._exit(
                agent_id, tool, operation, ToolErrorKind.INVALID_PARAMS,
                "params failed validation", None, None, started, adapter=adapter,
            )

        canonical = validated.model_dump()
        decision = self._permission_hook(agent_id=agent_id, tool=tool, operation=operation)

        if decision.decision is PermissionDecision.DENY:
            return await self._exit(
                agent_id, tool, operation, ToolErrorKind.PERMISSION_DENIED,
                decision.reason, decision, canonical, started, adapter=adapter,
            )

        approval_id = approval
        if decision.decision is PermissionDecision.ASK_USER:
            if approval is None:
                parked = await self._approvals.park(
                    ParkRequest(
                        agent_id=agent_id,
                        tool=tool,
                        operation=operation,
                        args_hash=args_hash(canonical),
                        params_redacted=canonical,
                        request_id=trace.request_id,
                        conversation_id=trace.conversation_id,
                        task_id=trace.task_id,
                        summary=park_context.summary,
                        continuation=park_context.continuation,
                    )
                )
                result = await self._exit(
                    agent_id, tool, operation, ToolErrorKind.APPROVAL_REQUIRED,
                    f"parked as {parked.approval_id}", decision, canonical, started,
                    adapter=adapter, approval_id=parked.approval_id,
                )
                return replace(
                    result,
                    approval=ApprovalRef(
                        approval_id=parked.approval_id, expires_at=parked.expires_at
                    ),
                )
            consumed = await self._approvals.consume(
                approval,
                binding=ApprovalBinding(
                    agent_id=agent_id,
                    tool=tool,
                    operation=operation,
                    args_hash=args_hash(canonical),
                ),
            )
            if not consumed.ok:
                return await self._exit(
                    agent_id, tool, operation, ToolErrorKind.APPROVAL_INVALID,
                    consumed.reason or "approval did not bind", decision, canonical, started,
                    adapter=adapter, approval_id=approval,
                )

        audit_id = await self._audit_hook.attempt(
            self._attempt_record(
                agent_id, tool, operation, adapter, canonical, decision, approval_id
            )
        )
        try:
            result = await op.handler(validated)
        except Exception:
            # C1 §2: an adapter exception NEVER reaches the orchestrator as an
            # exception, and the raw text never reaches the caller.
            result = ToolResult(
                ok=False,
                data=None,
                error_kind=ToolErrorKind.UPSTREAM_ERROR.value,
                error_message="unhandled adapter exception",
                meta=ToolResultMeta(
                    adapter_kind=adapter.kind, server_id=None, duration_ms=self._ms(started)
                ),
            )
        await self._audit_hook.finalise(
            audit_id,
            outcome="ok" if result.ok else "error",
            error_kind=result.error_kind,
            duration_ms=result.meta.duration_ms,
        )
        return result

    # -- internals ---------------------------------------------------------- #
    def _attempt_record(
        self, agent_id, tool, operation, adapter, params, decision, approval_id
    ) -> ToolCallAttempt:
        from datetime import UTC, datetime

        return ToolCallAttempt(
            request_id=self._request_id,
            task_id=self._task_id,
            agent_id=agent_id,
            tool=tool,
            operation=operation,
            adapter_kind=adapter.kind if adapter is not None else None,
            server_id=None,
            args_hash=args_hash(params) if params is not None else None,
            params_redacted=params,
            permission_decision=decision.decision if decision is not None else None,
            permission_reason=decision.reason if decision is not None else None,
            approval_id=approval_id,
            created_at=datetime.now(UTC).isoformat(),
        )

    async def _exit(
        self, agent_id, tool, operation, error_kind, message, decision, params, started,
        *, adapter, approval_id: str | None = None,
    ) -> ToolResult:
        audit_id = await self._audit_hook.attempt(
            self._attempt_record(
                agent_id, tool, operation, adapter, params, decision, approval_id
            )
        )
        duration_ms = self._ms(started)
        await self._audit_hook.finalise(
            audit_id, outcome="error", error_kind=error_kind.value, duration_ms=duration_ms
        )
        return ToolResult(
            ok=False,
            data=None,
            error_kind=error_kind.value,
            error_message=message,
            meta=ToolResultMeta(
                adapter_kind=adapter.kind if adapter is not None else None,
                server_id=None,
                duration_ms=duration_ms,
            ),
        )

    @staticmethod
    def _ms(started: float) -> int:
        return int((time.monotonic() - started) * 1000)

    # Set per call by `execute()` from the TraceContext it is handed, so
    # `_attempt_record` stays readable.
    _request_id: str = ""
    _task_id: str = ""
