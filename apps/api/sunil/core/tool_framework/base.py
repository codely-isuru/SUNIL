"""C1 — Tool Adapter interface (frozen contract transcription).

Source of truth: ``docs/contracts/C1-tool-adapter.md`` v1.0.0 (FROZEN, Phase 0
2026-09-10) §2 "Interface definition", §2.2 "Injected hooks (the seams streams
fake)" and §4 "Error semantics". Python ≥ 3.12, Pydantic v2 (C1 §2).

Zero business logic lives here: protocols, dataclasses, enums and exceptions
only. The Tool Manager pipeline of §2.1 — the single execution chokepoint — is
``core/tool_framework/manager.py`` (ARCHITECTURE_V2 §2) and is written by the
implementing engineer, not QA. ``ToolManagerProtocol`` below carries §2.1's
frozen call shape so the implementation can be checked against it.

The approvals seam this module's manager is constructed with is C4 §4's
``ApprovalsService`` (``sunil.core.approvals.base``) — defined once, injected
here (C1 §2.2; the narrower ``ParkHook`` was deleted in the 2026-09-10 fix round
with QA B3's consume-ownership fix).
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, Protocol

from pydantic import BaseModel

if TYPE_CHECKING:  # pragma: no cover - typing only
    from sunil.core.approvals.base import ApprovalsService


class AdapterKind(StrEnum):
    """C1 §2."""

    NATIVE = "native"  # in-process Python handler
    MCP_STDIO = "mcp_stdio"  # MCP server spawned as a child process, JSON-RPC over stdio
    MCP_HTTP = "mcp_http"  # MCP streamable-HTTP server (e.g. n8n MCP server)


@dataclass(frozen=True)
class ToolResultMeta:
    """Provenance every result carries. `adapter_kind` and `server_id` land on the
    `tool_calls` audit row so 'audit shows adapter type per call' (V2-A exit) is a
    database fact, not an inference."""

    adapter_kind: AdapterKind
    server_id: str | None  # MCP server identity from config/tools.yaml; None for NATIVE
    duration_ms: int


@dataclass(frozen=True)
class ToolResult:
    """The normalised shape every adapter call collapses to. An adapter exception
    NEVER reaches the orchestrator as an exception — it is always this value."""

    ok: bool
    data: dict | None  # None when ok=False
    error_kind: str | None  # closed set, §4 below; None when ok=True
    error_message: str | None  # human-readable, redacted; None when ok=True
    meta: ToolResultMeta


@dataclass(frozen=True)
class ToolOperation:
    """One operation an adapter exposes. `params_model` uses `extra="forbid"` (§26.8).
    For MCP adapters, `read_only` and `timeout_s` come from SUNIL's config/tools.yaml,
    NEVER from the server's self-description (ADR-034)."""

    name: str  # e.g. "issues.close"
    params_model: type[BaseModel]
    read_only: bool
    timeout_s: float
    handler: Callable[[BaseModel], Awaitable[ToolResult]]


class ToolAdapter(Protocol):
    """What every adapter implements. Deliberately NOT @runtime_checkable (M1 tripwire
    lesson: a runtime-checkable Protocol makes isinstance prove shape, not provenance).
    The Tool Manager is constructed with concrete instances by the wiring code."""

    name: str  # tool id in the permission matrix, e.g. "github"
    kind: AdapterKind
    operations: dict[str, ToolOperation]

    async def start(self) -> None: ...  # NATIVE: no-op. MCP: spawn/connect + handshake + discovery

    async def stop(self) -> None: ...  # NATIVE: no-op. MCP: terminate child / close session


class ToolAdapterStartupError(Exception):
    """C1 §2 — raised by wiring when ``start()`` fails, and by §5's
    ``credential_env:`` → ``Settings`` mapping when a named variable has no
    matching ``Settings`` field or an unset value. A tool that cannot start is
    absent from the registry, never half-present, and never a KeyError at call
    time."""


# --------------------------------------------------------------------------- #
# C1 §2.2 — injected hooks (the seams streams fake)
# --------------------------------------------------------------------------- #
class PermissionDecision(StrEnum):
    """C1 §2.2."""

    ALLOW = "allow"
    DENY = "deny"
    ASK_USER = "ask_user"


@dataclass(frozen=True)
class PermissionResult:
    """M1 engine shape kept verbatim; default-deny is structural in the engine, not config."""

    decision: PermissionDecision
    reason: str  # human-readable why, e.g. "granted" / "no grant for this triple (default deny)"
    source: str  # what decided, e.g. "config:project_manager.github_mcp.issues_close"


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
    adapter_kind: AdapterKind | None  # None iff the tool itself was unknown (step 1)
    server_id: str | None
    args_hash: str | None  # None when validation failed/never ran (steps 1–2 exits)
    params_redacted: dict | None  # None when validation failed/never ran
    permission_decision: PermissionDecision | None  # None when the pipeline exited before step 3
    permission_reason: str | None
    approval_id: str | None
    created_at: str  # ISO-8601 UTC


class PermissionHook(Protocol):
    """C1 §2.2."""

    def __call__(self, *, agent_id: str, tool: str, operation: str) -> PermissionResult: ...


class AuditHook(Protocol):
    """C1 §2.2 — two-phase audit (Security review 2026-09-10 item 3)."""

    async def attempt(self, record: ToolCallAttempt) -> str: ...
    # Returns the audit row id. Called once per execute() call, before any handler runs.

    async def finalise(
        self,
        audit_id: str,
        *,
        outcome: Literal["ok", "error"],
        error_kind: str | None,
        duration_ms: int,
    ) -> None: ...
    # Called exactly once per attempt, after the pipeline resolves (immediately, on early exits).


# --------------------------------------------------------------------------- #
# C1 §4 — error semantics (closed set)
# --------------------------------------------------------------------------- #
class ToolErrorKind(StrEnum):
    """C1 §4's closed set. ``ToolResult.error_kind`` keeps its frozen ``str | None``
    type; this enum names the permitted values (``StrEnum`` members ARE ``str``, so
    either form satisfies the field and comparisons). The orchestrator branches on
    ``error_kind`` only, never on ``error_message``."""

    UNKNOWN_OPERATION = "unknown_operation"  # tool/operation not in registry (step 1)
    INVALID_PARAMS = "invalid_params"  # Pydantic validation failed (step 2)
    PERMISSION_DENIED = "permission_denied"  # engine returned DENY (step 3)
    APPROVAL_REQUIRED = "approval_required"  # parked via C4 (step 3)
    APPROVAL_INVALID = "approval_invalid"  # supplied approval did not bind (step 3)
    TIMEOUT = "timeout"  # timeout_s exceeded (step 5)
    UPSTREAM_ERROR = "upstream_error"  # tool/server executed and failed (step 5)
    TRANSPORT_ERROR = "transport_error"  # could not reach the server (step 5)


# --------------------------------------------------------------------------- #
# C1 §2.1 — the Tool Manager's frozen call shape
# --------------------------------------------------------------------------- #
class ToolManagerProtocol(Protocol):
    """C1 §2.1's ``ToolManager`` signature, as a Protocol.

    The contract declares a concrete ``ToolManager`` whose ``__init__`` is
    ``(adapters, permission_hook, approvals, audit_hook)``; the implementation
    lives in ``core/tool_framework/manager.py`` and must satisfy this shape. It is
    transcribed as a Protocol here so that this interface module contains no
    implementation and nothing importable can be mistaken for the chokepoint.
    (Name deviates from the contract's ``ToolManager`` for exactly that reason —
    recorded as a finding in ``docs/tasks/P0-fakes.md``.)

    ``params`` is the raw candidate dict from the validated plan step; ``trace`` is
    the ``TraceContext`` above; ``approval`` is the **C4 approval id string** minted
    at park time — ``None`` on every first attempt, set only by the continuation
    executor (ADR-031). It is an opaque id, never a C4 object: the manager
    recomputes the binding itself (§2.1 step 3), so a caller cannot vouch for a
    binding it did not compute. There is no default hook: constructing a manager
    without an audit hook is a ``TypeError``, so "forgot to audit" is not an
    expressible program.
    """

    def __init__(
        self,
        adapters: list[ToolAdapter],
        permission_hook: PermissionHook,
        approvals: ApprovalsService,
        audit_hook: AuditHook,
    ) -> None: ...

    async def execute(
        self,
        agent_id: str,
        tool: str,
        operation: str,
        params: dict,
        *,
        trace: TraceContext,
        approval: str | None = None,
    ) -> ToolResult: ...
