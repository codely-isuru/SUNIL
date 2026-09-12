"""The developer agent — SUNIL's governed front end to an execution engine.

ADR-030 §4: OpenHands is the Developer/QA execution engine, "sandboxed in
Docker, delegated to by ``agents/developer``; all git writes approval-gated
(``push_branch: allow``, ``merge_main: ask_user``)". ARCHITECTURE_V2 §3 states
the same split from the other side: Stream F "consumes C1 (**its git ops are
tool calls**) + C4".

That sentence is the whole design, and it produces three rules this module
exists to make structural:

1. **The engine is not a tool; the git writes are.** The delegation itself is
   the agent's own work — it reaches the engine through an injected client, not
   through the C1 chokepoint, because the chokepoint governs *actions on the
   world* and a sandboxed run that touches nothing outside its own container is
   not one. Everything the run then wants to do to our repository is a C1 tool
   call, decided at the chokepoint from ``config/permissions.yaml``, audited,
   and parked through C4 when the matrix says ``ask_user``.

2. **The engine's reply is untrusted input** (C1 §3). It is the output of an
   autonomous loop that read a repository, an issue tracker and whatever else
   was in its context — the classic prompt-injection carrier. So:

   * the reported *operation* is matched against :data:`GOVERNED_OPERATIONS`, a
     closed set, before anything else happens; an unrecognised one fails the
     turn closed rather than being forwarded for a permission decision (a
     permission *deny* would be the right outcome for the wrong reason — it
     would mean "this agent may not deploy", when what we mean is "this engine
     does not get to choose the verb");
   * the reported *branch* must pass :func:`validate_branch` — charset, no
     traversal, inside the work order's prefix, and never a protected branch.
     Without that last check a ``push_branch: allow`` grant becomes an
     ungoverned write to the exact branch ``merge_main: ask_user`` protects;
   * the reported *prose* never becomes the owner-facing message. ``content``
     is composed by SUNIL from facts SUNIL checked, because ``content`` lands in
     the conversation and the conversation is the next turn's prompt. The
     engine's own words are reported in ``tool_details`` (evidence), not
     narrated as SUNIL's (instructions).

3. **The agent holds no credential.** It names a ``project_key``; the client
   resolves the repository; the sandbox holds its own scoped git token, granted
   at its boot and never passed per-run. There is no code path here that could
   carry one.

**No LLM call.** Unlike the project manager, this agent does not make ADR-015's
analysis call. That call exists to narrate tool output into an answer; here the
narration is deterministic, and feeding untrusted engine prose to a model to be
re-emitted as SUNIL's voice would re-open rule 2 through the back door.

**Where a merge actually happens.** Nowhere in this module. A parked merge ends
the turn (``kind="parked"``); the owner decides in the dashboard, and the C4
continuation executor re-enters the chokepoint with the approval id (ADR-031).
The continuation material minted below carries the engine run id and the intent
index so that resume lands on the same merge and no other.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from sunil.agents.developer.client import (
    REPORT_CONTRACT,
    EngineError,
    EngineErrorKind,
    GitIntent,
    OpenHandsClient,
    RunResult,
    RunState,
    TaskSpec,
)
from sunil.core.agent_framework.base import AgentContext, AgentResult
from sunil.core.orchestrator.guards import require_validated_plan
from sunil.core.tool_framework.base import (
    ParkContext,
    ToolErrorKind,
    TraceContext as ToolTraceContext,
)
from sunil.core.trace.stages import TraceStage

#: The plan step this agent answers to. A NON-tool step (``tool: "none"``): the
#: work order addresses the developer AGENT, and "agents" and "tools" are two
#: different registries on purpose. Registering ``developer.fix_and_pr`` as a
#: tool triple instead would put a catalogue entry in ``config/tools.yaml`` with
#: no adapter behind it — a tool the plan validator must reject and the
#: chokepoint could never execute.
WORK_ORDER_ACTION = "fix_and_pr"

#: The tool the git writes are made through. ``github_mcp``, not the native
#: ``github`` tool, for two reasons: ``config/tools.yaml`` declares the native
#: one "GitHub (native, read-only)", and the dashboard's own worked example
#: (``docs/design/mockups/01-approvals-queue.html``) already shows the approval
#: card as ``github_mcp.merge_main``.
GIT_TOOL = "github_mcp"

#: The closed set of git writes this agent will express on an engine's behalf.
#: Order is the execution order: a branch is pushed before it is merged.
GOVERNED_OPERATIONS: tuple[str, ...] = ("push_branch", "merge_main")

#: Branches a work branch may never be. ``push_branch`` is a grant to push the
#: agent's own branch; these are the ones whose write is governed elsewhere.
PROTECTED_BRANCHES: frozenset[str] = frozenset(
    {"main", "master", "develop", "release", "trunk", "HEAD"}
)

#: Conservative by construction, not by exclusion: only these characters, must
#: start alphanumeric. Rejects `--upload-pack=…` (an argument, not a ref),
#: whitespace, and anything a shell or a git refspec would read as syntax.
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$")

#: How much engine prose is retained as evidence. The engine can emit a
#: megabyte; `tool_details` is persisted and rendered.
MAX_SUMMARY_CHARS = 1000

DEFAULT_POLL_INTERVAL_S = 2.0
#: 150 x 2 s = five minutes of polling. A long-running refactor is expected to
#: outlive one turn; the honest answer then is `timeout`, not a blocked request
#: thread.
DEFAULT_MAX_POLLS = 150
DEFAULT_RUN_TIMEOUT_S = 900.0


class WorkOrder(BaseModel, extra="forbid"):
    """The validated work order. ``extra="forbid"`` for the same reason every
    C1 params model has it (§26.8): a planner must not be able to smuggle an
    extra field — ``runtime``, ``repo_url``, ``token`` — into a delegation."""

    project_key: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9_-]*$")
    instructions: str = Field(min_length=1, max_length=4000)
    base_branch: str = Field(default="main", min_length=1, max_length=120)
    branch_prefix: str = Field(default="sunil/", min_length=1, max_length=40)


class DeveloperAgent:
    """``config/agents.yaml: developer``."""

    id = "developer"

    def __init__(
        self,
        client: OpenHandsClient,
        *,
        poll_interval_s: float = DEFAULT_POLL_INTERVAL_S,
        max_polls: int = DEFAULT_MAX_POLLS,
        run_timeout_s: float = DEFAULT_RUN_TIMEOUT_S,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        # The client is injected, never constructed here: this module then holds
        # no base URL and no transport, which is the same rule the agent
        # framework applies to providers (`core/agent_framework/base.py`).
        self._client = client
        self._poll_interval_s = poll_interval_s
        self._max_polls = max_polls
        self._run_timeout_s = run_timeout_s
        self._sleep = sleep

    async def run(self, plan: object, ctx: AgentContext) -> AgentResult:
        """Guard site 2 (ADR-004 Amendment 1)."""
        validated = require_validated_plan(plan)

        found = _find_work_order(validated)
        if found is None:
            return _failed(
                ToolErrorKind.INVALID_PARAMS,
                {"reason": f"no {WORK_ORDER_ACTION!r} step in the plan"},
            )
        cursor, step = found

        try:
            order = WorkOrder.model_validate(step.params)
        except ValidationError as exc:
            return _failed(
                ToolErrorKind.INVALID_PARAMS,
                {"reason": "work order failed validation", "errors": exc.error_count()},
            )

        await ctx.trace.emit(
            TraceStage.AGENT_STARTED,
            summary="delegated the work order to the developer engine",
            detail={"engine": "openhands", "project_key": order.project_key},
            task_id=ctx.task_id,
        )

        try:
            run = await self._delegate(order)
        except EngineError as exc:
            return _failed(
                ToolErrorKind(exc.kind.value),
                {"engine": "openhands", "reason": exc.message},
            )

        report = {
            "engine": "openhands",
            "run_id": run.run_id,
            "state": run.state.value,
            "branch": run.branch,
            "summary": (run.summary or "")[:MAX_SUMMARY_CHARS] or None,
            "failure_kind": run.failure_kind,
        }

        if run.state is not RunState.SUCCEEDED:
            # The run executed and failed: C1 §4's `upstream_error`. The engine's
            # OWN word for why travels in `failure_kind`, unmapped — guessing a
            # C1 kind from it would be inventing a fact for the audit row.
            return _failed(ToolErrorKind.UPSTREAM_ERROR, report)

        return await self._execute_git_intents(run, order, cursor, ctx, validated, report)

    # -- delegation --------------------------------------------------------- #
    async def _delegate(self, order: WorkOrder) -> RunResult:
        spec = TaskSpec(
            project_key=order.project_key,
            instructions=_compose_instructions(order),
            base_branch=order.base_branch,
            branch_prefix=order.branch_prefix,
            timeout_s=self._run_timeout_s,
        )
        run_id = await self._client.submit(spec)

        for poll in range(self._max_polls):
            state = await self._client.status(run_id)
            if state.is_terminal:
                return await self._client.result(run_id)
            if poll + 1 < self._max_polls:
                await self._sleep(self._poll_interval_s)

        # Never `result()` on a run that has not finished: whatever it reported
        # half-way through is not a report, and acting on it would mean pushing a
        # branch the engine is still writing to.
        raise EngineError(
            EngineErrorKind.TIMEOUT,
            f"run {run_id} did not reach a terminal state in {self._max_polls} polls",
        )

    # -- the governed part -------------------------------------------------- #
    async def _execute_git_intents(
        self,
        run: RunResult,
        order: WorkOrder,
        cursor: int,
        ctx: AgentContext,
        plan: Any,
        report: dict[str, Any],
    ) -> AgentResult:
        result = AgentResult(kind="ok")
        details: list[dict[str, Any]] = [report]

        if not run.git_intents:
            result.tool_details = details
            result.content = _compose_content(run, order, git_calls=0)
            return result

        await ctx.trace.emit(
            TraceStage.TOOL_REQUESTED,
            summary="developer engine git intents reached the C1 chokepoint",
            detail={
                "intents": len(run.git_intents),
                "tool": GIT_TOOL,
                "operations": [intent.operation for intent in run.git_intents],
            },
            task_id=ctx.task_id,
        )

        for index, intent in enumerate(run.git_intents):
            branch, refusal = _vet(intent, run, order)
            if refusal is not None or branch is None:
                kind, detail = refusal  # type: ignore[misc]
                details.append(detail)
                result.kind = "tool_failed"
                result.tool_error_kind = kind.value
                await _emit_git_phase_end(ctx, result, kind.value)
                result.tool_details = details
                return result

            outcome = await self._call_git_tool(
                intent, branch, order, run, index, cursor, plan, ctx
            )
            details.append(outcome)
            result.tool_calls += 1
            result.permission_decision = outcome["permission_decision"]

            if outcome["error_kind"] == ToolErrorKind.APPROVAL_REQUIRED.value:
                result.kind = "parked"
                result.approval_id = outcome["approval_id"]
                result.approval_expires_at = outcome["expires_at"]
                result.approval_summary = outcome["summary"]
                break
            if outcome["error_kind"] is not None:
                result.kind = "tool_failed"
                result.tool_error_kind = outcome["error_kind"]
                break
            result.steps_executed += 1

        await _emit_git_phase_end(ctx, result, result.tool_error_kind)

        result.tool_details = details
        if result.kind == "ok":
            result.content = _compose_content(run, order, git_calls=result.steps_executed)
        return result

    async def _call_git_tool(
        self,
        intent: GitIntent,
        branch: str,
        order: WorkOrder,
        run: RunResult,
        index: int,
        cursor: int,
        plan: Any,
        ctx: AgentContext,
    ) -> dict[str, Any]:
        # Params are built HERE, from values SUNIL validated — never copied from
        # the engine's reply. `branch` is the one engine-derived value and it has
        # been through `validate_branch` above.
        params = {
            "project_key": order.project_key,
            "branch": branch,
            "base_branch": order.base_branch,
        }
        park_context = ParkContext(
            continuation={
                "plan": plan.raw,
                "plan_id": plan.plan_id,
                "cursor": cursor,
                "agent_id": ctx.agent_id,
                "request_id": ctx.request_id,
                "task_id": ctx.task_id,
                "conversation_id": ctx.conversation_id,
                # Stream F's addition to ADR-031's material: a resumed merge must
                # land on the SAME engine run and the SAME intent, not on
                # whatever the plan step would produce if re-delegated.
                "engine": "openhands",
                "run_id": run.run_id,
                "intent_index": index,
                "branch": branch,
            },
            # SUNIL-composed, never engine output (C4 §4). `branch` is included
            # because it is the identity of the thing being authorised; it is
            # charset-restricted by `validate_branch` before it gets here.
            summary=(
                f"{GIT_TOOL}.{intent.operation} requires approval: "
                f"{branch} -> {order.base_branch} on project {order.project_key}"
            )[:500],
        )

        tool_result = await ctx.tool_manager.execute(
            ctx.agent_id,
            GIT_TOOL,
            intent.operation,
            params,
            trace=ToolTraceContext(
                request_id=ctx.request_id,
                task_id=ctx.task_id,
                conversation_id=ctx.conversation_id,
            ),
            park_context=park_context,
        )
        ref = tool_result.approval
        return {
            "tool": GIT_TOOL,
            "operation": intent.operation,
            "branch": branch,
            "ok": tool_result.ok,
            "error_kind": tool_result.error_kind,
            "permission_decision": _decision_of(ctx, intent.operation),
            "approval_id": ref.approval_id if ref is not None else None,
            "expires_at": ref.expires_at if ref is not None else None,
            "summary": park_context.summary,
        }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _find_work_order(plan: Any) -> tuple[int, Any] | None:
    for cursor, step in enumerate(plan.steps):
        if step.action == WORK_ORDER_ACTION and not step.is_tool_call:
            return cursor, step
    return None


def validate_branch(name: str | None, order: WorkOrder) -> str | None:
    """The engine-reported branch, or ``None`` if it may not be used.

    Four checks, each closing a distinct hole:
    charset/shape (a ref, not an argument), no ``..`` (traversal and git's own
    range syntax), inside the work order's prefix (the engine works where it was
    told to), and not protected (``push_branch: allow`` is not a licence to
    write ``main``).
    """
    if not name:
        return None
    if not _BRANCH_RE.match(name):
        return None
    if ".." in name:
        return None
    if name in PROTECTED_BRANCHES or name.split("/")[-1] in PROTECTED_BRANCHES:
        return None
    if name == order.base_branch:
        return None
    if not name.startswith(order.branch_prefix):
        return None
    return name


def _vet(
    intent: GitIntent, run: RunResult, order: WorkOrder
) -> tuple[str | None, tuple[ToolErrorKind, dict[str, Any]] | None]:
    """Fail-closed checks on the engine's request, before the chokepoint.

    Returns ``(branch, None)`` for an accepted intent, or ``(None, refusal)``.
    The accepted branch is RETURNED rather than recomputed by the caller so that
    the value which passed the checks is the value that is used — the class of
    bug where a validator and its consumer read the field twice and disagree.
    """
    if intent.operation not in GOVERNED_OPERATIONS:
        return None, (
            ToolErrorKind.UNKNOWN_OPERATION,
            {
                "refused_operation": intent.operation,
                "reason": "the developer engine may only request operations in "
                f"{GOVERNED_OPERATIONS}",
            },
        )
    candidate = intent.branch or run.branch
    branch = validate_branch(candidate, order)
    if branch is None:
        return None, (
            ToolErrorKind.INVALID_PARAMS,
            {
                "refused_branch": candidate,
                "reason": "branch is missing, malformed, protected, or outside "
                f"the work order prefix {order.branch_prefix!r}",
            },
        )
    return branch, None


def _failed(kind: ToolErrorKind, *details: dict[str, Any]) -> AgentResult:
    """`AgentResult.kind` is a CLOSED literal (`core/agent_framework/base.py`)
    and `turn.py` maps only `tool_failed` / `provider_error` onto a C5 failure —
    a new member would be silently treated as success. So an engine failure is
    reported as `tool_failed` with the honest C1 §4 kind in `tool_error_kind`
    and the engine's own account in `tool_details`. See
    `docs/tasks/S2-F-openhands.md` for the integration request that would give
    it a kind of its own."""
    return AgentResult(
        kind="tool_failed", tool_error_kind=kind.value, tool_details=list(details)
    )


async def _emit_git_phase_end(
    ctx: AgentContext, result: AgentResult, error_kind: str | None
) -> None:
    await ctx.trace.emit(
        TraceStage.PERMISSION_DECISION,
        summary="permission decided at the C1 chokepoint",
        detail={"decision": result.permission_decision or "none", "calls": result.tool_calls},
        task_id=ctx.task_id,
    )
    await ctx.trace.emit(
        TraceStage.TOOL_RESULT,
        summary="developer git phase finished",
        detail={
            "outcome": "ok" if result.kind == "ok" else "error",
            "error_kind": error_kind
            or (ToolErrorKind.APPROVAL_REQUIRED.value if result.kind == "parked" else "none"),
            "executed": result.steps_executed,
        },
        task_id=ctx.task_id,
    )


def _decision_of(ctx: AgentContext, operation: str) -> str | None:
    """The decision as the AUDIT recorded it, not as the agent inferred it."""
    attempts = getattr(ctx.audit_hook, "attempts", None)
    if not attempts:
        return None
    for record in reversed(attempts):
        if record.tool == GIT_TOOL and record.operation == operation:
            return (
                record.permission_decision.value
                if record.permission_decision is not None
                else None
            )
    return None


def _compose_instructions(order: WorkOrder) -> str:
    """The delegated prompt. Composed by SUNIL: the branch policy is stated to
    the engine here AND enforced on the way back (`validate_branch`), because a
    prompt is a request and only the return-path check is a control."""
    return (
        f"{order.instructions}\n\n"
        f"Branch policy: base your work on '{order.base_branch}'. Create ONE "
        f"branch whose name begins with '{order.branch_prefix}'. Never commit to "
        f"'{order.base_branch}' and never merge anything.\n\n"
        f"{REPORT_CONTRACT}"
    )


def _compose_content(run: RunResult, order: WorkOrder, *, git_calls: int) -> str:
    """SUNIL's words about facts SUNIL checked. No engine prose — see rule 2 in
    the module docstring."""
    branch = validate_branch(run.branch, order)
    where = f" on branch {branch}" if branch else ""
    return (
        f"The developer engine finished run {run.run_id} for project "
        f"{order.project_key}{where}. {git_calls} git operation(s) were executed "
        "through the permission chokepoint."
    )
