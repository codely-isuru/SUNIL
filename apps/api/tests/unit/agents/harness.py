"""Test-only doubles for the Stream F developer seam.

Everything here is a TEST utility and lives in the test tree deliberately: no
production class grows a "for tests" branch, and nothing in
``sunil/agents/developer/`` knows this module exists.

Three doubles:

* :class:`StubGitAdapter` — a C1 adapter named ``github_mcp`` exposing the two
  write operations Stream F needs (``push_branch``, ``merge_main``). It stands
  in for the real MCP server that Stream A/E will wire; the point of these
  tests is the governance around the call, not the call's remote effect.
* :class:`FakeOpenHands` — a scripted :class:`OpenHandsClient`. Records what was
  submitted and replays a scripted state sequence and result (or raises an
  :class:`EngineError`), so an agent-level test never needs a container.
* :func:`build_ctx` / :func:`build_work_order_plan` — the wiring the orchestrator
  would do, assembled from the REAL Tool Manager, the REAL permission
  chokepoint shape (C1 §6.1's fake hook), C4 §6's ``FakeApprovalsService`` and
  the REAL plan validator. Only the two vendors are faked.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from sunil.agents.developer.client import (
    EngineError,
    RunResult,
    RunState,
    TaskSpec,
)
from sunil.core.agent_framework.base import AgentContext, UsageTally
from sunil.core.orchestrator.plan_validator import ToolCatalogue, validate_plan
from sunil.core.tool_framework.base import (
    AdapterKind,
    ToolAdapter,
    ToolOperation,
    ToolResult,
    ToolResultMeta,
)
from sunil.core.tool_framework.manager import ToolManager
from sunil.core.trace.context import NullTraceContext

from tests.fakes.fake_approvals import FakeApprovalsService
from tests.fakes.fake_hooks import FakePermissionHook, RecordingAuditHook

GIT_TOOL = "github_mcp"


# --------------------------------------------------------------------------- #
# A C1 adapter for the two git write operations
# --------------------------------------------------------------------------- #
class PushBranchParams(BaseModel, extra="forbid"):
    project_key: str = Field(min_length=1, max_length=64)
    branch: str = Field(min_length=1, max_length=120)
    base_branch: str = Field(min_length=1, max_length=120)


class MergeMainParams(BaseModel, extra="forbid"):
    project_key: str = Field(min_length=1, max_length=64)
    branch: str = Field(min_length=1, max_length=120)
    base_branch: str = Field(min_length=1, max_length=120)


class StubGitAdapter:
    """``github_mcp`` with the Stream F write operations.

    Structural conformance only (the ``_check`` witness at the foot of this
    module), for the reason C1 §6.3's own fake states: inheriting a Protocol
    hands the subclass ``...`` bodies that return ``None``.
    """

    def __init__(self) -> None:
        self.name = GIT_TOOL
        self.kind = AdapterKind.MCP_HTTP
        self.started = False
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.operations: dict[str, ToolOperation] = {
            "push_branch": ToolOperation(
                name="push_branch",
                params_model=PushBranchParams,
                read_only=False,
                timeout_s=30.0,
                handler=self._push_branch,
            ),
            "merge_main": ToolOperation(
                name="merge_main",
                params_model=MergeMainParams,
                read_only=False,
                timeout_s=30.0,
                handler=self._merge_main,
            ),
        }

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def _push_branch(self, params: PushBranchParams) -> ToolResult:
        self.calls.append(("push_branch", params.model_dump()))
        return self._ok({"pushed": params.branch})

    async def _merge_main(self, params: MergeMainParams) -> ToolResult:
        self.calls.append(("merge_main", params.model_dump()))
        return self._ok({"merged": params.branch})

    @staticmethod
    def _ok(data: dict[str, Any]) -> ToolResult:
        return ToolResult(
            ok=True,
            data=data,
            error_kind=None,
            error_message=None,
            meta=ToolResultMeta(
                adapter_kind=AdapterKind.MCP_HTTP, server_id=GIT_TOOL, duration_ms=1
            ),
        )


_check_adapter: ToolAdapter = StubGitAdapter()


# --------------------------------------------------------------------------- #
# The scripted OpenHands engine
# --------------------------------------------------------------------------- #
class FakeOpenHands:
    """Scripted ``OpenHandsClient``. No HTTP, no container, no clock."""

    def __init__(
        self,
        *,
        result: RunResult | None = None,
        states: Sequence[RunState] | None = None,
        submit_error: EngineError | None = None,
        status_error: EngineError | None = None,
        result_error: EngineError | None = None,
        run_id: str = "run-1",
    ) -> None:
        self._result = result
        self._states = list(states) if states is not None else [RunState.SUCCEEDED]
        self._submit_error = submit_error
        self._status_error = status_error
        self._result_error = result_error
        self._run_id = run_id
        self.submitted: list[TaskSpec] = []
        self.status_calls = 0

    async def submit(self, spec: TaskSpec) -> str:
        self.submitted.append(spec)
        if self._submit_error is not None:
            raise self._submit_error
        return self._run_id

    async def status(self, run_id: str) -> RunState:
        self.status_calls += 1
        if self._status_error is not None:
            raise self._status_error
        if len(self._states) > 1:
            return self._states.pop(0)
        return self._states[0]

    async def result(self, run_id: str) -> RunResult:
        if self._result_error is not None:
            raise self._result_error
        if self._result is None:  # pragma: no cover - misconfigured double
            raise AssertionError("FakeOpenHands.result called with no scripted result")
        return self._result


class RecordingSleep:
    """Replaces ``asyncio.sleep`` so a poll loop costs no wall-clock time."""

    def __init__(self) -> None:
        self.slept: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.slept.append(seconds)


# --------------------------------------------------------------------------- #
# Orchestrator-side wiring
# --------------------------------------------------------------------------- #
AGENTS_REGISTRY: dict[str, Any] = {
    "developer": {
        "tools": {GIT_TOOL: ["push_branch", "merge_main"]},
    }
}


def build_work_order_plan(
    params: dict[str, Any],
    *,
    action: str = "fix_and_pr",
    extra_steps: list[dict[str, Any]] | None = None,
):
    """A ValidatedPlan minted by the REAL validator.

    The work order is a NON-tool step (``tool: "none"``): it addresses the
    developer AGENT, not a tool in the permission matrix. See
    ``sunil/agents/developer/agent.py`` for why that distinction is load-bearing.
    """
    draft = {
        "intent": "tool_operation",
        "confidence": 0.9,
        "privacy_level": "internal",
        "objective": "fix the failing test and open a PR",
        "project_key": None,
        "agents": ["developer"],
        "tools": [],
        "steps": [
            {
                "id": "s1",
                "action": action,
                "tool": "none",
                "operation": "none",
                "params": params,
            },
            *(extra_steps or []),
        ],
    }
    return validate_plan(
        draft,
        agents=AGENTS_REGISTRY,
        catalogue=ToolCatalogue(
            operations_by_tool={GIT_TOOL: frozenset({"push_branch", "merge_main"})}
        ),
    )


class Wiring:
    """What the orchestrator would have constructed for one developer turn."""

    def __init__(self, *, decisions: dict[str, str]) -> None:
        self.adapter = StubGitAdapter()
        self.permissions = FakePermissionHook()
        for operation, decision in decisions.items():
            self.permissions.grant("developer", GIT_TOOL, operation, decision)  # type: ignore[arg-type]
        self.approvals = FakeApprovalsService()
        self.audit = RecordingAuditHook()
        self.manager = ToolManager(
            [self.adapter], self.permissions, self.approvals, self.audit
        )
        self.trace = NullTraceContext(request_id="req-1", conversation_id="conv-1")
        self.usage = UsageTally()

    def ctx(self) -> AgentContext:
        return AgentContext(
            agent_id="developer",
            request_id="req-1",
            task_id="task-1",
            conversation_id="conv-1",
            model="unused",
            privacy_class="internal",
            system_prompt="unused",
            user_message="fix the failing test",
            history=[],
            memory_items=[],
            trace=self.trace,
            tool_manager=self.manager,
            audit_hook=self.audit,
            provider=_ProviderThatMustNotBeCalled(),
            usage=self.usage,
            record_llm_call=_record_llm_call_must_not_be_called,
        )


class _ProviderThatMustNotBeCalled:
    """The developer agent composes its answer deterministically: it makes no
    analysis call, so untrusted engine prose never becomes a prompt."""

    async def complete(self, request: Any) -> Any:  # pragma: no cover - guard
        raise AssertionError("the developer agent must not call an LLM provider")


async def _record_llm_call_must_not_be_called(**kwargs: Any) -> None:  # pragma: no cover
    raise AssertionError("the developer agent must not record an llm_calls row")


def monotonic_ms() -> int:
    return int(time.monotonic() * 1000)
