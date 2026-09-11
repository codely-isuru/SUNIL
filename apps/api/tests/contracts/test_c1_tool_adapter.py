"""C1 — Tool Adapter contract suite.

Source of truth: ``docs/contracts/C1-tool-adapter.md`` **v1.1.1** (FROZEN
2026-09-10; ParkContext-guard patch 2026-09-11).

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
from inspect import signature

import pytest
from pydantic import ValidationError

from sunil.core.approvals.base import ApprovalBinding, ApprovalStatus
from sunil.core.tool_framework.base import (
    AdapterKind,
    ParkContext,
    PermissionDecision,
    PermissionResult,
    ToolCallAttempt,
    ToolErrorKind,
    ToolManagerProtocol,
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
def park_ctx() -> ParkContext:
    """C1 §6.4's fixture, verbatim (v1.1.0): the caller-supplied park material
    every FIRST attempt must carry, non-empty on both fields.

    A fixture rather than a module constant on purpose — ``continuation`` is a
    mutable dict inside a frozen dataclass, so a shared instance would let one
    test's edit reach the next (the F1 lesson, one seam over)."""
    return ParkContext(
        continuation={"plan_id": "plan-1", "cursor": "step_1"},
        summary="fake_tool.write_item: key=demo",
    )


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
async def test_c1_1_unknown_tool_and_unknown_operation(
    manager, audit: RecordingAuditHook, park_ctx: ParkContext
) -> None:
    """C1 contract test 1 (v1.1.0, F4) — two calls, both ``unknown_operation``,
    probing BOTH sides of ``ToolResultMeta.adapter_kind``:

    * unknown TOOL → ``meta.adapter_kind is None`` — no adapter was ever
      resolved, so a kind on that row would be a fabricated fact on the
      ``tool_calls`` audit trail (the backend probe wrote ``NATIVE``: F4);
    * unknown OPERATION on the known ``fake_tool`` → ``AdapterKind.NATIVE``, the
      resolved adapter's real kind.

    Each call: one attempt row with ``permission_decision=None`` and the matching
    ``adapter_kind``, finalised ``outcome="error"``.
    """
    unknown_tool = await manager.execute(
        "agent-1", "no_such_tool", "echo", {}, trace=TRACE, park_context=park_ctx
    )

    assert unknown_tool.ok is False
    assert unknown_tool.error_kind == "unknown_operation"
    assert unknown_tool.meta.adapter_kind is None
    assert unknown_tool.meta.server_id is None

    unknown_operation = await manager.execute(
        "agent-1", "fake_tool", "does.not.exist", {}, trace=TRACE, park_context=park_ctx
    )

    assert unknown_operation.error_kind == "unknown_operation"
    assert unknown_operation.meta.adapter_kind == AdapterKind.NATIVE

    assert len(audit.attempts) == 2
    assert [row.adapter_kind for row in audit.attempts] == [None, AdapterKind.NATIVE]
    assert [row.permission_decision for row in audit.attempts] == [None, None]
    assert audit.finalised["audit-1"]["outcome"] == "error"
    assert audit.finalised["audit-2"]["outcome"] == "error"


async def test_c1_2_extra_param_key_is_invalid_params(
    manager, audit: RecordingAuditHook, park_ctx: ParkContext
) -> None:
    """C1 contract test 2 — extra param key → ``invalid_params`` (proves
    ``extra="forbid"``); the attempt row has ``args_hash=None``."""
    result = await manager.execute(
        "agent-1",
        "fake_tool",
        "echo",
        {"text": "hi", "nope": 1},
        trace=TRACE,
        park_context=park_ctx,
    )

    assert result.error_kind == "invalid_params"
    assert len(audit.attempts) == 1
    assert audit.attempts[0].args_hash is None


async def test_c1_3_empty_grant_registry_denies(
    manager, park_ctx: ParkContext
) -> None:
    """C1 contract test 3 — empty grant registry → ``write_item`` returns
    ``permission_denied`` (structural default-deny)."""
    result = await manager.execute(
        "agent-1",
        "fake_tool",
        "write_item",
        {"key": "demo", "value": "1"},
        trace=TRACE,
        park_context=park_ctx,
    )

    assert result.error_kind == "permission_denied"


async def test_c1_4_ask_user_without_approval_parks(
    manager,
    hook: FakePermissionHook,
    approvals: FakeApprovalsService,
    park_ctx: ParkContext,
) -> None:
    """C1 contract test 4 — ASK_USER with no ``approval`` → ``approval_required``
    AND ``FakeApprovalsService`` holds exactly one ``pending`` approval whose
    ``args_hash == sha256(canonical_json(validated params))`` and whose
    ``request_id``/``task_id``/``conversation_id`` equal the ``TraceContext``.

    REQUIRED (v1.1.0, F3): the retained ``ParkRequest`` carries
    ``continuation``/``summary`` equal BY VALUE to the caller's non-empty
    ``park_ctx``. The backend probe parked ``continuation={}`` plus a synthesised
    summary — a never-resumable approval — and the v1.0.0 version of this test
    passed, because it asserted only ``args_hash`` and the trace ids. Equality
    against the caller's own fixture is what makes that impossible: a manager
    that synthesises, defaults or empties either field fails here.
    """
    hook.grant("agent-1", "fake_tool", "write_item", "ask_user")
    params = {"key": "demo", "value": "1"}

    result = await manager.execute(
        "agent-1", "fake_tool", "write_item", params, trace=TRACE, park_context=park_ctx
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

    # C4 §6 behaviour 1 (v1.1.0) — the fake retains the composed ParkRequest.
    parked = approvals.parked[row.id]
    assert parked.continuation == park_ctx.continuation
    assert parked.summary == park_ctx.summary
    assert parked.continuation == {"plan_id": "plan-1", "cursor": "step_1"}
    assert parked.summary == "fake_tool.write_item: key=demo"
    # ...and the manager computed the rest itself (one composer, one hasher).
    assert parked.args_hash == args_hash(params)
    assert (parked.agent_id, parked.tool, parked.operation) == (
        "agent-1",
        "fake_tool",
        "write_item",
    )


async def test_c1_5_approved_id_executes_once_then_is_spent(
    manager,
    hook: FakePermissionHook,
    approvals: FakeApprovalsService,
    audit: RecordingAuditHook,
    park_ctx: ParkContext,
) -> None:
    """C1 contract test 5 — approve test 4's approval, re-execute the IDENTICAL
    params with ``approval=approval_id`` → executes, ``ok=True``; the attempt row
    carries ``approval_id``; the approval is ``consumed``. A third execution with
    the same id → ``approval_invalid`` (single-use, C4 test 1 seen from C1).

    The two continuation calls pass NO ``park_context`` (v1.1.0, §2.1): a call
    carrying an ``approval`` never parks — a consume failure early-exits
    ``approval_invalid`` — so the precondition is a first-attempt rule only, and
    a manager that demanded it on continuations would break every resume."""
    hook.grant("agent-1", "fake_tool", "write_item", "ask_user")
    params = {"key": "demo", "value": "1"}

    await manager.execute(
        "agent-1", "fake_tool", "write_item", params, trace=TRACE, park_context=park_ctx
    )
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


async def test_c1_6_timeout(
    manager, hook: FakePermissionHook, park_ctx: ParkContext
) -> None:
    """C1 contract test 6 — ``sleep_forever`` → ``timeout`` in < 1 s wall clock."""
    hook.grant("agent-1", "fake_tool", "sleep_forever", "allow")
    started = time.monotonic()

    result = await manager.execute(
        "agent-1", "fake_tool", "sleep_forever", {}, trace=TRACE, park_context=park_ctx
    )

    assert result.error_kind == "timeout"
    assert time.monotonic() - started < 1.0


async def test_c1_7_every_path_pairs_one_attempt_with_one_finalise(
    manager,
    hook: FakePermissionHook,
    audit: RecordingAuditHook,
    park_ctx: ParkContext,
) -> None:
    """C1 contract test 7 (v1.1.0 wording) — every ``execute`` CALL above
    produced exactly one attempt AND exactly one finalise (two-phase pairing).
    Per CALL, not per test: test 1 makes two, and test 8's precondition failure
    is excluded because it never enters the pipeline."""
    hook.grant("agent-1", "fake_tool", "echo", "allow")
    calls = [
        ("does.not.exist", {}),
        ("echo", {"text": "hi", "nope": 1}),
        ("write_item", {"key": "demo", "value": "1"}),
        ("echo", {"text": "hi"}),
    ]

    for operation, params in calls:
        await manager.execute(
            "agent-1",
            "fake_tool",
            operation,
            params,
            trace=TRACE,
            park_context=park_ctx,
        )

    assert len(audit.attempts) == len(calls)
    assert len(audit.finalised) == len(calls)
    assert set(audit.finalised) == {f"audit-{i + 1}" for i in range(len(calls))}


async def test_c1_7_attempt_row_is_written_before_the_handler_runs(
    adapter: FakeToolAdapter,
    hook: FakePermissionHook,
    approvals: FakeApprovalsService,
    park_ctx: ParkContext,
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

    await manager.execute(
        "agent-1",
        "fake_tool",
        "echo",
        {"text": "hi"},
        trace=TRACE,
        park_context=park_ctx,
    )

    assert events == ["attempt", "execute"]


# ========================================================================== #
# Pipeline-level: C1 contract test 8 (v1.1.0, F3) — the park_context precondition
# ========================================================================== #
async def test_c1_8_first_attempt_without_park_context_raises(
    manager, hook: FakePermissionHook, approvals: FakeApprovalsService,
    audit: RecordingAuditHook,
) -> None:
    """C1 contract test 8 (v1.1.0, F3) — a FIRST attempt (``approval=None``) with
    ``park_context`` omitted raises ``TypeError`` **before any pipeline step**:
    afterwards the approvals fake holds zero approvals and the audit hook
    recorded zero attempts.

    It is a caller contract violation of the same class as constructing the
    manager without an audit hook — not a pipeline outcome — so it must not mint
    an attempt row, and it is excluded from test 7's pairing accounting. This is
    the precondition that makes a non-resumable park inexpressible: every V2 tool
    call originates from a validated plan step, so the orchestrator always holds
    both values (§2.1).
    """
    hook.grant("agent-1", "fake_tool", "write_item", "ask_user")

    with pytest.raises(TypeError):
        await manager.execute(
            "agent-1", "fake_tool", "write_item", {"key": "demo", "value": "1"},
            trace=TRACE,
        )

    assert approvals.approvals == {}
    assert approvals.parked == {}
    assert audit.attempts == []
    assert audit.finalised == {}


async def test_c1_8_explicit_none_park_context_is_the_same_violation(
    manager, hook: FakePermissionHook, audit: RecordingAuditHook
) -> None:
    """§2.1 — "``park_context=None`` (or omitted)": passing the default
    explicitly is the same caller violation, so a call site cannot satisfy the
    precondition by naming the parameter and handing over nothing."""
    hook.grant("agent-1", "fake_tool", "echo", "allow")

    with pytest.raises(TypeError):
        await manager.execute(
            "agent-1", "fake_tool", "echo", {"text": "hi"},
            trace=TRACE, park_context=None,
        )

    assert audit.attempts == []


# ========================================================================== #
# Construction-level: C1 contract test 9 (v1.1.1) — ParkContext is its own guard
# ========================================================================== #
def test_c1_9_empty_park_context_is_unconstructible(park_ctx: ParkContext) -> None:
    """C1 contract test 9 (v1.1.1, §2.2) — an invalid ``ParkContext`` is
    **unconstructible**, not merely forbidden: ``ValueError`` on an empty
    ``continuation``, an empty or whitespace-only ``summary``, or a ``summary``
    over 500 characters.

    Why this is a construction probe and not a pipeline one: v1.1.0 pinned only
    the MISSING case (test 8, ``TypeError`` before step 1), so an
    empty-but-present ``ParkContext`` satisfied §2.1's non-None precondition,
    reached step 3 and took an unhandled ``pydantic.ValidationError`` out of
    ``approvals.park(...)`` — a raise from ``execute`` with no kind in §4's closed
    error set, an unfinalised attempt row behind it, and a never-resumable
    approval if it had persisted (C4 §1 restart safety). v1.1.1 moves the
    rejection to the constructor, in the orchestrator, where the plan cursor
    actually lives. So: no manager, no fakes, no import guard — this runs green
    the moment the guard lands and stays green through Phase 2.

    Each probe pins the SPECIFIC guard that must fire (``match=``): a bare
    ``pytest.raises(ValueError)`` would pass on any of the three, so a
    transcription that checked ``continuation`` twice and ``summary`` never
    would look correct.
    """
    valid_cont = {"plan_id": "plan-1", "cursor": "step_1"}
    valid_summary = "fake_tool.write_item: key=demo"

    with pytest.raises(ValueError, match="continuation must be non-empty"):
        ParkContext(continuation={}, summary=valid_summary)

    with pytest.raises(ValueError, match="summary must be non-empty"):
        ParkContext(continuation=valid_cont, summary="")

    # C4 §4's Field(min_length=1) admits "   "; the caller-side tightening does
    # not — a blank approval card is the same never-actionable failure class.
    with pytest.raises(ValueError, match="summary must be non-empty"):
        ParkContext(continuation=valid_cont, summary="   ")

    with pytest.raises(ValueError, match="summary must be at most 500 characters"):
        ParkContext(continuation=valid_cont, summary="x" * 501)

    # Both legal constructions. 500 is the boundary C4 §4's max_length=500
    # mirrors: inclusive, so anything constructible here is valid there.
    boundary = ParkContext(continuation=valid_cont, summary="x" * 500)
    assert len(boundary.summary) == 500

    # §6.4's own fixture still constructs — the PATCH classification's claim that
    # no conforming caller can observe the change, asserted rather than assumed.
    assert park_ctx.continuation == valid_cont
    assert park_ctx.summary == valid_summary


# ========================================================================== #
# Pipeline-level: §2.1 step 3 — an approval id under an ALLOW grant is IGNORED,
# never consumed (QA finding F6: normative, previously untested)
# ========================================================================== #
async def test_c1_allow_grant_ignores_an_approval_id_without_burning_it(
    manager,
    hook: FakePermissionHook,
    approvals: FakeApprovalsService,
    park_ctx: ParkContext,
) -> None:
    """C1 §2.1 step 3 — under an ``ALLOW`` grant the pipeline executes and the
    supplied ``approval`` id is **ignored, not consumed**.

    Why this matters enough to pin: a manager that consumed opportunistically
    (or "for tidiness") would silently burn a single-use, still-valid approval
    the owner granted for a DIFFERENT call — the approval's one execution is
    spent on a call that never needed it, and the real continuation then fails
    ``approval_invalid`` with nothing to show the owner. The bug is invisible on
    the happy path: the call succeeds either way. So the test asserts the
    approval is still there, still ``approved``, and still consumable
    afterwards.
    """
    params = {"key": "demo", "value": "1"}
    hook.grant("agent-1", "fake_tool", "write_item", "ask_user")
    await manager.execute(
        "agent-1", "fake_tool", "write_item", params, trace=TRACE, park_context=park_ctx
    )
    approval_id = next(iter(approvals.approvals))
    approvals.decide(approval_id, "approve", None, approvals.clock.now())

    # The owner widens the grant (or the matrix reloads) before the resume.
    hook.grant("agent-1", "fake_tool", "write_item", "allow")
    result = await manager.execute(
        "agent-1", "fake_tool", "write_item", params, trace=TRACE,
        approval=approval_id,
    )

    assert result.ok is True
    assert approvals.approvals[approval_id].status == ApprovalStatus.APPROVED
    assert approvals.approvals[approval_id].consumed_at is None

    # Still spendable — the ALLOW path did not eat the grant.
    spend = await approvals.consume(
        approval_id,
        binding=ApprovalBinding(
            agent_id="agent-1",
            tool="fake_tool",
            operation="write_item",
            args_hash=args_hash(params),
        ),
    )
    assert (spend.ok, spend.reason) == (True, "consumed")


# ========================================================================== #
# Fake-level: the frozen SHAPES this suite is written against (v1.1.0)
# ========================================================================== #
def test_c1_tool_manager_protocol_execute_is_the_v1_1_0_signature() -> None:
    """C1 §2.1 — ``execute``'s parameters, in order, with ``trace``/``approval``/
    ``park_context`` keyword-only and the two optionals defaulting to ``None``.

    The transcription is the only place this shape is machine-readable before
    ``manager.py`` exists, so it is pinned: dropping ``park_context`` or making
    it positional would silently un-break the F3 fix.
    """
    execute = signature(ToolManagerProtocol.execute)

    assert list(execute.parameters) == [
        "self",
        "agent_id",
        "tool",
        "operation",
        "params",
        "trace",
        "approval",
        "park_context",
    ]
    for name in ("trace", "approval", "park_context"):
        assert execute.parameters[name].kind.name == "KEYWORD_ONLY"
    assert execute.parameters["trace"].default is execute.empty
    assert execute.parameters["approval"].default is None
    assert execute.parameters["park_context"].default is None
    assert execute.parameters["park_context"].annotation == "ParkContext | None"


def test_c1_tool_manager_protocol_init_is_the_four_seam_shape() -> None:
    """C1 §2.1 — the manager is constructed with exactly the four seams
    (adapters, permission hook, approvals, audit hook), in that order.

    Recorded nit F7: a Protocol's ``__init__`` binds nothing structurally — a
    type checker will not reject an implementation that constructs differently.
    So the transcription's value is documentary, and this test is what keeps the
    document honest: the shape cannot drift inside ``base.py`` unnoticed. The
    load-bearing property behind it — no default audit hook, so "forgot to
    audit" is not an expressible program — is asserted here as the absence of
    defaults.
    """
    init = signature(ToolManagerProtocol.__init__)

    assert list(init.parameters) == [
        "self",
        "adapters",
        "permission_hook",
        "approvals",
        "audit_hook",
    ]
    assert all(
        parameter.default is init.empty for parameter in init.parameters.values()
    )


def test_c1_adapter_kind_is_optional_on_both_record_types() -> None:
    """C1 §2 (v1.1.0, F4) — ``ToolResultMeta.adapter_kind`` and
    ``ToolCallAttempt.adapter_kind`` carry the SAME ``AdapterKind | None``
    convention: None iff the tool itself was unknown.

    Asserted on the annotations because these are plain frozen dataclasses —
    nothing at runtime would reject ``adapter_kind=NATIVE`` on a no-adapter exit,
    which is exactly the lie the probe was forced to write. The annotation is
    therefore the artefact under test.
    """
    assert ToolResultMeta.__annotations__["adapter_kind"] == "AdapterKind | None"
    assert ToolCallAttempt.__annotations__["adapter_kind"] == "AdapterKind | None"
    assert ToolResultMeta.__annotations__["server_id"] == "str | None"
    # Constructible with None — the unknown-TOOL exit's meta (C1 §6.3).
    meta = ToolResultMeta(adapter_kind=None, server_id=None, duration_ms=0)
    assert meta.adapter_kind is None


def test_c1_tool_error_kind_membership_matches_section_4() -> None:
    """C1 §4 — the closed error set, member for member.

    Recorded nit F9: ``ToolErrorKind`` is a QA-invented public symbol (the
    contract types ``error_kind`` as ``str | None`` and gives the values in a
    table). It stays, because a closed set that only exists in prose cannot be
    checked — but it must never become a SECOND source of truth, so its
    membership is pinned to §4's table verbatim and its values are asserted to
    be the exact strings the table uses.
    """
    assert {kind.value for kind in ToolErrorKind} == {
        "unknown_operation",
        "invalid_params",
        "permission_denied",
        "approval_required",
        "approval_invalid",
        "timeout",
        "upstream_error",
        "transport_error",
    }
    assert len(ToolErrorKind) == 8
    # StrEnum members ARE str, so either form satisfies the frozen field type.
    assert ToolErrorKind.TIMEOUT == "timeout"
