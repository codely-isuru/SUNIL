"""ORM models — the twelve tables of `ARCHITECTURE_V1.md` §7.3, migration
`0001_initial`.

`users, conversations, messages, workflows, tasks, task_status_events,
plans, tool_calls, approvals, memories, llm_calls, audit_events`. Twelve —
an earlier draft of the build plan said eleven while listing twelve; it is
twelve (`docs/M1_BUILD_PLAN.md` §0.2 revision note #4).

Every rule in `sunil.db.base` applies throughout: text UUID primary keys,
portable JSON, UTC timestamps (`DateTime(timezone=True)`, written via
`utc_now()`), `String` + `StrEnum` + `CheckConstraint` instead of native
enums, no server-side defaults, and money as `BigInteger` micro-USD
(`Numeric` is lossy and warns on SQLite).

No `relationship()` declarations: lazy loading is a footgun on async
sessions (ADR-002's consequence). Joins are explicit `select()` statements
written by the callers that need them.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from sunil.core.trace.stages import TraceStage
from sunil.db.base import Base, PortableJSON, enum_check_constraint, new_uuid, utc_now
from sunil.db.capture import CapturePolicy, RetentionClass, Sensitivity

# A `DateTime(timezone=True)` column, defaulted in Python (§7.2 — no
# server-side defaults). Every timestamp column in this module uses this.
_TZ_TIMESTAMP = DateTime(timezone=True)

# ---------------------------------------------------------------------------
# Enums (§7.2: String column + StrEnum + CheckConstraint, never native ENUM)
# ---------------------------------------------------------------------------


class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class WorkflowTrigger(StrEnum):
    """M1 has exactly one trigger; the type exists so a second one (M10's
    scheduler) is an enum addition, not a schema change."""

    CHAT_MESSAGE = "chat_message"


class WorkflowStatus(StrEnum):
    """§7.3 does not spell out `workflows.status`'s values explicitly;
    mirrored from `tasks.status`, which is spelled out, since a workflow's
    lifecycle is the same shape as its task's in M1 (one task per
    workflow). Flagged here as a judgment call, not a quoted requirement.
    """

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class PermissionDecision(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ASK_USER = "ask_user"


class ToolCallStatus(StrEnum):
    OK = "ok"
    ERROR = "error"
    NOT_EXECUTED = "not_executed"


class ApprovalStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class MemoryType(StrEnum):
    SHORT_TERM = "short_term"
    LONG_TERM = "long_term"
    STRUCTURED = "structured"
    KNOWLEDGE = "knowledge"
    PREFERENCE = "preference"


class LLMPurpose(StrEnum):
    """Mirrors `sunil.providers.base.LLMPurpose` (T6) by value. Duplicated
    rather than imported so `sunil.db` never depends on `sunil.providers`
    (`core/` must not import in the wrong direction — §3.1). M1 writes
    `plan` and `analysis` only (ADR-015); `final_response` is a legal
    column value with no M1 writer."""

    PLAN = "plan"
    ANALYSIS = "analysis"
    FINAL_RESPONSE = "final_response"


# ---------------------------------------------------------------------------
# Shared capture-policy columns (ADR-014, §7.3.1) — messages, plans,
# llm_calls, tool_calls, memories. Deliberately NOT applied to audit_events.
# ---------------------------------------------------------------------------


class CaptureColumns:
    """The four ADR-014 columns. No Python-side defaults: every insert on a
    capture table must go through `db.capture.resolve_capture()` and set
    all four explicitly, so an omitted call fails loudly (an
    `IntegrityError`) instead of silently defaulting to something that
    reads like a decision nobody made."""

    capture_policy: Mapped[str] = mapped_column(String(20), nullable=False)
    sensitivity: Mapped[str] = mapped_column(String(20), nullable=False)
    retention_class: Mapped[str] = mapped_column(String(20), nullable=False)
    training_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)


def _capture_check_constraints(table_name: str) -> tuple:
    return (
        enum_check_constraint(
            "capture_policy", CapturePolicy, name=f"ck_{table_name}_capture_policy"
        ),
        enum_check_constraint("sensitivity", Sensitivity, name=f"ck_{table_name}_sensitivity"),
        enum_check_constraint(
            "retention_class", RetentionClass, name=f"ck_{table_name}_retention_class"
        ),
    )


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    preferences: Mapped[dict] = mapped_column(PortableJSON, nullable=False, default=dict)
    security_settings: Mapped[dict] = mapped_column(PortableJSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)


class Conversation(Base):
    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    active_context: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)


class Message(CaptureColumns, Base):
    __tablename__ = "messages"
    __table_args__ = (
        enum_check_constraint("role", MessageRole, name="ck_messages_role"),
        *_capture_check_constraints("messages"),
        Index("ix_messages_conversation_seq", "conversation_id", "seq"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), nullable=False, index=True
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_in: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_out: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_micro_usd: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)


class Workflow(Base):
    __tablename__ = "workflows"
    __table_args__ = (
        enum_check_constraint("trigger", WorkflowTrigger, name="ck_workflows_trigger"),
        enum_check_constraint("status", WorkflowStatus, name="ck_workflows_status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    owner_user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    trigger: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    schedule: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(_TZ_TIMESTAMP, nullable=True)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (enum_check_constraint("status", TaskStatus, name="ck_tasks_status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    workflow_id: Mapped[str] = mapped_column(ForeignKey("workflows.id"), nullable=False, index=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), nullable=False, index=True
    )
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    parent_task_id: Mapped[str | None] = mapped_column(
        ForeignKey("tasks.id"), nullable=True
    )  # always null in M1
    assigned_agent: Mapped[str] = mapped_column(String(100), nullable=False)
    privacy_level: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(_TZ_TIMESTAMP, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(_TZ_TIMESTAMP, nullable=True)
    failure_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)


class TaskStatusEvent(Base):
    __tablename__ = "task_status_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)


class Plan(CaptureColumns, Base):
    __tablename__ = "plans"
    __table_args__ = (*_capture_check_constraints("plans"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    validated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    validation_errors: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)


class ToolCall(CaptureColumns, Base):
    __tablename__ = "tool_calls"
    __table_args__ = (
        enum_check_constraint(
            "permission_decision", PermissionDecision, name="ck_tool_calls_permission_decision"
        ),
        enum_check_constraint("status", ToolCallStatus, name="ck_tool_calls_status"),
        *_capture_check_constraints("tool_calls"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    # ADR-004 Amendment 1 / ExecutionMetadata: the plan that authorised this
    # call. §7.3's prose omits this column; §6.1's ExecutionMetadata chain
    # requires it ("all four fields are written onto the tool_calls row").
    validated_plan_id: Mapped[str] = mapped_column(
        ForeignKey("plans.id"), nullable=False, index=True
    )
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tool: Mapped[str] = mapped_column(String(100), nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    parameters: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    permission_decision: Mapped[str] = mapped_column(String(20), nullable=False)
    permission_reason: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    result: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    error_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)


class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (enum_check_constraint("status", ApprovalStatus, name="ck_approvals_status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    tool_call_id: Mapped[str | None] = mapped_column(
        ForeignKey("tool_calls.id"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(200), nullable=False)
    risk: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_by: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    user_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)
    decided_at: Mapped[datetime | None] = mapped_column(_TZ_TIMESTAMP, nullable=True)


class Memory(CaptureColumns, Base):
    __tablename__ = "memories"
    __table_args__ = (
        enum_check_constraint("type", MemoryType, name="ck_memories_type"),
        *_capture_check_constraints("memories"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    source_task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    relevance: Mapped[float | None] = mapped_column(nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)
    # `sensitivity` (NFR-009, non-null) is provided by CaptureColumns —
    # §7.3.1: "already carried sensitivity for NFR-009; it gains the other
    # three" — one physical column serves both purposes, not a duplicate.


class LLMCall(CaptureColumns, Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        enum_check_constraint("purpose", LLMPurpose, name="ck_llm_calls_purpose"),
        *_capture_check_constraints("llm_calls"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    capability: Mapped[str] = mapped_column(String(50), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    request_system: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_messages: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    request_schema: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_json: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    pricing_version: Mapped[str] = mapped_column(String(20), nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    provider_request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)


class AuditEvent(Base):
    """The table ET-6 is graded against. Deliberately carries none of the
    ADR-014 capture columns (§7.3.1) — a capture policy must never be able
    to suppress an audit row."""

    __tablename__ = "audit_events"
    __table_args__ = (
        enum_check_constraint("stage", TraceStage, name="ck_audit_events_stage"),
        UniqueConstraint("request_id", "seq", name="uq_audit_events_request_seq"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    stage: Mapped[str] = mapped_column(String(30), nullable=False)
    task_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    detail: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)
