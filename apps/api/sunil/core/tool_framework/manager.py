"""``ToolManager`` — C1 §2.1's pipeline: the single execution chokepoint.

Source of truth: ``docs/contracts/C1-tool-adapter.md`` **v1.1.1** §2.1 (the
seven steps, in order, for every call regardless of adapter kind), §2.2 (the
injected seams), §3 (the untrusted-results posture) and §4 (the closed error
set). Placement is the contract's own (§2.1 "Module placement"): ``base.py``
holds interface types, this module holds the pipeline.

Three properties are load-bearing and each is defended by a named test:

* **One composer, one hasher** (§2.1 step 3, backend review F3). The manager
  computes ``args_hash``, ``params_redacted``, the identity triple and the trace
  ids for the ``ParkRequest``, and copies ONLY ``continuation``/``summary``
  verbatim from the caller's ``ParkContext``. The same
  :func:`sunil.core.tool_framework.canonical.args_hash` then recomputes the
  binding from freshly re-validated params on the continuation call, so what the
  approval was minted against is what it is checked against.
* **Single consume owner** (§2.1 step 3, QA B3 / ADR-031 Amendment 1). The
  continuation executor never issues the consume CAS — it re-enters ``execute``
  with the approval id. An ``ALLOW`` grant therefore **ignores** a supplied
  approval id rather than consuming it: burning a single-use approval the owner
  granted for a different call is invisible on the happy path and expensive on
  the real resume.
* **Two-phase audit** (§2.1 step 4, Security review 2026-09-10 item 3). Exactly
  one ``attempt`` row and exactly one ``finalise`` per ``execute`` call, on every
  path, and on the execute path the attempt is written BEFORE the handler runs —
  so a process kill mid-execution can never leave a side effect with no
  ``tool_calls`` row.

An adapter exception never reaches the orchestrator as an exception (§2): every
outcome collapses to a ``ToolResult`` whose ``error_kind`` is in §4's closed
set. The one deliberate exception is the ``park_context`` precondition, which is
a CALLER contract violation (``TypeError`` before step 1, no attempt row) of the
same class as constructing this manager without an audit hook.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from pydantic import ValidationError

from sunil.core.approvals.base import (
    ApprovalBinding,
    ApprovalsService,
    ParkRequest,
)
from sunil.core.tool_framework.base import (
    AdapterKind,
    ApprovalRef,
    AuditHook,
    ParkContext,
    PermissionDecision,
    PermissionHook,
    ToolAdapter,
    ToolCallAttempt,
    ToolErrorKind,
    ToolOperation,
    ToolResult,
    ToolResultMeta,
    TraceContext,
)
from sunil.core.tool_framework.canonical import args_hash
from sunil.core.tool_framework.redaction import redact_params
from sunil.core.tool_framework.untrusted import sanitise_untrusted_data

_LOGGER = logging.getLogger(__name__)

#: C1 §3 applies the cap and the key strip to MCP results specifically ("MCP
#: results additionally pass a size cap ... and a key strip at the adapter
#: boundary"). Applied here, at the chokepoint, keyed on the RESOLVED adapter
#: kind rather than inside each adapter: two adapters cannot then disagree about
#: what "untrusted" means, and a third adapter kind added later is covered by
#: adding it to this set, in one place, under review.
_UNTRUSTED_KINDS = frozenset({AdapterKind.MCP_STDIO, AdapterKind.MCP_HTTP})


def _now_iso() -> str:
    """ISO-8601 UTC with a ``Z`` suffix (C1 §2.2 ``created_at``)."""
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class ToolManager:
    """C1 §2.1. Constructed with exactly the four seams, none defaulted.

    No default audit hook: "forgot to audit" must not be an expressible program
    (§2.2), which a default argument would make it.
    """

    def __init__(
        self,
        adapters: list[ToolAdapter],
        permission_hook: PermissionHook,
        approvals: ApprovalsService,
        audit_hook: AuditHook,
        transaction: Any | None = None,
    ) -> None:
        self._adapters: dict[str, ToolAdapter] = {adapter.name: adapter for adapter in adapters}
        self._permission_hook = permission_hook
        self._approvals = approvals
        self._audit = audit_hook
        #: C1 §2.1 step 4's transactional rule, when the wired seams can honour
        #: it (`core/tool_framework/transaction.py`). `None` means they cannot —
        #: an in-memory C4 fake has no transaction to share — and the two
        #: approval paths then fall back to separate writes, which is the ONLY
        #: posture the fakes can express and the reason C1 §6 says they "assert
        #: ordering, not atomicity". Production wiring always passes one;
        #: `api/wiring.py` decides that once, at boot, so this pipeline never
        #: sniffs a seam for capabilities on the request path.
        self._transaction = transaction

    # -- the pipeline ------------------------------------------------------- #
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
        started = time.monotonic()

        # --- precondition (§2.1, F3): a FIRST attempt must carry park material.
        # Raised BEFORE step 1, so no attempt row is written and the approvals
        # service is never touched: this is a caller contract violation, not a
        # pipeline outcome, and a call that could park non-resumably must not be
        # expressible. `park_context` is IGNORED on continuation calls — a call
        # carrying an approval never parks.
        if approval is None and park_context is None:
            raise TypeError(
                "ToolManager.execute() requires park_context on a first attempt "
                "(approval is None): a call that could park must be resumable "
                "(C1 §2.1, ADR-031)"
            )

        # --- step 1: resolve tool + operation --------------------------------
        adapter = self._adapters.get(tool)
        if adapter is None:
            # No adapter was EVER resolved, so adapter_kind/server_id stay None
            # on both the result meta and the audit row (§2 F4): a kind here
            # would be a fabricated fact on the tool_calls trail.
            return await self._early_exit(
                agent_id=agent_id,
                tool=tool,
                operation=operation,
                trace=trace,
                adapter_kind=None,
                server_id=None,
                error_kind=ToolErrorKind.UNKNOWN_OPERATION,
                error_message=f"no such tool: {tool}",
                started=started,
                approval_id=approval,
            )

        adapter_kind = adapter.kind
        server_id = _server_id_of(adapter)
        operation_def: ToolOperation | None = adapter.operations.get(operation)
        if operation_def is None:
            # An unknown OPERATION on a KNOWN tool records the resolved
            # adapter's real kind (§2 F4).
            return await self._early_exit(
                agent_id=agent_id,
                tool=tool,
                operation=operation,
                trace=trace,
                adapter_kind=adapter_kind,
                server_id=server_id,
                error_kind=ToolErrorKind.UNKNOWN_OPERATION,
                error_message=f"no such operation: {tool}.{operation}",
                started=started,
                approval_id=approval,
            )

        # --- step 2: validate params (extra="forbid") ------------------------
        # BEFORE the permission check, so the audit row records what was
        # actually attempted, in canonical form. Plan-step params are immutable
        # literals (C2 §2), which is what keeps args_hash meaningful.
        try:
            validated = operation_def.params_model.model_validate(params)
        except ValidationError as exc:
            return await self._early_exit(
                agent_id=agent_id,
                tool=tool,
                operation=operation,
                trace=trace,
                adapter_kind=adapter_kind,
                server_id=server_id,
                error_kind=ToolErrorKind.INVALID_PARAMS,
                error_message=f"parameters rejected: {exc.error_count()} validation error(s)",
                started=started,
                approval_id=approval,
            )

        canonical_params = validated.model_dump()
        hashed = args_hash(validated)
        redacted = redact_params(canonical_params)

        # --- step 3: the permission decision ---------------------------------
        decision = self._permission_hook(agent_id=agent_id, tool=tool, operation=operation)

        if decision.decision is PermissionDecision.DENY:
            return await self._early_exit(
                agent_id=agent_id,
                tool=tool,
                operation=operation,
                trace=trace,
                adapter_kind=adapter_kind,
                server_id=server_id,
                error_kind=ToolErrorKind.PERMISSION_DENIED,
                error_message=f"{tool}.{operation} is not permitted for {agent_id}",
                started=started,
                args_hash_=hashed,
                params_redacted=redacted,
                permission_decision=decision.decision,
                permission_reason=decision.reason,
                approval_id=approval,
            )

        approval_id_for_row = approval
        #: Set by the transactional continuation path below, where the attempt
        #: row is written INSIDE the consume transaction; `None` everywhere else,
        #: which is what makes step 4 the single writer on every other path.
        audit_id: str | None = None
        if decision.decision is PermissionDecision.ASK_USER:
            if approval is None:
                # Park. The manager composes the ParkRequest: continuation and
                # summary VERBATIM from the caller's ParkContext, everything
                # else computed here and nowhere else.
                assert park_context is not None  # guaranteed by the precondition
                request = ParkRequest(
                    agent_id=agent_id,
                    tool=tool,
                    operation=operation,
                    args_hash=hashed,
                    params_redacted=redacted,
                    request_id=trace.request_id,
                    conversation_id=trace.conversation_id,
                    task_id=trace.task_id,
                    summary=park_context.summary,
                    continuation=park_context.continuation,
                )
                if self._transaction is not None:
                    # C1 §2.1 step 4's park clause (condition C-1): the approval
                    # INSERT — continuation and all — and the attempt row commit
                    # together. A parked approval whose attempt row was lost is
                    # one the owner can approve for a call `tool_calls` has no
                    # record of anybody making.
                    return await self._parked_in_one_transaction(
                        request,
                        agent_id=agent_id,
                        tool=tool,
                        operation=operation,
                        trace=trace,
                        adapter_kind=adapter_kind,
                        server_id=server_id,
                        started=started,
                        hashed=hashed,
                        redacted=redacted,
                        decision=decision,
                    )
                parked = await self._approvals.park(request)
                # The park INSERT commits before the turn returns `parked`
                # (C4 §1 restart safety), so it precedes this exit's audit row;
                # the row carries the minted id so the trail joins to the
                # approval that a later continuation will present.
                return await self._early_exit(
                    agent_id=agent_id,
                    tool=tool,
                    operation=operation,
                    trace=trace,
                    adapter_kind=adapter_kind,
                    server_id=server_id,
                    error_kind=ToolErrorKind.APPROVAL_REQUIRED,
                    error_message=f"{tool}.{operation} requires the owner's approval",
                    started=started,
                    args_hash_=hashed,
                    params_redacted=redacted,
                    permission_decision=decision.decision,
                    permission_reason=decision.reason,
                    approval_id=parked.approval_id,
                    # C1 v1.2.0 (ruling R8): the typed reference the orchestrator
                    # surfaces into C5's `outcome=parked`, copied verbatim from
                    # the ParkedApproval this exit is holding. It does NOT ride
                    # in `data` — §2 freezes that to None on every error result,
                    # and §3 labels it adapter-attributed untrusted output.
                    approval_ref=ApprovalRef(
                        approval_id=parked.approval_id, expires_at=parked.expires_at
                    ),
                )

            # Continuation: recompute the binding from THIS call's freshly
            # validated params and consume. The manager is the single consume
            # owner (QA B3) — a caller cannot vouch for a binding it did not
            # compute, so the supplied value is an opaque id and nothing more.
            binding = ApprovalBinding(
                agent_id=agent_id,
                tool=tool,
                operation=operation,
                args_hash=hashed,
            )
            if self._transaction is not None:
                # C1 §2.1 step 4, the continuation clause (condition C-1): the
                # attempt row is written by the CAS's own transaction. `audit_id`
                # comes back set exactly when the consume won, and step 4 below
                # then skips its duplicate write — one attempt row per execute
                # call, on this path as on every other.
                #
                # A failure inside that transaction is NOT converted into a
                # ToolResult: it rolls the consume back, so the approval is
                # unspent, and the pipeline cannot honestly record an outcome
                # through the audit sink that just failed.
                consumed, audit_id = await self._transaction.consume_with_attempt(
                    approval,
                    binding=binding,
                    record=self._attempt_record(
                        agent_id=agent_id,
                        tool=tool,
                        operation=operation,
                        trace=trace,
                        adapter_kind=adapter_kind,
                        server_id=server_id,
                        args_hash_=hashed,
                        params_redacted=redacted,
                        permission_decision=decision.decision,
                        permission_reason=decision.reason,
                        approval_id=approval_id_for_row,
                    ),
                )
            else:
                consumed, audit_id = (
                    await self._approvals.consume(approval, binding=binding),
                    None,
                )
            if not consumed.ok:
                # A binding mismatch does NOT burn the approval (C4 §6 rule 3)
                # and a consume failure never re-parks (§2.1).
                return await self._early_exit(
                    agent_id=agent_id,
                    tool=tool,
                    operation=operation,
                    trace=trace,
                    adapter_kind=adapter_kind,
                    server_id=server_id,
                    error_kind=ToolErrorKind.APPROVAL_INVALID,
                    error_message=f"approval did not bind ({consumed.reason})",
                    started=started,
                    args_hash_=hashed,
                    params_redacted=redacted,
                    permission_decision=decision.decision,
                    permission_reason=decision.reason,
                    approval_id=approval,
                )
        elif approval is not None:
            # ALLOW + an approval id: ignored, NOT consumed (§2.1 step 3).
            # Policy alone authorises; the orphaned `approved` row is expired by
            # C4 §1's stale-approved sweep. Recorded on the row so the trail
            # shows the id was presented and deliberately not spent.
            _LOGGER.info(
                "approval id ignored under an ALLOW grant (not consumed): "
                "tool=%s operation=%s agent=%s",
                tool,
                operation,
                agent_id,
            )

        # --- step 4: audit attempt BEFORE the handler runs -------------------
        # Skipped only when the consume transaction already wrote this call's
        # row (C1 §2.1 step 4's own rule — the transactional write REPLACES this
        # one rather than adding to it; two rows would double-count the call on
        # the `tool_calls` trail).
        if audit_id is None:
            audit_id = await self._audit.attempt(
                self._attempt_record(
                    agent_id=agent_id,
                    tool=tool,
                    operation=operation,
                    trace=trace,
                    adapter_kind=adapter_kind,
                    server_id=server_id,
                    args_hash_=hashed,
                    params_redacted=redacted,
                    permission_decision=decision.decision,
                    permission_reason=decision.reason,
                    approval_id=approval_id_for_row,
                )
            )

        # --- step 5: execute under the operation's own timeout ---------------
        try:
            async with asyncio.timeout(operation_def.timeout_s):
                result = await operation_def.handler(validated)
        except TimeoutError:
            result = self._error(
                ToolErrorKind.TIMEOUT,
                f"{tool}.{operation} exceeded its {operation_def.timeout_s}s timeout",
                adapter_kind,
                server_id,
                started,
            )
        except Exception:  # noqa: BLE001 - §2: an adapter exception never escapes
            # Never the raw exception text: it can carry upstream payload or
            # credential material, and the orchestrator branches on error_kind
            # only (§4).
            _LOGGER.exception(
                "unhandled adapter exception in %s.%s", tool, operation, stack_info=False
            )
            result = self._error(
                ToolErrorKind.UPSTREAM_ERROR,
                "unhandled adapter exception",
                adapter_kind,
                server_id,
                started,
            )

        # --- step 7 (before 6's finalise can report it): wrap as untrusted ---
        result = self._normalise(result, adapter_kind, server_id, started, tool, operation)

        # --- step 6: audit finalise ------------------------------------------
        await self._audit.finalise(
            audit_id,
            outcome="ok" if result.ok else "error",
            error_kind=result.error_kind,
            duration_ms=result.meta.duration_ms,
        )
        return result

    # -- helpers ------------------------------------------------------------- #
    @staticmethod
    def _attempt_record(
        *,
        agent_id: str,
        tool: str,
        operation: str,
        trace: TraceContext,
        adapter_kind: AdapterKind | None,
        server_id: str | None,
        args_hash_: str | None = None,
        params_redacted: dict | None = None,
        permission_decision: PermissionDecision | None = None,
        permission_reason: str | None = None,
        approval_id: str | None = None,
    ) -> ToolCallAttempt:
        """C1 §2.2's ``ToolCallAttempt``, composed in ONE place.

        Three writers now exist — step 4, ``_early_exit`` and the two
        transactional paths — and a row composed differently on any of them would
        make the ``tool_calls`` trail describe the same call in two shapes
        depending on which door it came through.
        """
        return ToolCallAttempt(
            request_id=trace.request_id,
            task_id=trace.task_id,
            agent_id=agent_id,
            tool=tool,
            operation=operation,
            adapter_kind=adapter_kind,
            server_id=server_id,
            args_hash=args_hash_,
            params_redacted=params_redacted,
            permission_decision=permission_decision,
            permission_reason=permission_reason,
            approval_id=approval_id,
            created_at=_now_iso(),
        )

    async def _parked_in_one_transaction(
        self,
        request: ParkRequest,
        *,
        agent_id: str,
        tool: str,
        operation: str,
        trace: TraceContext,
        adapter_kind: AdapterKind | None,
        server_id: str | None,
        started: float,
        hashed: str,
        redacted: dict,
        decision: Any,
    ) -> ToolResult:
        """The park exit, with the approval row and the attempt row in one
        transaction (C1 §2.1 step 4's park clause).

        The record is passed as a FUNCTION of the approval id, because the row
        must name an id that does not exist until the INSERT has run — and an
        attempt row that did not name it would not join to the approval a later
        continuation presents, which is the only reason the row is on this path
        at all.

        ``finalise`` runs after the commit: the row exists by then, and an UPDATE
        sharing the park's transaction would hold its locks across an error path.
        """
        parked, audit_id = await self._transaction.park_with_attempt(
            request,
            lambda approval_id: self._attempt_record(
                agent_id=agent_id,
                tool=tool,
                operation=operation,
                trace=trace,
                adapter_kind=adapter_kind,
                server_id=server_id,
                args_hash_=hashed,
                params_redacted=redacted,
                permission_decision=decision.decision,
                permission_reason=decision.reason,
                approval_id=approval_id,
            ),
        )
        result = self._error(
            ToolErrorKind.APPROVAL_REQUIRED,
            f"{tool}.{operation} requires the owner's approval",
            adapter_kind,
            server_id,
            started,
            # The returned ParkedApproval was previously discarded (`_parked`),
            # which is how this exit — the one the real wiring takes — surfaced
            # no reference at all. C1 v1.2.0 (ruling R8): both park exits mint
            # the same typed field, verbatim from C4's own value.
            approval_ref=ApprovalRef(
                approval_id=parked.approval_id, expires_at=parked.expires_at
            ),
        )
        await self._audit.finalise(
            audit_id,
            outcome="error",
            error_kind=result.error_kind,
            duration_ms=result.meta.duration_ms,
        )
        return result

    async def _early_exit(
        self,
        *,
        agent_id: str,
        tool: str,
        operation: str,
        trace: TraceContext,
        adapter_kind: AdapterKind | None,
        server_id: str | None,
        error_kind: ToolErrorKind,
        error_message: str,
        started: float,
        args_hash_: str | None = None,
        params_redacted: dict | None = None,
        permission_decision: PermissionDecision | None = None,
        permission_reason: str | None = None,
        approval_id: str | None = None,
        approval_ref: ApprovalRef | None = None,
    ) -> ToolResult:
        """Steps 1–3's shared shape: write the attempt row AT the exit point and
        finalise it immediately with the error outcome (§2.1 step 4) — one
        attempt, one finalise, on every path.

        ``args_hash``/``params_redacted`` stay None when validation failed or
        never ran, and ``permission_decision``/``permission_reason`` stay None
        when the pipeline exited before step 3 (§2.2's own rules): an audit row
        must not imply a decision that was never taken.

        ``approval_id`` and ``approval_ref`` are two different jobs on two
        different records and are deliberately not one argument: the former is
        the AUDIT row's join key (also set on the ``approval_invalid`` exit,
        which surfaces no reference), the latter is the C1 v1.2.0 typed field the
        park exit alone mints onto the RESULT.
        """
        audit_id = await self._audit.attempt(
            self._attempt_record(
                agent_id=agent_id,
                tool=tool,
                operation=operation,
                trace=trace,
                adapter_kind=adapter_kind,
                server_id=server_id,
                args_hash_=args_hash_,
                params_redacted=params_redacted,
                permission_decision=permission_decision,
                permission_reason=permission_reason,
                approval_id=approval_id,
            )
        )
        result = self._error(
            error_kind,
            error_message,
            adapter_kind,
            server_id,
            started,
            approval_ref=approval_ref,
        )
        await self._audit.finalise(
            audit_id,
            outcome="error",
            error_kind=result.error_kind,
            duration_ms=result.meta.duration_ms,
        )
        return result

    def _normalise(
        self,
        result: ToolResult,
        adapter_kind: AdapterKind | None,
        server_id: str | None,
        started: float,
        tool: str,
        operation: str,
    ) -> ToolResult:
        """Re-stamp provenance and apply §3 to the data.

        ``meta`` is rebuilt from the REGISTRY's view of the adapter rather than
        trusted from the adapter's own result: ``adapter_kind``/``server_id``
        land on the ``tool_calls`` row as facts (V2-A exit), and an adapter — an
        MCP server's proxy in particular — must not be able to describe itself
        onto the audit trail. ``duration_ms`` is the manager's measurement,
        which is also what ``finalise`` reports.

        ``approval`` is cleared for the same reason (C1 §2.1 step 7, v1.2.0 /
        ruling R8): without the explicit ``approval=None`` this ``replace`` would
        PRESERVE an adapter-set value, and an adapter that could set it would
        point the owner's decision UI at an approval its call never parked. Only
        step 3's park exit mints the field — and park exits never pass through
        here, so the minted value survives exactly where it was minted.
        """
        data = result.data
        if result.ok and data is not None and adapter_kind in _UNTRUSTED_KINDS:
            data = sanitise_untrusted_data(
                data, context=f"{tool}.{operation}", logger=_LOGGER
            )
        return replace(
            result,
            data=data,
            meta=self._meta(adapter_kind, server_id, started),
            approval=None,
        )

    def _error(
        self,
        error_kind: ToolErrorKind,
        error_message: str,
        adapter_kind: AdapterKind | None,
        server_id: str | None,
        started: float,
        *,
        approval_ref: ApprovalRef | None = None,
    ) -> ToolResult:
        """``approval_ref`` is keyword-only and defaults to None because exactly
        one of this function's callers may pass it: the park exit (C1 v1.2.0's
        invariant — the field is non-None IFF ``error_kind`` is
        ``approval_required``). Positional would let any error result acquire one
        by argument drift."""
        return ToolResult(
            ok=False,
            data=None,
            error_kind=error_kind.value,
            error_message=error_message,
            meta=self._meta(adapter_kind, server_id, started),
            approval=approval_ref,
        )

    @staticmethod
    def _meta(
        adapter_kind: AdapterKind | None, server_id: str | None, started: float
    ) -> ToolResultMeta:
        return ToolResultMeta(
            adapter_kind=adapter_kind,
            server_id=server_id,
            duration_ms=int((time.monotonic() - started) * 1000),
        )


def _server_id_of(adapter: ToolAdapter) -> str | None:
    """MCP adapters carry a ``server_id`` (their ``config/tools.yaml`` key,
    C1 §5); native adapters do not, and the field is None for them (§2).

    ``getattr`` because ``server_id`` is deliberately NOT on C1 §2's
    ``ToolAdapter`` protocol — adding it would oblige every native adapter to
    declare a field whose only legal value is None.
    """
    server_id = getattr(adapter, "server_id", None)
    return server_id if isinstance(server_id, str) else None
