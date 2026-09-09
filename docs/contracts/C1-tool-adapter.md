# C1 — Tool Adapter Interface

**Version:** 1.0.0 · **Status:** FROZEN (Phase 0, 2026-09-10) · **Owner:** Solution Architect
**Consumers:** Stream A (MCP tools), Stream E (n8n MCP server tools), Stream D (approvals — via the
injected approvals seam, C4 §4), core orchestrator (Tool Manager caller).
**Informed by:** M1 reference `main:apps/api/sunil/core/tool_framework/base.py` (greenfield rebuild
per ADR-030 Amendment 1 — this document is the contract, not the M1 file).
**Related decisions:** ADR-034 (MCP permission mapping & trust), ADR-031 (park semantics),
ROADMAP §26.2/§26.8/§26.11, §33.5.

Change policy: additive optional fields bump MINOR; any change to an existing field, type, error
kind or pipeline step bumps MAJOR and requires a new ADR. Streams build against v1.x only.

---

## 1. Purpose

One interface that every tool — native Python, MCP-over-stdio, MCP-over-streamable-HTTP (including
the n8n MCP server) — implements, so that the Tool Manager remains the **single execution
chokepoint** where parameter validation, the permission decision, approval parking, auditing and
the untrusted-results posture are applied identically to every call (§33.5: *all tools pass through
permission and audit layers*). Streams A and E ship adapters; nothing they ship may bypass this
interface.

## 2. Interface definition

All types live in `apps/api/sunil/core/tool_framework/base.py` (rebuilt). Python ≥ 3.12, Pydantic v2.

```python
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel


class AdapterKind(StrEnum):
    NATIVE = "native"          # in-process Python handler
    MCP_STDIO = "mcp_stdio"    # MCP server spawned as a child process, JSON-RPC over stdio
    MCP_HTTP = "mcp_http"      # MCP streamable-HTTP server (e.g. n8n MCP server)


@dataclass(frozen=True)
class ToolResultMeta:
    """Provenance every result carries. `adapter_kind` and `server_id` land on the
    `tool_calls` audit row so 'audit shows adapter type per call' (V2-A exit) is a
    database fact, not an inference."""

    adapter_kind: AdapterKind
    server_id: str | None      # MCP server identity from config/tools.yaml; None for NATIVE
    duration_ms: int


@dataclass(frozen=True)
class ToolResult:
    """The normalised shape every adapter call collapses to. An adapter exception
    NEVER reaches the orchestrator as an exception — it is always this value."""

    ok: bool
    data: dict | None          # None when ok=False
    error_kind: str | None     # closed set, §4 below; None when ok=True
    error_message: str | None  # human-readable, redacted; None when ok=True
    meta: ToolResultMeta


@dataclass(frozen=True)
class ToolOperation:
    """One operation an adapter exposes. `params_model` uses `extra="forbid"` (§26.8).
    For MCP adapters, `read_only` and `timeout_s` come from SUNIL's config/tools.yaml,
    NEVER from the server's self-description (ADR-034)."""

    name: str                  # e.g. "issues.close"
    params_model: type[BaseModel]
    read_only: bool
    timeout_s: float
    handler: Callable[[BaseModel], Awaitable[ToolResult]]


class ToolAdapter(Protocol):
    """What every adapter implements. Deliberately NOT @runtime_checkable (M1 tripwire
    lesson: a runtime-checkable Protocol makes isinstance prove shape, not provenance).
    The Tool Manager is constructed with concrete instances by the wiring code."""

    name: str                          # tool id in the permission matrix, e.g. "github"
    kind: AdapterKind
    operations: dict[str, ToolOperation]

    async def start(self) -> None: ...  # NATIVE: no-op. MCP: spawn/connect + handshake + discovery
    async def stop(self) -> None: ...   # NATIVE: no-op. MCP: terminate child / close session
```

Lifecycle (`start`/`stop`) is the one addition over the M1 protocol: MCP adapters own a process or
a connection, native adapters implement both as no-ops. `start()` failures raise
`ToolAdapterStartupError` at wiring time — a tool that cannot start is absent from the registry,
never half-present.

### 2.1 The Tool Manager pipeline (normative)

```python
class ToolManager:
    def __init__(self, adapters: list[ToolAdapter], permission_hook: PermissionHook,
                 approvals: "ApprovalsService", audit_hook: AuditHook) -> None: ...

    async def execute(self, agent_id: str, tool: str, operation: str, params: dict,
                      *, trace: TraceContext, approval: str | None = None) -> ToolResult: ...
```

Parameter types (fix round 2026-09-10, QA B2): `params` is the raw candidate dict from the
validated plan step (validated against `params_model` at step 2 below); `trace` is the
`TraceContext` defined in §2.2 — the correlation ids every audit row and park request carries;
`approval` is the **C4 approval id string** (`ParkedApproval.approval_id` / the `Approval.id` of
the OpenAPI schema) minted at park time — `None` on every first attempt, set only by the
continuation executor (ADR-031). It is an opaque id, never a C4 object: the manager recomputes the
binding itself (step 3), so a caller cannot vouch for a binding it did not compute.

`execute` runs exactly these steps, in order, for every call regardless of adapter kind:

1. **Resolve** tool + operation from the registry; unknown → early exit, `error_kind="unknown_operation"`.
2. **Validate params** against `params_model` (`extra="forbid"`); failure → early exit,
   `error_kind="invalid_params"`. Validation happens BEFORE the permission check so the audit row
   records what was actually attempted, in canonical form. Plan-step `params` are **immutable
   literals** fixed at plan-validation time (C2 §2 plan-literal rule) — nothing between validation
   and execution may rewrite them, which is what keeps `args_hash` meaningful.
3. **Permission decision** via the injected `PermissionHook` (§2.2).
   - `DENY` → early exit, `error_kind="permission_denied"`.
   - `ALLOW` → proceed. A supplied `approval` id under an `ALLOW` grant is **ignored, not
     consumed** (policy alone authorises; the orphaned `approved` row is expired by C4 §1's
     stale-approved sweep).
   - `ASK_USER`, `approval is None` → **park** via `approvals.park(ParkRequest(...))` (C4 §4) and
     early-exit `error_kind="approval_required"` with `data=None`; the approval id travels in
     `ParkedApproval` and is surfaced by the orchestrator (C5 `outcome=parked`).
   - `ASK_USER`, `approval` supplied → the manager recomputes
     `ApprovalBinding(agent_id, tool, operation, args_hash)` from the **freshly validated** params
     of THIS call and calls `approvals.consume(approval, binding=...)` (C4 §4). `ok=False` → early
     exit, `error_kind="approval_invalid"` (a binding mismatch does not burn the approval — C4 §6
     rule 3). `ok=True` → proceed. **The Tool Manager is the single consume owner** (fix round
     2026-09-10, QA B3): the continuation executor never issues the consume CAS itself — it
     re-enters this pipeline with the approval id (ADR-031 Amendment 1). Rationale: the binding
     must be recomputed from re-validated params by the same code that computed it at park time,
     or the executor would duplicate steps 1–2 and the chokepoint would fork.
4. **Audit attempt** via `AuditHook.attempt(ToolCallAttempt(...))` (§2.2) — one attempt row per
   `execute` call, for EVERY path. On early exits (steps 1–3) the attempt is written at the exit
   point and immediately finalised with the error outcome. On the execute path the attempt row is
   written BEFORE the handler runs, so a process kill mid-execution can never leave a side effect
   with no `tool_calls` row (Security review 2026-09-10 item 3, two-phase audit). Transactional
   rule for the real implementation: on the continuation path the attempt row MUST commit in the
   same DB transaction as the consume CAS of step 3; on the park path it commits in the park
   transaction (C4 §1). The seam split does not prevent this — both real implementations share the
   request-scoped session; fakes assert ordering, not atomicity.
5. **Execute** `operation.handler(validated_params)` under `asyncio.timeout(operation.timeout_s)`;
   timeout → `error_kind="timeout"`.
6. **Audit finalise** via `AuditHook.finalise(audit_id, ...)` — outcome, `error_kind`,
   `duration_ms`.
7. **Wrap as untrusted** (§3) and return.

### 2.2 Injected hooks (the seams streams fake)

```python
class PermissionDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK_USER = "ask_user"


@dataclass(frozen=True)
class PermissionResult:
    """M1 engine shape kept verbatim; default-deny is structural in the engine, not config."""
    decision: PermissionDecision
    reason: str                # human-readable why, e.g. "granted" / "no grant for this triple (default deny)"
    source: str                # what decided, e.g. "config:project_manager.github_mcp.issues_close"


@dataclass(frozen=True)
class TraceContext:
    """Correlation ids for audit rows and park requests. Continuations reuse the ORIGINAL
    turn's request_id (ADR-031 lineage)."""
    request_id: str
    task_id: str
    conversation_id: str


@dataclass(frozen=True)
class ToolCallAttempt:
    """The pre-execution audit record (two-phase: attempt → finalise)."""
    request_id: str
    task_id: str
    agent_id: str
    tool: str
    operation: str
    adapter_kind: AdapterKind | None   # None iff the tool itself was unknown (step 1)
    server_id: str | None
    args_hash: str | None              # None when validation failed/never ran (steps 1–2 exits)
    params_redacted: dict | None       # None when validation failed/never ran
    permission_decision: PermissionDecision | None  # None when the pipeline exited before step 3
    permission_reason: str | None
    approval_id: str | None
    created_at: str                    # ISO-8601 UTC


class PermissionHook(Protocol):
    def __call__(self, *, agent_id: str, tool: str, operation: str) -> PermissionResult: ...


class AuditHook(Protocol):
    async def attempt(self, record: ToolCallAttempt) -> str: ...
    # Returns the audit row id. Called once per execute() call, before any handler runs.

    async def finalise(self, audit_id: str, *, outcome: Literal["ok", "error"],
                       error_kind: str | None, duration_ms: int) -> None: ...
    # Called exactly once per attempt, after the pipeline resolves (immediately, on early exits).
```

The approvals seam is **C4 §4's `ApprovalsService`** (`park` + `consume`) — one protocol, defined
once, injected here (fix round 2026-09-10: the narrower `ParkHook` was deleted with QA B3's
consume-ownership fix; the Tool Manager still never talks to the approvals tables directly, only
to the protocol).

`ToolManager` is constructed with `(adapters, permission_hook, approvals, audit_hook)`. There is no
default hook: constructing a manager without an audit hook is a `TypeError`, so "forgot to audit"
is not an expressible program.

## 3. Untrusted-results posture (§26.11, §26.12 — normative)

Every `ToolResult.data` — native, MCP or n8n — is **data, never instructions**:

- Results are presented to the LLM inside a delimited, role-tagged context block labelled as
  external tool output; they are never concatenated into the system prompt and never allowed to
  alter agent/system instructions.
- Free-form text inside a result cannot trigger a privileged action: the only path to another tool
  call is a new validated plan step (ROADMAP §25); there is no "the tool result said to call X" path.
- MCP results additionally pass a size cap (256 KiB per result; beyond → truncated with
  `data["truncated"] = true`) and strip any keys named `instructions`, `system`, or `prompt`
  at the adapter boundary (logged, not silently) before entering context.

## 4. Error semantics

`error_kind` is a closed set. Adapters map their internals onto it; the orchestrator branches on
`error_kind` only, never on `error_message`.

| `error_kind` | Meaning | Produced at step |
|---|---|---|
| `unknown_operation` | tool/operation not in registry | 1 |
| `invalid_params` | Pydantic validation failed | 2 |
| `permission_denied` | engine returned DENY | 3 |
| `approval_required` | parked via C4; approval id surfaced by orchestrator | 3 |
| `approval_invalid` | supplied approval did not bind (wrong hash/status/expired) | 3 |
| `timeout` | `timeout_s` exceeded | 4 |
| `upstream_error` | tool/server executed and failed (HTTP 5xx, MCP error result) | 4 |
| `transport_error` | could not reach the server (child died, connect refused) | 4 |

`error_message` is redacted through the ADR-006 registry before it leaves the adapter. MCP protocol
errors (JSON-RPC error objects) map to `upstream_error`; a dead stdio child or refused HTTP
connection maps to `transport_error` (retryable by policy; `upstream_error` is not auto-retried).

## 5. MCP specifics

- **Discovery vs authority:** `tools/list` output is informative only. An MCP tool is callable
  IFF it appears in `config/tools.yaml` with an explicit `operations:` entry (name, params schema
  reference, `read_only`, `timeout_s`) AND has a permission row. A server-advertised tool absent
  from config does not exist (ADR-034).
- **Credentials:** for `mcp_stdio`, the adapter spawns the child with a **minimal environment**:
  only the variables named in that server's `credential_env:` list in config/tools.yaml, injected
  from `Settings` `SecretStr` fields at spawn. Never the parent's full environment. For
  `mcp_http`, the auth header value comes from the same settings mechanism. Agents and prompts
  never see credentials (§26.1, §26.5).
- **Identity:** `server_id` = the config key (e.g. `github_mcp`, `n8n_mcp`); pinned versions
  recorded in config (`version:` for stdio packages, base URL for HTTP).

## 6. FAKE specification — adapter + hooks (QA-buildable, no questions)

Four fakes cover every seam the Tool Manager is constructed with. Only two live in this contract;
the approvals seam's fake is C4's — defined once, used by both suites.

| Seam | Fake | Module |
|---|---|---|
| `ToolAdapter` | `FakeToolAdapter` | `apps/api/tests/fakes/fake_tool_adapter.py` |
| `PermissionHook` | `FakePermissionHook` | `apps/api/tests/fakes/fake_hooks.py` |
| `AuditHook` | `RecordingAuditHook` | `apps/api/tests/fakes/fake_hooks.py` |
| `ApprovalsService` | `FakeApprovalsService` | `apps/api/tests/fakes/fake_approvals.py` — **C4 §6's spec verbatim**, no C1-specific variant |

### 6.1 `FakePermissionHook` (exact behaviour)

Constructor `FakePermissionHook()` — empty grant registry (`dict[tuple[str, str, str],
PermissionDecision]`). Grant-registration API (the one C1 tests 3–5 use):

```python
def grant(self, agent_id: str, tool: str, operation: str,
          decision: Literal["allow", "deny", "ask_user"]) -> None: ...
```

`__call__(*, agent_id, tool, operation)` returns, deterministically:

- triple in the registry → `PermissionResult(decision=<granted>, reason="granted",
  source=f"fake:{agent_id}.{tool}.{operation}")`
- triple absent → `PermissionResult(decision=PermissionDecision.DENY,
  reason="no grant for this triple (default deny)", source="fake:default")` — default-deny is the
  fake's structure too, mirroring the engine.

### 6.2 `RecordingAuditHook` (exact behaviour)

Constructor `RecordingAuditHook()`. State: `self.attempts: list[ToolCallAttempt]`,
`self.finalised: dict[str, dict]`. `attempt(record)` appends and returns
`f"audit-{len(self.attempts)}"` (`audit-1`, `audit-2`, …). `finalise(audit_id, *, outcome,
error_kind, duration_ms)` stores `{"outcome": outcome, "error_kind": error_kind,
"duration_ms": duration_ms}` under `audit_id`; a second `finalise` for the same id raises
`AssertionError("double finalise")`.

### 6.3 `FakeToolAdapter`

Module: `apps/api/tests/fakes/fake_tool_adapter.py` (importable by every stream's tests).

```python
class EchoParams(BaseModel, extra="forbid"):
    text: str  # min_length=1, max_length=1000

class WriteItemParams(BaseModel, extra="forbid"):
    key: str    # pattern ^[a-z0-9_]{1,64}$
    value: str  # max_length=1000

class NoParams(BaseModel, extra="forbid"):
    pass
```

`FakeToolAdapter` — `name="fake_tool"`, `kind=AdapterKind.NATIVE`, in-memory `dict` store,
constructor `FakeToolAdapter(clock=time.monotonic)`; `start()`/`stop()` set/clear `self.started`.

| Operation | `read_only` | `timeout_s` | params | Behaviour (exact) |
|---|---|---|---|---|
| `echo` | `True` | 5.0 | `EchoParams` | returns `ok=True, data={"echo": text}` |
| `write_item` | `False` | 5.0 | `WriteItemParams` | stores `store[key]=value`; returns `ok=True, data={"written": key, "count": len(store)}` |
| `fail_upstream` | `True` | 5.0 | `NoParams` | returns `ok=False, error_kind="upstream_error", error_message="fake upstream failure"` |
| `raise_unexpected` | `True` | 5.0 | `NoParams` | handler raises `RuntimeError("fake crash")` — tests assert the MANAGER converts it to `error_kind="upstream_error"`, message `"unhandled adapter exception"` (never the raw exception text) |
| `sleep_forever` | `True` | 0.05 | `NoParams` | `await asyncio.sleep(3600)` — exercises the timeout path: manager returns `error_kind="timeout"` |

Every result's `meta` = `ToolResultMeta(adapter_kind=NATIVE, server_id=None, duration_ms=<measured>)`.

### 6.4 Contract tests

Published as `apps/api/tests/contracts/test_c1_tool_adapter.py`; any adapter implementation must
pass them, run first against the fakes. Fixture for every test:
`ToolManager([FakeToolAdapter()], FakePermissionHook(), FakeApprovalsService(),
RecordingAuditHook())`; `trace = TraceContext(request_id="req-1", task_id="task-1",
conversation_id="conv-1")`.

1. unknown operation → `unknown_operation`; one attempt row with `permission_decision=None`,
   finalised `outcome="error"`.
2. extra param key → `invalid_params` (proves `extra="forbid"`); attempt row has `args_hash=None`.
3. empty grant registry → `write_item` returns `permission_denied` (structural default-deny).
4. `hook.grant("agent-1", "fake_tool", "write_item", "ask_user")`, execute with no `approval` →
   `approval_required` AND `FakeApprovalsService` now holds exactly one `pending` approval whose
   `args_hash == sha256(canonical_json(validated params))` (rule below) and whose
   `request_id/task_id/conversation_id` equal the `TraceContext` values.
5. same grant; take test 4's `approval_id`, `fake_approvals.decide(approval_id, "approve", None,
   now)`, re-execute the IDENTICAL params with `approval=approval_id` → executes, `ok=True`; the
   attempt row carries `approval_id`; the approval's status is `consumed`. Re-executing a third
   time with the same id → `approval_invalid` (single-use, C4 test 1's property seen from C1).
6. `sleep_forever` → `timeout` in < 1 s wall clock.
7. every case above produced exactly one attempt AND exactly one finalise (two-phase pairing).
   Ordering probe (attempt precedes execution): build one extra manager whose adapter is a
   `FakeToolAdapter` with its `echo` handler wrapped test-locally to append `"execute"` to a shared
   `events: list[str]`, and whose audit hook is a `RecordingAuditHook` subclass whose `attempt`
   appends `"attempt"` to the same list — after one `echo` call assert
   `events == ["attempt", "execute"]`.

`args_hash` canonicalisation (normative for C1 and C4): `sha256` hex digest of the UTF-8 JSON
serialisation of the **validated** params model with `sort_keys=True`, separators `(",", ":")`.

## Changelog

- **v1.0.0 — 2026-09-10 fix round** (pre-merge; version unchanged because the freeze was never
  merged). `execute` signature typed: `TraceContext` + `approval: str | None` (QA B2). Consume
  ownership: the manager consumes via the C4 `ApprovalsService` seam, which replaces `ParkHook`;
  continuation path re-enters the pipeline (QA B3, ADR-031 Amendment 1). Two-phase audit
  (`attempt`/`finalise`, `ToolCallAttempt` typed) (Security item 3). Fake specs added for
  `PermissionHook` (grant API), `AuditHook`; approvals fake = C4 §6 (QA B1). Strip-list defined
  recursive + case-insensitive, cosmetic (Security item 4). `credential_env:`→`Settings` mapping
  specified (QA should-fix). Plan-literal cross-reference in step 2 (Security build-check item 5).
