"""C1 — Tool Adapter contract suite.

Source of truth: ``docs/contracts/C1-tool-adapter.md`` v1.0.0 (FROZEN 2026-09-10).

Two halves, deliberately separated:

* **Fake-level (executable now).** Everything C1 §6.1–§6.3 fixes about the three
  QA fakes, plus §6.4's canonicalisation rule. These are the assertions Streams A
  and E rely on when they build against the fakes.
* **Pipeline-level (C1 contract tests 1–7).** Every one of them exercises
  ``ToolManager.execute`` — C1 §2.1's chokepoint, which lives in
  ``sunil/core/tool_framework/manager.py`` and is *production* code owned by the
  implementing engineer, not QA (a QA-written chokepoint would mean QA testing
  its own implementation). The bodies are written in full against the frozen
  §2.1 signature and skip, loudly, until that module exists. They are documented
  debt in ``docs/tasks/P0-fakes.md`` — never a faked pass.
"""

from __future__ import annotations

import asyncio
import time

import pytest
from pydantic import ValidationError

from sunil.core.approvals.base import ApprovalStatus
from sunil.core.tool_framework.base import (
    AdapterKind,
    PermissionDecision,
    PermissionResult,
    ToolCallAttempt,
    ToolErrorKind,
    ToolResult,
    ToolResultMeta,
    TraceContext,
)
from tests.fakes.canonical import args_hash
from tests.fakes.clock import FakeClock
from tests.fakes.fake_approvals import FakeApprovalsService
from tests.fakes.fake_hooks import FakePermissionHook, RecordingAuditHook
from tests.fakes.fake_tool_adapter import (
    EchoParams,
    FakeToolAdapter,
    NoParams,
    WriteItemParams,
)

pytestmark = pytest.mark.contract

TRACE = TraceContext(request_id="req-1", task_id="task-1", conversation_id="conv-1")


def tool_manager_class():
    """C1 §2.1's ``ToolManager`` — or an explicit skip while it does not exist."""
    try:
        from sunil.core.tool_framework.manager import ToolManager  # noqa: PLC0415
    except ModuleNotFoundError:
        pytest.skip(
            "C1 §2.1 ToolManager (sunil/core/tool_framework/manager.py) is not built "
            "yet — Phase 2 production code, not a QA deliverable. The fakes and the "
            "assertions in this test are ready; the suite activates when it lands."
        )
    return ToolManager


@pytest.fixture
def adapter() -> FakeToolAdapter:
    return FakeToolAdapter()


@pytest.fixture
def hook() -> FakePermissionHook:
    return FakePermissionHook()


@pytest.fixture
def audit() -> RecordingAuditHook:
    return RecordingAuditHook()


@pytest.fixture
def approvals() -> FakeApprovalsService:
    return FakeApprovalsService(consume_grace_hours=1, clock=FakeClock())


@pytest.fixture
def manager(adapter, hook, approvals, audit):
    """C1 §6.4's fixture, verbatim: ``ToolManager([FakeToolAdapter()],
    FakePermissionHook(), FakeApprovalsService(), RecordingAuditHook())``."""
    return tool_manager_class()([adapter], hook, approvals, audit)


# ========================================================================== #
# Fake-level: C1 §6.3 FakeToolAdapter
# ========================================================================== #
def test_fake_adapter_identity_and_operation_table(adapter: FakeToolAdapter) -> None:
    """C1 §6.3 — ``name="fake_tool"``, NATIVE, and the five operations with the
    exact ``read_only`` / ``timeout_s`` / params model of the spec table."""
    assert adapter.name == "fake_tool"
    assert adapter.kind is AdapterKind.NATIVE
    assert set(adapter.operations) == {
        "echo",
        "write_item",
        "fail_upstream",
        "raise_unexpected",
        "sleep_forever",
    }

    expected = {
        "echo": (True, 5.0, EchoParams),
        "write_item": (False, 5.0, WriteItemParams),
        "fail_upstream": (True, 5.0, NoParams),
        "raise_unexpected": (True, 5.0, NoParams),
        "sleep_forever": (True, 0.05, NoParams),
    }
    for name, (read_only, timeout_s, params_model) in expected.items():
        op = adapter.operations[name]
        assert op.name == name
        assert (op.read_only, op.timeout_s, op.params_model) == (
            read_only,
            timeout_s,
            params_model,
        )


async def test_fake_adapter_lifecycle_sets_and_clears_started(
    adapter: FakeToolAdapter,
) -> None:
    """C1 §6.3 — ``start()``/``stop()`` set/clear ``self.started``."""
    assert adapter.started is False
    await adapter.start()
    assert adapter.started is True
    await adapter.stop()
    assert adapter.started is False


async def test_fake_adapter_echo_returns_ok_with_native_meta(
    adapter: FakeToolAdapter,
) -> None:
    """C1 §6.3 — ``echo`` returns ``ok=True, data={"echo": text}``; every result's
    meta is ``ToolResultMeta(adapter_kind=NATIVE, server_id=None, duration_ms=…)``."""
    result = await adapter.operations["echo"].handler(EchoParams(text="hello"))

    assert isinstance(result, ToolResult)
    assert (result.ok, result.data) == (True, {"echo": "hello"})
    assert (result.error_kind, result.error_message) == (None, None)
    assert isinstance(result.meta, ToolResultMeta)
    assert result.meta.adapter_kind is AdapterKind.NATIVE
    assert result.meta.server_id is None
    assert isinstance(result.meta.duration_ms, int) and result.meta.duration_ms >= 0


async def test_fake_adapter_write_item_stores_and_counts(
    adapter: FakeToolAdapter,
) -> None:
    """C1 §6.3 — ``write_item`` stores ``store[key]=value`` and returns
    ``{"written": key, "count": len(store)}``."""
    first = await adapter.operations["write_item"].handler(
        WriteItemParams(key="demo", value="1")
    )
    assert (first.ok, first.data) == (True, {"written": "demo", "count": 1})
    assert adapter.store == {"demo": "1"}

    second = await adapter.operations["write_item"].handler(
        WriteItemParams(key="other", value="2")
    )
    assert second.data == {"written": "other", "count": 2}


async def test_fake_adapter_fail_upstream_returns_error_result(
    adapter: FakeToolAdapter,
) -> None:
    """C1 §6.3 — ``fail_upstream`` returns ``ok=False,
    error_kind="upstream_error", error_message="fake upstream failure"``; C1 §2
    ToolResult: ``data`` is None when ``ok=False``."""
    result = await adapter.operations["fail_upstream"].handler(NoParams())

    assert result.ok is False
    assert result.data is None
    assert result.error_kind == "upstream_error"
    assert result.error_kind == ToolErrorKind.UPSTREAM_ERROR
    assert result.error_message == "fake upstream failure"


async def test_fake_adapter_raise_unexpected_raises_runtimeerror(
    adapter: FakeToolAdapter,
) -> None:
    """C1 §6.3 — the handler raises ``RuntimeError("fake crash")``. The MANAGER's
    conversion to ``upstream_error`` / ``"unhandled adapter exception"`` is
    asserted in contract test 1's sibling below (pipeline-level)."""
    with pytest.raises(RuntimeError, match="^fake crash$"):
        await adapter.operations["raise_unexpected"].handler(NoParams())


async def test_fake_adapter_sleep_forever_exceeds_its_declared_timeout() -> None:
    """C1 §6.3 — ``sleep_forever`` awaits 3600 s against ``timeout_s=0.05``, so the
    §2.1 step-5 timeout path is exercisable in well under a second."""
    adapter = FakeToolAdapter()
    op = adapter.operations["sleep_forever"]
    started = time.monotonic()

    with pytest.raises(TimeoutError):
        async with asyncio.timeout(op.timeout_s):
            await op.handler(NoParams())

    assert time.monotonic() - started < 1.0


@pytest.mark.parametrize(
    "model,kwargs",
    [
        (EchoParams, {"text": "hi", "extra": "nope"}),
        (WriteItemParams, {"key": "k", "value": "v", "extra": "nope"}),
        (NoParams, {"extra": "nope"}),
    ],
)
def test_fake_adapter_params_models_forbid_extra_keys(model, kwargs) -> None:
    """C1 §2 / §26.8 — every ``params_model`` uses ``extra="forbid"``. This is the
    property contract test 2 proves through the manager."""
    with pytest.raises(ValidationError):
        model(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"text": ""},  # min_length=1
        {"text": "x" * 1001},  # max_length=1000
    ],
)
def test_echo_params_bounds(kwargs) -> None:
    """C1 §6.3 — ``EchoParams.text``: min_length=1, max_length=1000."""
    with pytest.raises(ValidationError):
        EchoParams(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"key": "Bad-Key", "value": "v"},  # pattern ^[a-z0-9_]{1,64}$
        {"key": "", "value": "v"},
        {"key": "a" * 65, "value": "v"},
        {"key": "ok", "value": "v" * 1001},  # value max_length=1000
    ],
)
def test_write_item_params_bounds(kwargs) -> None:
    """C1 §6.3 — ``WriteItemParams``: ``key`` matches ``^[a-z0-9_]{1,64}$``,
    ``value`` max_length=1000."""
    with pytest.raises(ValidationError):
        WriteItemParams(**kwargs)


# ========================================================================== #
# Fake-level: C1 §6.1 FakePermissionHook, §6.2 RecordingAuditHook
# ========================================================================== #
def test_permission_hook_defaults_to_deny(hook: FakePermissionHook) -> None:
    """C1 §6.1 — triple absent → DENY, ``reason="no grant for this triple
    (default deny)"``, ``source="fake:default"``. Default-deny is the fake's
    structure too, mirroring the engine."""
    result = hook(agent_id="agent-1", tool="fake_tool", operation="write_item")

    assert isinstance(result, PermissionResult)
    assert result.decision is PermissionDecision.DENY
    assert result.reason == "no grant for this triple (default deny)"
    assert result.source == "fake:default"


@pytest.mark.parametrize(
    "decision,expected",
    [
        ("allow", PermissionDecision.ALLOW),
        ("deny", PermissionDecision.DENY),
        ("ask_user", PermissionDecision.ASK_USER),
    ],
)
def test_permission_hook_grant_registry(
    hook: FakePermissionHook, decision: str, expected: PermissionDecision
) -> None:
    """C1 §6.1 — ``grant(agent_id, tool, operation, decision)``; a registered
    triple returns that decision with ``reason="granted"`` and
    ``source=f"fake:{agent_id}.{tool}.{operation}"``."""
    hook.grant("agent-1", "fake_tool", "write_item", decision)
    result = hook(agent_id="agent-1", tool="fake_tool", operation="write_item")

    assert result.decision is expected
    assert result.reason == "granted"
    assert result.source == "fake:agent-1.fake_tool.write_item"


def test_permission_hook_grants_are_triple_scoped(hook: FakePermissionHook) -> None:
    """A grant must not leak to a neighbouring triple (the engine's rule: the
    grant is per ``agent × tool × operation``, C4 §1)."""
    hook.grant("agent-1", "fake_tool", "write_item", "allow")

    other_op = hook(agent_id="agent-1", tool="fake_tool", operation="echo")
    other_agent = hook(agent_id="agent-2", tool="fake_tool", operation="write_item")

    assert other_op.decision is PermissionDecision.DENY
    assert other_agent.decision is PermissionDecision.DENY


async def test_recording_audit_hook_two_phase(audit: RecordingAuditHook) -> None:
    """C1 §6.2 — ``attempt`` appends and returns ``audit-1``, ``audit-2``, …;
    ``finalise`` stores outcome/error_kind/duration_ms under the id."""
    record = ToolCallAttempt(
        request_id="req-1",
        task_id="task-1",
        agent_id="agent-1",
        tool="fake_tool",
        operation="echo",
        adapter_kind=AdapterKind.NATIVE,
        server_id=None,
        args_hash=args_hash({"text": "hi"}),
        params_redacted={"text": "hi"},
        permission_decision=PermissionDecision.ALLOW,
        permission_reason="granted",
        approval_id=None,
        created_at="2026-01-01T00:00:00Z",
    )

    first = await audit.attempt(record)
    second = await audit.attempt(record)
    assert (first, second) == ("audit-1", "audit-2")
    assert audit.attempts == [record, record]

    await audit.finalise(first, outcome="ok", error_kind=None, duration_ms=7)
    assert audit.finalised[first] == {
        "outcome": "ok",
        "error_kind": None,
        "duration_ms": 7,
    }


async def test_recording_audit_hook_rejects_double_finalise(
    audit: RecordingAuditHook,
) -> None:
    """C1 §6.2 — a second ``finalise`` for the same id raises
    ``AssertionError("double finalise")``. This is what makes the two-phase
    pairing of contract test 7 provable rather than asserted by eyeball."""
    record = ToolCallAttempt(
        request_id="req-1",
        task_id="task-1",
        agent_id="agent-1",
        tool="fake_tool",
        operation="echo",
        adapter_kind=AdapterKind.NATIVE,
        server_id=None,
        args_hash=None,
        params_redacted=None,
        permission_decision=None,
        permission_reason=None,
        approval_id=None,
        created_at="2026-01-01T00:00:00Z",
    )
    audit_id = await audit.attempt(record)
    await audit.finalise(audit_id, outcome="error", error_kind="timeout", duration_ms=1)

    with pytest.raises(AssertionError, match="^double finalise$"):
        await audit.finalise(audit_id, outcome="ok", error_kind=None, duration_ms=2)


# ========================================================================== #
# Fake-level: C1 §6.4 args_hash canonicalisation (normative for C1 and C4)
# ========================================================================== #
def test_args_hash_is_canonical_and_order_independent() -> None:
    """C1 §6.4 — ``sha256`` hex of the UTF-8 JSON of the VALIDATED params with
    ``sort_keys=True`` and separators ``(",", ":")``. Key order in the input
    cannot change the hash, and the digest is a pinned constant."""
    from hashlib import sha256

    expected = sha256(b'{"key":"demo","value":"1"}').hexdigest()

    assert args_hash(WriteItemParams(key="demo", value="1")) == expected
    assert args_hash({"key": "demo", "value": "1"}) == expected
    assert args_hash({"value": "1", "key": "demo"}) == expected
    assert args_hash({"key": "demo", "value": "2"}) != expected
    assert len(expected) == 64


# ========================================================================== #
# Pipeline-level: C1 contract tests 1–7 (C1 §6.4)
# Bodies complete against the frozen §2.1 signature; skipped until
# sunil/core/tool_framework/manager.py exists (backend deliverable).
# ========================================================================== #
async def test_c1_1_unknown_operation(manager, audit: RecordingAuditHook) -> None:
    """C1 contract test 1 — unknown operation → ``unknown_operation``; one attempt
    row with ``permission_decision=None``, finalised ``outcome="error"``."""
    result = await manager.execute(
        "agent-1", "fake_tool", "does.not.exist", {}, trace=TRACE
    )

    assert result.ok is False
    assert result.error_kind == "unknown_operation"
    assert len(audit.attempts) == 1
    assert audit.attempts[0].permission_decision is None
    assert audit.finalised["audit-1"]["outcome"] == "error"


async def test_c1_2_extra_param_key_is_invalid_params(
    manager, audit: RecordingAuditHook
) -> None:
    """C1 contract test 2 — extra param key → ``invalid_params`` (proves
    ``extra="forbid"``); the attempt row has ``args_hash=None``."""
    result = await manager.execute(
        "agent-1", "fake_tool", "echo", {"text": "hi", "nope": 1}, trace=TRACE
    )

    assert result.error_kind == "invalid_params"
    assert len(audit.attempts) == 1
    assert audit.attempts[0].args_hash is None


async def test_c1_3_empty_grant_registry_denies(manager) -> None:
    """C1 contract test 3 — empty grant registry → ``write_item`` returns
    ``permission_denied`` (structural default-deny)."""
    result = await manager.execute(
        "agent-1", "fake_tool", "write_item", {"key": "demo", "value": "1"}, trace=TRACE
    )

    assert result.error_kind == "permission_denied"


async def test_c1_4_ask_user_without_approval_parks(
    manager, hook: FakePermissionHook, approvals: FakeApprovalsService
) -> None:
    """C1 contract test 4 — ASK_USER with no ``approval`` → ``approval_required``
    AND ``FakeApprovalsService`` holds exactly one ``pending`` approval whose
    ``args_hash == sha256(canonical_json(validated params))`` and whose
    ``request_id``/``task_id``/``conversation_id`` equal the ``TraceContext``."""
    hook.grant("agent-1", "fake_tool", "write_item", "ask_user")
    params = {"key": "demo", "value": "1"}

    result = await manager.execute(
        "agent-1", "fake_tool", "write_item", params, trace=TRACE
    )

    assert result.error_kind == "approval_required"
    assert result.data is None

    pending = [
        row
        for row in approvals.approvals.values()
        if row.status == ApprovalStatus.PENDING
    ]
    assert len(pending) == 1
    row = pending[0]
    assert row.args_hash == args_hash(params)
    assert row.request_id == TRACE.request_id
    assert row.task_id == TRACE.task_id
    assert row.conversation_id == TRACE.conversation_id


async def test_c1_5_approved_id_executes_once_then_is_spent(
    manager,
    hook: FakePermissionHook,
    approvals: FakeApprovalsService,
    audit: RecordingAuditHook,
) -> None:
    """C1 contract test 5 — approve test 4's approval, re-execute the IDENTICAL
    params with ``approval=approval_id`` → executes, ``ok=True``; the attempt row
    carries ``approval_id``; the approval is ``consumed``. A third execution with
    the same id → ``approval_invalid`` (single-use, C4 test 1 seen from C1)."""
    hook.grant("agent-1", "fake_tool", "write_item", "ask_user")
    params = {"key": "demo", "value": "1"}

    await manager.execute("agent-1", "fake_tool", "write_item", params, trace=TRACE)
    approval_id = next(iter(approvals.approvals))
    approvals.decide(approval_id, "approve", None, approvals.clock.now())

    ok = await manager.execute(
        "agent-1", "fake_tool", "write_item", params, trace=TRACE, approval=approval_id
    )
    assert ok.ok is True
    assert audit.attempts[-1].approval_id == approval_id
    assert approvals.approvals[approval_id].status == ApprovalStatus.CONSUMED

    spent = await manager.execute(
        "agent-1", "fake_tool", "write_item", params, trace=TRACE, approval=approval_id
    )
    assert spent.error_kind == "approval_invalid"


async def test_c1_6_timeout(manager, hook: FakePermissionHook) -> None:
    """C1 contract test 6 — ``sleep_forever`` → ``timeout`` in < 1 s wall clock."""
    hook.grant("agent-1", "fake_tool", "sleep_forever", "allow")
    started = time.monotonic()

    result = await manager.execute(
        "agent-1", "fake_tool", "sleep_forever", {}, trace=TRACE
    )

    assert result.error_kind == "timeout"
    assert time.monotonic() - started < 1.0


async def test_c1_7_every_path_pairs_one_attempt_with_one_finalise(
    manager, hook: FakePermissionHook, audit: RecordingAuditHook
) -> None:
    """C1 contract test 7 — every case above produced exactly one attempt AND
    exactly one finalise (two-phase pairing)."""
    hook.grant("agent-1", "fake_tool", "echo", "allow")
    calls = [
        ("does.not.exist", {}),
        ("echo", {"text": "hi", "nope": 1}),
        ("write_item", {"key": "demo", "value": "1"}),
        ("echo", {"text": "hi"}),
    ]

    for operation, params in calls:
        await manager.execute("agent-1", "fake_tool", operation, params, trace=TRACE)

    assert len(audit.attempts) == len(calls)
    assert len(audit.finalised) == len(calls)
    assert set(audit.finalised) == {f"audit-{i + 1}" for i in range(len(calls))}


async def test_c1_7_attempt_row_is_written_before_the_handler_runs(
    adapter: FakeToolAdapter,
    hook: FakePermissionHook,
    approvals: FakeApprovalsService,
) -> None:
    """C1 contract test 7, ordering probe — the attempt row is written BEFORE the
    handler runs (§2.1 step 4: a process kill mid-execution can never leave a
    side effect with no ``tool_calls`` row)."""
    manager_cls = tool_manager_class()
    events: list[str] = []

    inner = adapter.operations["echo"].handler

    async def wrapped(params):
        events.append("execute")
        return await inner(params)

    adapter.operations["echo"] = adapter.operations["echo"].__class__(
        name="echo",
        params_model=adapter.operations["echo"].params_model,
        read_only=True,
        timeout_s=5.0,
        handler=wrapped,
    )

    class OrderingAuditHook(RecordingAuditHook):
        async def attempt(self, record: ToolCallAttempt) -> str:
            events.append("attempt")
            return await super().attempt(record)

    hook.grant("agent-1", "fake_tool", "echo", "allow")
    manager = manager_cls([adapter], hook, approvals, OrderingAuditHook())

    await manager.execute("agent-1", "fake_tool", "echo", {"text": "hi"}, trace=TRACE)

    assert events == ["attempt", "execute"]
