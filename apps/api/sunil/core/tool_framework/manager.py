"""`ToolManager.execute()` — the privileged gate every tool call passes
through (`ARCHITECTURE_V1.md` §9.3, ADR-004 Amendment 1 — guard site 3).

The order below is the order in the architecture, and each step is a
requirement, not a convenience:

0. **Runtime guard.** Reject the call unless `plan` is a genuine
   `ValidatedPlan` (`guards.require_validated_plan()`) and `meta` is a
   genuine `ExecutionMetadata` with all four fields present. **No
   `tool_calls` row is written for a step-0 failure** — a caller with no
   validated plan cannot reach step 1, so there is nothing yet to record.
1. **Resolve** tool + operation. Unknown → `tool_calls` row,
   `permission_decision=deny`, `status=not_executed`. No adapter exists
   to call.
2. **Agent grant precheck** — the agent's own `config/agents.yaml` tool
   list (FR-082). Deliberately duplicates the agent runner's own check
   (defence in depth against a future agent that forgets).
3. **Validate parameters** against `params_model` (`extra="forbid"`). On
   failure: `error_kind=invalid_params`, adapter never invoked.
4. **Permission decision** (T7's `decide()`) → stage 9, recorded on the
   row.
5. Not `ALLOW` → return without touching the adapter.
6. **Execute** the adapter inside `asyncio.timeout(op.timeout_s)`.
7. **Normalise** to `ToolResult` — an adapter exception never propagates.
8. **Record** the result, `duration_ms`; stage 10.

Every terminal branch writes **exactly one** `tool_calls` row before
returning, so ET-4 ("exactly one ToolCall, decision ALLOW") and ET-7
("zero ToolCalls" for a plan that never reaches execution) are both
facts read back from the database, not inferred from the absence of an
error.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sunil.capture import CaptureKind, ContentSource
from sunil.core.orchestrator.guards import (
    ExecutionMetadata,
    InvalidPlanExecution,
    require_validated_plan,
)
from sunil.core.permissions.engine import Decision, decide
from sunil.core.registry.errors import UnknownAgentError
from sunil.core.registry.loader import Registries
from sunil.core.tool_framework.base import ToolAdapter, ToolResult
from sunil.core.trace.context import NullTraceContext, TraceContext
from sunil.core.trace.stages import TraceStage
from sunil.db.capture import resolve_capture
from sunil.db.models import ToolCall
from sunil.redaction import scrub

__all__ = ["ExecutionMetadata", "InvalidPlanExecution", "ToolManager"]

# tool_calls.status values (mirrors sunil.db.models.ToolCallStatus by
# value — not imported directly so this module's DB-write helper stays a
# thin, obvious mapping rather than a second source of truth for the enum
# itself; sunil.db.models.ToolCallStatus is still what the column's
# CheckConstraint is built from).
_STATUS_OK = "ok"
_STATUS_ERROR = "error"
_STATUS_NOT_EXECUTED = "not_executed"


class ToolManager:
    """Constructed once per process (or per turn) with the adapters and
    registries it needs. `adapters`/`registries`/`sessionmaker` all
    default to empty/`None` so a bare `ToolManager()` is always
    constructible — the step-0 guard runs before any of them is touched,
    so a caller proving only the guard (no real execution) never needs to
    wire a database or a registry just to get past `__init__`.
    """

    def __init__(
        self,
        *,
        adapters: dict[str, ToolAdapter] | None = None,
        registries: Registries | None = None,
        sessionmaker: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        self._adapters = adapters or {}
        self._registries = registries
        self._sessionmaker = sessionmaker

    async def execute(
        self,
        *,
        plan: object,
        tool: str,
        operation: str,
        params: dict[str, Any],
        meta: object,
        trace: TraceContext | None = None,
    ) -> ToolResult:
        # --- step 0: the runtime guard (ADR-004 Amendment 1, guard site 3) ---
        require_validated_plan(plan)
        if not isinstance(meta, ExecutionMetadata):
            raise InvalidPlanExecution(
                f"ToolManager.execute() requires ExecutionMetadata, received {type(meta).__name__}"
            )
        if not (meta.validated_plan_id and meta.request_id and meta.task_id and meta.agent_id):
            raise InvalidPlanExecution(
                "ExecutionMetadata is missing one or more required fields "
                "(validated_plan_id, request_id, task_id, agent_id must all be present)"
            )

        if self._registries is None or self._sessionmaker is None:
            raise RuntimeError(
                "ToolManager must be constructed with `registries` and `sessionmaker` to "
                "actually execute a tool call — a bare ToolManager() only proves the step-0 guard."
            )

        active_trace = trace if trace is not None else NullTraceContext(request_id=meta.request_id)
        start = time.monotonic()
        project_key = params.get("project_key") if isinstance(params, dict) else None

        # --- step 1: resolve tool + operation ---
        adapter = self._adapters.get(tool)
        operation_def = adapter.operations.get(operation) if adapter is not None else None
        if operation_def is None:
            return await self._deny_and_record(
                meta=meta,
                tool=tool,
                operation=operation,
                params=params,
                project_key=project_key,
                reason=f"no such tool/operation: {tool}.{operation}",
                error_kind="unknown_operation",
                start=start,
            )

        # --- step 2: agent grant precheck (config/agents.yaml, FR-082) ---
        try:
            agent = self._registries.agents.get(meta.agent_id)
        except UnknownAgentError:
            return await self._deny_and_record(
                meta=meta,
                tool=tool,
                operation=operation,
                params=params,
                project_key=project_key,
                reason=f"unknown agent {meta.agent_id!r}",
                error_kind="unknown_agent",
                start=start,
            )
        if operation not in agent.tools.get(tool, []):
            return await self._deny_and_record(
                meta=meta,
                tool=tool,
                operation=operation,
                params=params,
                project_key=project_key,
                reason=f"agent {meta.agent_id!r} is not granted {tool}.{operation} in agents.yaml",
                error_kind="not_granted_to_agent",
                start=start,
            )

        # --- step 3: validate parameters (extra="forbid") ---
        try:
            validated_params = operation_def.params_model.model_validate(params)
        except ValidationError as exc:
            return await self._deny_and_record(
                meta=meta,
                tool=tool,
                operation=operation,
                params=params,
                project_key=project_key,
                reason=f"invalid parameters: {exc}",
                error_kind="invalid_params",
                start=start,
            )

        # --- step 4: the permission decision (T7) ---
        decision_result = decide(
            self._registries.permissions, agent_id=meta.agent_id, tool=tool, operation=operation
        )
        await active_trace.emit(
            TraceStage.PERMISSION_DECISION,
            summary=f"{decision_result.decision.value} {tool}.{operation}",
            detail={"reason": decision_result.reason, "source": decision_result.source},
            task_id=meta.task_id,
        )

        # --- step 5: anything but ALLOW stops here, before the adapter ---
        if decision_result.decision is not Decision.ALLOW:
            return await self._persist_and_return(
                meta=meta,
                tool=tool,
                operation=operation,
                params=validated_params.model_dump(),
                project_key=project_key,
                permission_decision=decision_result.decision.value,
                permission_reason=decision_result.reason,
                status=_STATUS_NOT_EXECUTED,
                result=None,
                error_kind=None,
                error_message=None,
                duration_ms=int((time.monotonic() - start) * 1000),
                trace=active_trace,
            )

        # --- step 6: execute the adapter, bounded by its own timeout ---
        try:
            async with asyncio.timeout(operation_def.timeout_s):
                tool_result = await operation_def.handler(validated_params)
        except TimeoutError:
            tool_result = ToolResult(
                ok=False,
                data=None,
                error_kind="timeout",
                error_message=f"{tool}.{operation} exceeded its {operation_def.timeout_s}s timeout",
            )
        except Exception as exc:  # noqa: BLE001 - step 7: an adapter exception never propagates
            tool_result = ToolResult(
                ok=False, data=None, error_kind="tool_error", error_message=str(exc)
            )

        # --- step 8: record + stage 10 ---
        return await self._persist_and_return(
            meta=meta,
            tool=tool,
            operation=operation,
            params=validated_params.model_dump(),
            project_key=project_key,
            permission_decision=decision_result.decision.value,
            permission_reason=decision_result.reason,
            status=_STATUS_OK if tool_result.ok else _STATUS_ERROR,
            result=tool_result.data,
            error_kind=tool_result.error_kind,
            error_message=tool_result.error_message,
            duration_ms=int((time.monotonic() - start) * 1000),
            trace=active_trace,
            tool_result=tool_result,
        )

    async def _deny_and_record(
        self,
        *,
        meta: ExecutionMetadata,
        tool: str,
        operation: str,
        params: dict[str, Any],
        project_key: str | None,
        reason: str,
        error_kind: str,
        start: float,
    ) -> ToolResult:
        """Steps 1–3's shared shape: `permission_decision=deny`,
        `status=not_executed`, adapter never reached. These steps do not
        go through T7's `decide()` (there is no tool/operation/agent
        triple to evaluate yet), so `permission_decision` is set to
        `deny` directly here — the architecture's own wording for all
        three ("record tool_calls with permission_decision=deny,
        status=not_executed")."""
        return await self._persist_and_return(
            meta=meta,
            tool=tool,
            operation=operation,
            params=params if isinstance(params, dict) else {},
            project_key=project_key,
            permission_decision=Decision.DENY.value,
            permission_reason=reason,
            status=_STATUS_NOT_EXECUTED,
            result=None,
            error_kind=error_kind,
            error_message=reason,
            duration_ms=int((time.monotonic() - start) * 1000),
            trace=None,
        )

    async def _persist_and_return(
        self,
        *,
        meta: ExecutionMetadata,
        tool: str,
        operation: str,
        params: dict[str, Any],
        project_key: str | None,
        permission_decision: str,
        permission_reason: str,
        status: str,
        result: dict[str, Any] | None,
        error_kind: str | None,
        error_message: str | None,
        duration_ms: int,
        trace: TraceContext | None,
        tool_result: ToolResult | None = None,
    ) -> ToolResult:
        """The one place a `tool_calls` row is written (§9.3's "the row is
        written before the adapter is reached" for steps 1–3, and "record
        result" for step 8 — same helper either way, so there is exactly
        one INSERT statement in this module to audit).

        Capture policy (ADR-014) is resolved fresh for the `result`
        column — `tool_calls` is one of the five `CaptureColumns` tables
        and has no Python-side column default, so an omitted resolution
        would fail loudly as an `IntegrityError` rather than silently
        default to something nobody decided. Redaction (`scrub()`, ADR-006)
        runs on both `parameters` and `result` before insert — this
        module's own responsibility per `sunil/redaction.py`'s docstring
        ("T6 and T8 must call scrub() themselves").
        """
        decision = resolve_capture(
            kind=CaptureKind.TOOL_CALL,
            project_key=project_key,
            agent_id=meta.agent_id,
            source=ContentSource.EXTERNAL_TOOL_RESULT,
        )
        # `apply_capture_to_content()` is typed for a single `str` column;
        # `tool_calls.result` is a JSON object, so the NONE/METADATA_ONLY
        # nulling is applied to the whole dict here rather than misusing
        # that helper on a value it was not shaped for.
        stored_result = (
            None
            if decision.capture_policy.value in ("none", "metadata_only")
            else (scrub(result) if result is not None else None)
        )

        row = ToolCall(
            request_id=meta.request_id,
            task_id=meta.task_id,
            validated_plan_id=meta.validated_plan_id,
            agent_id=meta.agent_id,
            tool=tool,
            operation=operation,
            parameters=scrub(params),
            permission_decision=permission_decision,
            permission_reason=permission_reason,
            status=status,
            result=stored_result,
            error_kind=error_kind,
            duration_ms=duration_ms,
            capture_policy=decision.capture_policy.value,
            sensitivity=decision.sensitivity.value,
            retention_class=decision.retention_class.value,
            training_eligible=decision.training_eligible,
        )

        assert self._sessionmaker is not None  # guaranteed by the __init__ check above
        async with self._sessionmaker() as session:
            session.add(row)
            await session.commit()

        if trace is not None:
            await trace.emit(
                TraceStage.TOOL_RESULT,
                summary=f"{status} {tool}.{operation}",
                detail={"error_kind": error_kind, "duration_ms": duration_ms},
                task_id=meta.task_id,
            )

        if tool_result is not None:
            return tool_result
        return ToolResult(ok=False, data=None, error_kind=error_kind, error_message=error_message)
