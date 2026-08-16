"""Agent framework primitives (`ARCHITECTURE_V1.md` §10.1, NFR-007).

`AgentContext` is the load-bearing piece of this module, and the binding
constraint on it (the Delivery Manager, following BE-3's finding while
building T9): **an agent must never be able to mint or supply its own
`ExecutionMetadata`.** BE-3 proved that a forged `ValidatedPlan` (built
via `object.__new__`, bypassing `__init__`'s token check) carrying a
self-minted `ExecutionMetadata` passes `ToolManager.execute()`'s guard
site 3 today — re-verifying the stored `plans` row is DC-14, deferred to
M5 — so the *only* thing standing between "agent code" and "a tool call
authorised by a plan nobody validated" is that agent code has no
reachable way to construct or substitute an `ExecutionMetadata` on the
path it is actually given.

**How this is built, structurally, not as a docstring convention:**

`AgentContext.call_tool()` is not a regular method. It is an `async`
closure, built fresh inside `AgentContext.__init__` and assigned to
`self.call_tool` — so the `ExecutionMetadata` and the `ValidatedPlan` it
closes over are captured in the closure's cells, not stored as *any*
attribute of `self` under *any* name (mangled or not). Three
consequences, each checked by a test in this package:

1. **The public signature has no parameter for it.** `call_tool(tool,
   operation, params)` — three arguments, none of them metadata. There is
   no keyword an agent could pass to override what gets sent to the Tool
   Manager (`test_call_tool_signature_has_no_metadata_parameter`).
2. **There is nothing to overwrite.** `ctx.metadata = forged`,
   `ctx._metadata = forged`, `ctx.__dict__["metadata"] = forged` — none of
   these have any effect on what `call_tool()` actually sends, because
   `call_tool()` never reads an attribute named anything like that; it
   reads the closure cell it was built with
   (`test_assigning_a_forged_metadata_attribute_has_no_effect`).
3. **Nothing beyond the four granted capabilities is exposed at all** —
   `dir(AgentContext)` (the class) and `dir(instance)`/`vars(instance)`
   (a constructed one) show only `call_tool`, `ask_model`, `memory`,
   `trace` (`test_the_agent_context_instance_exposes_only_the_four_capabilities`,
   which is a stronger, instance-level version of Security's own
   class-level `test_agent_context_exposes_no_session_no_client_and_no_secret`).

**Stated honestly, per the same discipline ADR-004 Amendment 1 applied to
`ValidatedPlan`:** this is not a claim that Python makes closures
unreachable in principle — a sufficiently determined caller with a
reference to the closure's `__closure__` cells could still read them.
What it removes is the *sanctioned* path: there is no method signature,
no conventionally-named attribute, and no documented API through which
agent code — which only ever receives an `AgentContext`, never a
`ToolManager` or a raw `ExecutionMetadata` reference — can supply a
different plan or metadata than the one the runner minted for this turn.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from sunil.core.orchestrator.guards import ExecutionMetadata
from sunil.core.orchestrator.plan_models import ValidatedPlan
from sunil.core.registry.agents import AgentDefinition
from sunil.core.routing.router import LLMPurpose, ModelRouter
from sunil.core.tool_framework.base import ToolResult
from sunil.core.tool_framework.manager import ToolManager
from sunil.core.trace.context import TraceContext
from sunil.core.trace.stages import TraceStage
from sunil.db.models import Task
from sunil.logging import get_logger
from sunil.providers.base import ChatTurn, LLMRequest, LLMResponse

_logger = get_logger("sunil.agent_framework")

# A short, deliberately small default: M1's one agent produces a 2-4
# sentence summary (ADR-000 Q2), never a long-form document.
_DEFAULT_ANALYSIS_MAX_TOKENS = 500


@dataclass(frozen=True)
class AgentResult:
    """What `Agent.run()` returns (§10.1). `summary` is the agent's prose
    — the user-facing answer in M1 (ADR-015), never raw tool JSON."""

    summary: str
    tool_calls: list[str]
    ok: bool
    error_kind: str | None


class Agent(Protocol):
    """What every `agents/*` package implements."""

    id: str

    async def run(self, plan: ValidatedPlan, task: Task, ctx: AgentContext) -> AgentResult: ...


class AgentMemory(Protocol):
    """The agent's own memory scope (§10.1) — read/write, nothing else.
    No M1 agent exercises this (the PM agent's fixed pipeline needs none,
    ADR-000 Q2); the interface exists so `agents/*` code written against
    it needs no change when a real backing store (T11a's
    `core/memory/short_term.py`) lands."""

    async def read(self) -> list[dict[str, object]]: ...

    async def write(self, content: str, *, source_request_id: str) -> None: ...


class NullAgentMemory:
    """Records nothing, returns nothing — the default until a real
    memory store exists."""

    async def read(self) -> list[dict[str, object]]:
        return []

    async def write(self, content: str, *, source_request_id: str) -> None:
        return None


class ToolNotGrantedForAgent(Exception):
    """FR-082: the agent's own `config/agents.yaml` tool list does not
    grant this `(tool, operation)` pair. Raised before the Tool Manager is
    ever reached — `ToolManager.execute()` step 2 duplicates this check
    as defence in depth, but this is the one FR-082 actually requires
    ("rejected before the Tool Manager is invoked")."""

    def __init__(self, agent_id: str, tool: str, operation: str) -> None:
        self.agent_id = agent_id
        self.tool = tool
        self.operation = operation
        super().__init__(f"agent {agent_id!r} is not granted {tool}.{operation} in agents.yaml")


class AgentContext:
    """Exactly four capabilities (§10.1, NFR-007): `call_tool`,
    `ask_model`, `memory`, `trace`. No DB session, no HTTP client, no
    secrets — and, per the module docstring, no way to mint or override
    the `ExecutionMetadata` that authorises a tool call.

    Constructed once per agent invocation by `core.agent_framework.runner`
    (trusted code) — never by agent code itself.
    """

    def __init__(
        self,
        *,
        agent_definition: AgentDefinition,
        model_router: ModelRouter,
        tool_manager: ToolManager,
        memory: AgentMemory,
        trace: TraceContext,
        plan: ValidatedPlan,
        metadata: ExecutionMetadata,
        request_id: str,
        task_id: str,
        agent_id: str,
    ) -> None:
        self.memory = memory
        self.trace = trace

        async def call_tool(tool: str, operation: str, params: dict[str, object]) -> ToolResult:
            """The only way agent code can reach the Tool Manager.
            `plan` and `metadata` are captured in this closure — see the
            module docstring for why that is the control, not a
            convention."""
            if operation not in agent_definition.tools.get(tool, []):
                _logger.warning(
                    "tool_not_granted",
                    agent_id=agent_id,
                    tool=tool,
                    operation=operation,
                )
                raise ToolNotGrantedForAgent(agent_id, tool, operation)

            await trace.emit(
                TraceStage.TOOL_REQUESTED,
                summary=f"requesting {tool}.{operation}",
                detail={"tool": tool, "operation": operation},
                task_id=task_id,
            )

            return await tool_manager.execute(
                plan=plan,
                tool=tool,
                operation=operation,
                params=params,
                meta=metadata,
                trace=trace,
            )

        async def ask_model(
            *,
            system: str,
            messages: list[ChatTurn],
            max_tokens: int = _DEFAULT_ANALYSIS_MAX_TOKENS,
            json_schema: dict | None = None,
            use_escalation: bool = False,
        ) -> LLMResponse:
            """The agent supplies the system prompt and the content it
            wants analysed — never a model or vendor name, never a
            capability directly. `use_escalation` selects between the
            agent's own `preferred_capability` and `escalation_capability`
            (both from `config/agents.yaml`, §4.5) — the only choice M1
            gives agent code over model selection.

            Composing *what* the system prompt says is deliberately left
            to the agent (`agents/project_manager/agent.py`'s
            `SYSTEM_PROMPT`), not built in here from `agent_definition` —
            that keeps this method a thin, agent-agnostic router call, and
            keeps the prompt text somewhere a security review's static
            checks (`agent_mod.SYSTEM_PROMPT`) can import and assert
            against directly.
            """
            capability = (
                agent_definition.escalation_capability
                if use_escalation
                else agent_definition.preferred_capability
            )
            request = LLMRequest(
                system=system,
                messages=messages,
                max_tokens=max_tokens,
                json_schema=json_schema,
            )
            return await model_router.run(
                capability=capability,
                request=request,
                purpose=LLMPurpose.ANALYSIS,
                ctx=trace,
                request_id=request_id,
                task_id=task_id,
                agent_id=agent_id,
            )

        self.call_tool = call_tool
        self.ask_model = ask_model
