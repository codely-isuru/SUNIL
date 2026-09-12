"""ORM models — the V2 spine's tables, Alembic revision `0001_spine`.

`users, conversations, messages, tasks, task_status_events, plans, llm_calls,
tool_calls, audit_events`. Nine tables: everything a governed turn writes and
nothing a stream has not started yet (Stream C's entity/memory tables and Stream
E's workflow tables arrive with their own migrations).

**`approvals` is deliberately not here** (wave-1 ruling R2, applied in the wave-2
wiring round). Its one true declaration is `core/approvals/table.py` on the
private `APPROVALS_METADATA`, created and altered by Stream D's hand-written
revisions. The ORM class this module used to carry declared VARCHAR timestamps
and one index while the deployed table has TIMESTAMPTZ and four — so it was the
only `approvals` autogenerate could see, and it disagreed with every deployment.
`db/autogenerate.py` fences the name out of the comparison on both sides, which
is what makes this absence safe rather than a pending `op.drop_table`.

Shapes are taken from two frozen sources, not invented:

* `audit_events` — the spine ROADMAP §28 is graded against, with
  `UniqueConstraint(request_id, seq)` and a CHECK over `TraceStage`. It carries
  **no** capture-policy columns: a capture policy must never be able to suppress
  an audit row.
* `tool_calls` — C1 §2.2's `ToolCallAttempt` (the pre-execution record) plus the
  two-phase finalise fields. `adapter_kind`/`server_id` are nullable exactly
  where C1 says they may be `None` (step 1 exited before an adapter was
  resolved).

Every rule in `sunil.db.base` applies throughout: text ids, portable JSON, UTC
timestamps, `String` + `StrEnum` + `CheckConstraint`, no server-side defaults, no
`relationship()`.
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

# A `DateTime(timezone=True)` column, defaulted in Python. Every timestamp
# column in this module uses this.
_TZ_TIMESTAMP = DateTime(timezone=True)


# --------------------------------------------------------------------------- #
# Enums (String column + StrEnum + CheckConstraint, never a native ENUM)
# --------------------------------------------------------------------------- #
class MessageRole(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ConversationChannel(StrEnum):
    """C5 §2.3 — recorded at creation, and the whole basis of the service lane's
    blast radius: a bearer-lane caller may only reach conversations whose
    channel is `service`."""

    WEB = "web"
    SERVICE = "service"


class TaskStatus(StrEnum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PARKED = "parked"  # ADR-031: a turn that hit ASK_USER and ended honestly


class PermissionDecisionValue(StrEnum):
    """Mirrors `sunil.core.tool_framework.base.PermissionDecision` by VALUE.
    Duplicated rather than imported so `sunil.db` never imports `core` beyond
    the trace stages — the import law in ARCHITECTURE_V2 §2."""

    ALLOW = "allow"
    DENY = "deny"
    ASK_USER = "ask_user"


class ToolCallOutcome(StrEnum):
    OK = "ok"
    ERROR = "error"
    NOT_EXECUTED = "not_executed"  # the pipeline exited before the adapter ran


# `ApprovalStatusValue` lived here as the CHECK-constraint vocabulary of the
# deleted ORM `Approval` (wave-1 ruling R2). It went with it: the deployed
# table's constraint is written in `core/approvals/table.py`, and a second copy
# of a lifecycle enum in a module that no longer declares the table is the drift
# generator R2 removed, one layer down.


class LLMPurpose(StrEnum):
    """ADR-015's two logical calls, plus the third the envelope reserves."""

    PLAN = "plan"
    ANALYSIS = "analysis"
    FINAL_RESPONSE = "final_response"


# --------------------------------------------------------------------------- #
# Tables
# --------------------------------------------------------------------------- #
class User(Base):
    """The owner. Single-owner system (C5 §2.3), so this table exists for the
    session's subject and the password hash, not for multi-tenancy."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)


class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        enum_check_constraint("channel", ConversationChannel, name="ck_conversations_channel"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    # Nullable: a service-lane conversation has no owner session behind it
    # (ADR-035). The owner still sees it — single-owner system, C5 §2.3.
    user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    channel_label: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        enum_check_constraint("role", MessageRole, name="ck_messages_role"),
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
    # ADR-031 lineage: set on the assistant message a continuation appends, so
    # the conversation shows WHY the answer arrived minutes after the question.
    resumed_from_approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)


class Task(Base):
    __tablename__ = "tasks"
    __table_args__ = (enum_check_constraint("status", TaskStatus, name="ck_tasks_status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id"), nullable=False, index=True
    )
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    objective: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    assigned_agent: Mapped[str] = mapped_column(String(100), nullable=False)
    # C6's `Task` shape (frozen 2026-09-11) requires `priority` and sources it
    # from this column: "tasks.priority; V2 writes 'normal' (M1 schema default)".
    # It is carried from M1's schema, not invented here — the V2 transcription of
    # `ARCHITECTURE_V1.md` §7.3 dropped it, and a read route cannot project a
    # column that does not exist (every C6 tasks/activity read was a 500 against
    # the real schema until this line). Not an enum: the values are SUNIL-written
    # and trusted, and C6 deliberately declares it a string rather than freeze a
    # priority vocabulary a later agent would have to violate.
    priority: Mapped[str] = mapped_column(
        String(20), nullable=False, default="normal", server_default="normal"
    )
    # C6 §3 / ADR-036 (Q2 ruling): nullable, written ONCE at task creation from
    # the `ValidatedPlan`. Nothing updates it — see `core/tasks/service.py`. It
    # exists so `GET /api/v1/tasks?project_key=…` is a query rather than a
    # per-row join against `audit_events`.
    project_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    privacy_level: Mapped[str] = mapped_column(String(20), nullable=False, default="internal")
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(_TZ_TIMESTAMP, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(_TZ_TIMESTAMP, nullable=True)
    failure_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)


class TaskStatusEvent(Base):
    """Every transition, so a task's history is a record rather than a guess.

    `id` is a database-assigned monotonic integer, NOT the UUID every other row
    here carries, and the difference is load-bearing: C6's `TaskDetail` promises
    `status_events` "ascending `at`; ties keep write order", and two transitions
    of one task can share a timestamp (same-second, or a clock with second
    resolution). The tiebreak that promise reduces to — `ORDER BY at ASC, id
    ASC` in `api/routes/tasks.py` — is only write order if the id increases with
    writes. A UUID sorts by nothing, so it would make the contract sentence
    quietly false while every test stayed green (migration 0004; integration-w1
    §5.2). Nothing joins to this id and C6 does not put it on the wire
    (`TaskStatusEvent.required` is `[from_status, to_status, at]`), so the
    column is free to be the ordering key the contract needs.
    """

    __tablename__ = "task_status_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(ForeignKey("tasks.id"), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    to_status: Mapped[str] = mapped_column(String(20), nullable=False)
    at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)


class Plan(Base):
    """Every plan attempt — accepted or rejected — is evidence, never a lost log
    line. A `plan_rejected` turn must be able to show WHAT was rejected and why.
    `raw_json` is scrubbed before insert (the raw draft is model output, which
    can carry anything a user pasted into the prompt)."""

    __tablename__ = "plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), nullable=False)
    raw_json: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    validated: Mapped[bool] = mapped_column(Boolean, nullable=False)
    validation_errors: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)


class LLMCall(Base):
    """One row per provider ATTEMPT, including failures — that is what makes
    `usage` in the C5 envelope "summed across every provider attempt" (M1's A-2
    rule) a query rather than an in-memory tally that a failure path can drop."""

    __tablename__ = "llm_calls"
    __table_args__ = (enum_check_constraint("purpose", LLMPurpose, name="ck_llm_calls_purpose"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_id: Mapped[str | None] = mapped_column(ForeignKey("tasks.id"), nullable=True, index=True)
    agent_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    privacy_class: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    provider_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    request_messages: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    request_schema: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    response_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    response_json: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False)
    # Money as integer micro-USD: `Numeric` is lossy on SQLite and warns.
    cost_micro_usd: Mapped[int] = mapped_column(BigInteger, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)


class ToolCall(Base):
    """C1's two-phase audit row: inserted by `attempt()` BEFORE any handler runs,
    updated once by `finalise()`. Two phases, not one, because a row written only
    on completion is missing for exactly the calls worth investigating — a hang,
    a crash, a process kill mid-call (Security review 2026-09-10 item 3)."""

    __tablename__ = "tool_calls"
    __table_args__ = (
        enum_check_constraint(
            "permission_decision",
            PermissionDecisionValue,
            name="ck_tool_calls_permission_decision",
        ),
        enum_check_constraint("outcome", ToolCallOutcome, name="ck_tool_calls_outcome"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    request_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    task_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    # ADR-004 Amendment 1: the plan that authorised this call, so an executed
    # call is traceable to its authorising plan without inference. Nullable only
    # because a continuation re-enters the manager with the plan's id carried in
    # the approval's continuation state.
    validated_plan_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    tool: Mapped[str] = mapped_column(String(100), nullable=False)
    operation: Mapped[str] = mapped_column(String(100), nullable=False)
    # C1: None iff the tool itself was unknown — no adapter was ever resolved.
    adapter_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    server_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # C1: None when validation failed or never ran (steps 1-2 exits).
    args_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    params_redacted: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    # C1: None when the pipeline exited before step 3.
    permission_decision: Mapped[str | None] = mapped_column(String(20), nullable=True)
    permission_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    approval_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    error_kind: Mapped[str | None] = mapped_column(String(50), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)
    finalised_at: Mapped[datetime | None] = mapped_column(_TZ_TIMESTAMP, nullable=True)


class AuditEvent(Base):
    """The spine. `UniqueConstraint(request_id, seq)` makes "stage N of this turn"
    a single fact; the CHECK over `TraceStage` keeps a typo from looking like a
    thirteenth stage. No capture-policy columns, ever."""

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
    # "api" for a turn stage, "service" for the ADR-035 lane, a sweeper name for
    # a background write — who advanced the stage.
    actor: Mapped[str] = mapped_column(String(100), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # Enums and numbers only — never prose, never LLM output (the C5 rule).
    detail: Mapped[dict | None] = mapped_column(PortableJSON, nullable=True)
    at: Mapped[datetime] = mapped_column(_TZ_TIMESTAMP, nullable=False, default=utc_now)
