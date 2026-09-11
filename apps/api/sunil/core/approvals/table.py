"""The ``approvals`` table — SQLAlchemy **Core**, on its own ``MetaData``.

Why Core and its own metadata, not a row in ``db/models.py``: Stream D owns
``core/approvals/*`` (ARCHITECTURE_V2 §3) while the spine lane owns the base
schema, and the two streams build in parallel worktrees. A private
``MetaData`` means this table can be created, dropped and migrated without
importing a spine module that may not exist yet, and the service's
compare-and-swap statements are written as ``UPDATE … WHERE status=… RETURNING``
in Core — the literal shape C4 §1's transition table specifies. An ORM
``session.merge``/flush path would read, mutate in Python and write back, which
is a read-modify-write and therefore NOT a CAS.

The two load-bearing schema decisions, both from C4:

* **``status`` has NO server default** (C4 §1 and the OpenAPI ``ApprovalStatus``
  description, central-memory lesson 2026-08-17). Every creation path must name
  the value; an omitting path is an error, never a silently-decided row. The
  ``CheckConstraint`` bounds the column to the five contract values so a typo in
  a future transition cannot invent a sixth state.
* **``continuation`` is a column on this row** (C4 §1 restart safety). The park
  INSERT is one statement, so "commits in the same transaction as the persisted
  continuation state" is true by construction rather than by discipline. It is
  deliberately absent from the C4 ``Approval`` response model — it never leaves
  this service over HTTP (C4 §4).

Timestamps are ``TIMESTAMP WITH TIME ZONE``. The service converts to and from
the contract's ``…Z`` strings at its edge, so nothing above it handles naive
datetimes.

No foreign keys. ``task_id``/``conversation_id``/``request_id`` are contract
**strings** (C4 OpenAPI ``Approval``), and declaring FKs into the spine's tables
would couple this migration to the spine's revision for no integrity the
service relies on — the reconciliation already treats a missing task as a fact
to handle, not an impossibility.
"""

from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    Index,
    JSON,
    MetaData,
    String,
    Table,
)

#: Stream D's private metadata — see the module docstring.
APPROVALS_METADATA = MetaData()

TABLE_NAME = "approvals"

#: The five C4 ``ApprovalStatus`` values, as the CHECK constraint sees them.
STATUS_VALUES = ("pending", "approved", "refused", "expired", "consumed")

approvals_table = Table(
    TABLE_NAME,
    APPROVALS_METADATA,
    Column("id", String(64), primary_key=True),
    # NOTE: no server_default, and nullable=False — C4 §1.
    Column("status", String(16), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("agent_id", String(128), nullable=False),
    Column("tool", String(128), nullable=False),
    Column("operation", String(128), nullable=False),
    Column("args_hash", String(128), nullable=False),
    Column("params_redacted", JSON, nullable=False),
    Column("request_id", String(64), nullable=False),
    Column("conversation_id", String(64), nullable=False),
    Column("task_id", String(64), nullable=False),
    Column("summary", String(500), nullable=False),
    # Persisted in the park transaction; never serialised over HTTP (C4 §4).
    Column("continuation", JSON, nullable=False),
    Column("decided_at", DateTime(timezone=True), nullable=True),
    Column("decided_by", String(128), nullable=True),
    Column("decision_reason", String(1000), nullable=True),
    Column("consumed_at", DateTime(timezone=True), nullable=True),
    CheckConstraint(
        "status IN ('pending', 'approved', 'refused', 'expired', 'consumed')",
        name="ck_approvals_status",
    ),
    # The sweeper's two guards (§1): pending-past-TTL and approved-past-grace.
    Index("ix_approvals_status_expires_at", "status", "expires_at"),
    Index("ix_approvals_status_decided_at", "status", "decided_at"),
    # C4 §6.5's page order, so the keyset cursor is an index scan.
    Index("ix_approvals_created_at_id", "created_at", "id"),
    # The dashboard's per-task lookup and the reconciliation's scan.
    Index("ix_approvals_task_id", "task_id"),
)
