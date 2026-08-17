"""Shared constants and builders for `sunil.core.agent_framework` unit
tests — a uniquely-named module, not `conftest.py`, per the CI rule
against cross-file `from conftest import ...` (see
`tests/unit/registry/registry_helpers.py`'s own docstring for the full
reasoning).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import uuid4

from sunil.core.orchestrator.guards import ExecutionMetadata
from sunil.core.orchestrator.plan_models import ValidatedPlan
from sunil.core.orchestrator.plan_validator import validate_plan
from sunil.core.registry.agents import AgentDefinition
from sunil.core.registry.capture import CaptureRegistry
from sunil.core.registry.loader import Registries
from sunil.core.registry.model_catalogue import CapabilityDefinition, ModelDefinition, ModelRegistry
from sunil.core.registry.permissions import PermissionRegistry
from sunil.core.registry.projects import GithubCoordinates, ProjectDefinition, ProjectRegistry
from sunil.core.registry.tools import ToolDefinition, ToolOperationDefinition, ToolRegistry
from sunil.core.tool_framework.base import ToolResult
from sunil.db.models import Task


def build_agent_definition(*, tools: dict[str, list[str]] | None = None) -> AgentDefinition:
    return AgentDefinition(
        id="project_manager",
        role="Manage software projects and identify risks.",
        instructions=["Review recent project activity."],
        objectives=["Report current project status."],
        memory_scope=["short_term"],
        preferred_capability="general_reasoning",
        escalation_capability="complex_reasoning",
        tools=tools if tools is not None else {"github": ["list_recent_activity"]},
    )


def build_registries(*, agent_definition: AgentDefinition | None = None) -> Registries:
    definition = agent_definition or build_agent_definition()
    agents_map = {definition.id: definition}
    from sunil.core.registry.agents import AgentRegistry

    return Registries(
        agents=AgentRegistry(agents_map),
        permissions=PermissionRegistry(
            {definition.id: {"github": {"list_recent_activity": "allow"}}}
        ),
        projects=ProjectRegistry(
            {
                "easy_clean_workforce": ProjectDefinition(
                    key="easy_clean_workforce",
                    display_name="EasyClean Workforce",
                    github=GithubCoordinates(owner="codely-isuru", repo="easy_clean_workforce"),
                )
            }
        ),
        models=ModelRegistry(
            pricing_version="2026-08-14",
            models={
                "claude-sonnet-5": ModelDefinition(
                    model_id="claude-sonnet-5",
                    provider="anthropic",
                    context_window=1_000_000,
                    max_output=128_000,
                    input_usd_per_mtok=Decimal("2"),
                    output_usd_per_mtok=Decimal("10"),
                    supports_structured_output=True,
                )
            },
            capabilities={
                "general_reasoning": CapabilityDefinition(
                    capability="general_reasoning",
                    provider="anthropic",
                    model="claude-sonnet-5",
                    max_tokens=1024,
                    timeout_s=20,
                )
            },
        ),
        tools=ToolRegistry(
            {
                "github": ToolDefinition(
                    name="github",
                    display_name="GitHub",
                    operations={
                        "list_recent_activity": ToolOperationDefinition(
                            name="list_recent_activity",
                            read_only=True,
                            description="Recent commits, open PRs and open issues.",
                            timeout_s=15,
                            params={"project_key": {"type": "string", "required": True}},
                        )
                    },
                )
            }
        ),
        capture=CaptureRegistry(defaults={}, project_overrides={}),
    )


def build_validated_plan(
    *, project_key: str = "easy_clean_workforce", registries: Registries | None = None
) -> ValidatedPlan:
    """A real `ValidatedPlan`, minted the only legal way — through
    `plan_validator.validate_plan()` — so these tests exercise the actual
    guard `isinstance(plan, ValidatedPlan)` checks against a genuine
    instance, never a stand-in."""
    draft = {
        "intent": "project_status_review",
        "confidence": 0.9,
        "privacy_level": "internal",
        "objective": "Check on EasyClean Workforce.",
        "project_key": project_key,
        "agents": ["project_manager"],
        "tools": ["github"],
        "steps": [
            {"id": "s1", "action": "resolve_project", "tool": "none"},
            {"id": "s2", "action": "list_recent_activity", "tool": "github"},
            {"id": "s3", "action": "summarise_activity", "tool": "none"},
        ],
    }
    return validate_plan(draft, registries or build_registries())


def build_task(*, request_id: str | None = None) -> Task:
    return Task(
        id=str(uuid4()),
        workflow_id=str(uuid4()),
        conversation_id=str(uuid4()),
        request_id=request_id or str(uuid4()),
        objective="Check on EasyClean Workforce.",
        status="in_progress",
        priority="normal",
        assigned_agent="project_manager",
        privacy_level="internal",
    )


def build_execution_metadata(
    *, plan: ValidatedPlan | None = None, task: Task | None = None
) -> ExecutionMetadata:
    validated_plan = plan or build_validated_plan()
    real_task = task or build_task()
    return ExecutionMetadata(
        validated_plan_id=validated_plan.plan_id,
        request_id=real_task.request_id,
        task_id=real_task.id,
        agent_id="project_manager",
    )


@dataclass
class FakeTraceContext:
    """Satisfies the parts of `TraceContext` the agent framework uses."""

    request_id: str = "test-request"
    user_id: str | None = None
    conversation_id: str | None = None
    remaining_values: list[float] = field(default_factory=lambda: [1000.0])
    emitted: list[tuple[Any, str, dict[str, Any] | None, str | None]] = field(default_factory=list)

    async def emit(
        self,
        stage: Any,
        *,
        summary: str,
        detail: dict[str, Any] | None = None,
        task_id: str | None = None,
    ) -> None:
        self.emitted.append((stage, summary, detail, task_id))

    def remaining_deadline_s(self) -> float:
        if len(self.remaining_values) > 1:
            return self.remaining_values.pop(0)
        return self.remaining_values[0]


@dataclass
class RecordedToolCall:
    plan: object
    tool: str
    operation: str
    params: dict[str, Any]
    meta: object
    trace: object


class FakeToolManager:
    """Stands in for `sunil.core.tool_framework.manager.ToolManager` — no
    database, no real adapter. Records every call and returns a scripted
    `ToolResult`."""

    def __init__(self, *, result: ToolResult | None = None) -> None:
        self.calls: list[RecordedToolCall] = []
        self._result = result or ToolResult(
            ok=True,
            data={"commits": [], "pull_requests": [], "issues": []},
            error_kind=None,
            error_message=None,
        )

    async def execute(
        self,
        *,
        plan: object,
        tool: str,
        operation: str,
        params: dict[str, Any],
        meta: object,
        trace: object | None = None,
    ) -> ToolResult:
        self.calls.append(
            RecordedToolCall(
                plan=plan, tool=tool, operation=operation, params=params, meta=meta, trace=trace
            )
        )
        return self._result


class FakeModelRouter:
    """Stands in for `sunil.core.routing.router.ModelRouter` — records
    every `run()` call and returns a scripted `LLMResponse`."""

    def __init__(self, *, response: Any = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self._response = response

    async def run(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        return self._response
