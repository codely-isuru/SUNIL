"""`sunil.core.agent_framework.base.AgentContext` — the structural control
that keeps an agent from minting or overriding `ExecutionMetadata` (the
Delivery Manager's binding constraint, following BE-3's T9 finding).
"""

from __future__ import annotations

import inspect

import pytest
from sunil.core.agent_framework.base import (
    AgentContext,
    NullAgentMemory,
    ToolNotGrantedForAgent,
)
from sunil.core.routing.router import LLMPurpose
from sunil.providers.base import ChatTurn

from .agent_framework_helpers import (
    FakeModelRouter,
    FakeToolManager,
    FakeTraceContext,
    build_agent_definition,
    build_execution_metadata,
    build_validated_plan,
)


def _build_context(
    *,
    tool_manager: FakeToolManager | None = None,
    model_router: FakeModelRouter | None = None,
    trace: FakeTraceContext | None = None,
    agent_definition=None,
):
    plan = build_validated_plan()
    metadata = build_execution_metadata(plan=plan)
    definition = agent_definition or build_agent_definition()
    active_trace = trace or FakeTraceContext()
    ctx = AgentContext(
        agent_definition=definition,
        model_router=model_router or FakeModelRouter(),
        tool_manager=tool_manager or FakeToolManager(),
        memory=NullAgentMemory(),
        trace=active_trace,
        plan=plan,
        metadata=metadata,
        request_id=active_trace.request_id,
        task_id="task-1",
        agent_id="project_manager",
    )
    return ctx, plan, metadata


# -- Structural: the four capabilities and nothing else ---------------------


def test_the_agent_context_class_exposes_no_public_class_level_members() -> None:
    """Mirrors Security's own `test_agent_context_exposes_no_session_no_
    client_and_no_secret` (class-level `dir()`)."""
    public = {n for n in dir(AgentContext) if not n.startswith("_") and not n.isupper()}
    assert public == set()


def test_the_agent_context_instance_exposes_only_the_four_capabilities() -> None:
    """The stronger, instance-level version: even after construction, the
    only public attributes are the four granted capabilities."""
    ctx, _plan, _metadata = _build_context()

    public = {n for n in vars(ctx) if not n.startswith("_")}
    assert public == {"memory", "trace", "call_tool", "ask_model"}


def test_call_tool_signature_has_no_metadata_or_plan_parameter() -> None:
    ctx, _plan, _metadata = _build_context()

    signature = inspect.signature(ctx.call_tool)
    assert set(signature.parameters) == {"tool", "operation", "params"}


async def test_call_tool_rejects_an_attempt_to_pass_meta_or_plan() -> None:
    ctx, _plan, _metadata = _build_context()

    with pytest.raises(TypeError):
        await ctx.call_tool("github", "list_recent_activity", {"project_key": "x"}, meta="forged")
    with pytest.raises(TypeError):
        await ctx.call_tool("github", "list_recent_activity", {"project_key": "x"}, plan="forged")


async def test_assigning_a_forged_metadata_attribute_has_no_effect() -> None:
    """Prove the fence: a malicious agent tries every guessable attribute
    name to override the metadata `call_tool()` actually sends, then
    calls `call_tool()` and confirms the *real* metadata (from the
    closure) reached the Tool Manager regardless."""
    tool_manager = FakeToolManager()
    ctx, _plan, real_metadata = _build_context(tool_manager=tool_manager)

    forged = object()
    ctx.metadata = forged  # type: ignore[attr-defined]
    ctx._metadata = forged  # type: ignore[attr-defined]
    ctx.__dict__["metadata"] = forged
    ctx.__dict__["_metadata"] = forged

    await ctx.call_tool("github", "list_recent_activity", {"project_key": "easy_clean_workforce"})

    assert len(tool_manager.calls) == 1
    assert tool_manager.calls[0].meta is real_metadata
    assert tool_manager.calls[0].meta is not forged


# -- call_tool: the FR-082 precheck and the ToolManager hand-off -------------


async def test_call_tool_delegates_to_the_tool_manager_with_the_closed_over_plan_and_metadata() -> (
    None
):
    tool_manager = FakeToolManager()
    ctx, plan, metadata = _build_context(tool_manager=tool_manager)

    result = await ctx.call_tool(
        "github", "list_recent_activity", {"project_key": "easy_clean_workforce"}
    )

    assert result.ok is True
    assert len(tool_manager.calls) == 1
    call = tool_manager.calls[0]
    assert call.plan is plan
    assert call.meta is metadata
    assert call.tool == "github"
    assert call.operation == "list_recent_activity"
    assert call.params == {"project_key": "easy_clean_workforce"}


async def test_call_tool_emits_the_tool_requested_stage_before_delegating() -> None:
    from sunil.core.trace.stages import TraceStage

    trace = FakeTraceContext()
    ctx, _plan, _metadata = _build_context(trace=trace)

    await ctx.call_tool("github", "list_recent_activity", {"project_key": "easy_clean_workforce"})

    assert len(trace.emitted) == 1
    stage, _summary, detail, task_id = trace.emitted[0]
    assert stage == TraceStage.TOOL_REQUESTED
    assert detail == {"tool": "github", "operation": "list_recent_activity"}
    assert task_id == "task-1"


async def test_call_tool_rejects_an_operation_the_agent_is_not_granted() -> None:
    """FR-082: rejected *before* the Tool Manager is invoked."""
    tool_manager = FakeToolManager()
    definition = build_agent_definition(tools={"github": ["list_recent_activity"]})
    ctx, _plan, _metadata = _build_context(tool_manager=tool_manager, agent_definition=definition)

    with pytest.raises(ToolNotGrantedForAgent):
        await ctx.call_tool("github", "delete_repo", {"project_key": "easy_clean_workforce"})

    assert tool_manager.calls == []


async def test_call_tool_rejects_an_entirely_unlisted_tool() -> None:
    tool_manager = FakeToolManager()
    ctx, _plan, _metadata = _build_context(tool_manager=tool_manager)

    with pytest.raises(ToolNotGrantedForAgent):
        await ctx.call_tool("filesystem", "read_file", {"path": "/etc/passwd"})

    assert tool_manager.calls == []


# -- ask_model: purpose, capability selection, no vendor/model exposure ------


async def test_ask_model_always_uses_the_analysis_purpose() -> None:
    router = FakeModelRouter(response="a response")
    ctx, _plan, _metadata = _build_context(model_router=router)

    await ctx.ask_model(system="sys", messages=[ChatTurn(role="user", content="hi")])

    assert len(router.calls) == 1
    assert router.calls[0]["purpose"] == LLMPurpose.ANALYSIS


async def test_ask_model_uses_the_preferred_capability_by_default() -> None:
    router = FakeModelRouter(response="a response")
    ctx, _plan, _metadata = _build_context(model_router=router)

    await ctx.ask_model(system="sys", messages=[ChatTurn(role="user", content="hi")])

    assert router.calls[0]["capability"] == "general_reasoning"


async def test_ask_model_uses_the_escalation_capability_when_asked() -> None:
    router = FakeModelRouter(response="a response")
    ctx, _plan, _metadata = _build_context(model_router=router)

    await ctx.ask_model(
        system="sys", messages=[ChatTurn(role="user", content="hi")], use_escalation=True
    )

    assert router.calls[0]["capability"] == "complex_reasoning"


async def test_ask_model_passes_the_supplied_system_prompt_verbatim() -> None:
    router = FakeModelRouter(response="a response")
    ctx, _plan, _metadata = _build_context(model_router=router)

    await ctx.ask_model(system="exactly this text", messages=[ChatTurn(role="user", content="hi")])

    assert router.calls[0]["request"].system == "exactly this text"


async def test_ask_model_never_sets_a_tools_parameter() -> None:
    """THREAT_MODEL §5.1 control 1, at the framework level: `LLMRequest`
    has no `tools` field at all, so there is nothing for this call to
    accidentally set."""
    router = FakeModelRouter(response="a response")
    ctx, _plan, _metadata = _build_context(model_router=router)

    await ctx.ask_model(system="sys", messages=[ChatTurn(role="user", content="hi")])

    request = router.calls[0]["request"]
    assert not hasattr(request, "tools")


# -- NullAgentMemory ----------------------------------------------------------


async def test_null_agent_memory_reads_empty_and_writes_are_no_ops() -> None:
    memory = NullAgentMemory()

    assert await memory.read() == []
    assert await memory.write("anything", source_request_id="r1") is None
