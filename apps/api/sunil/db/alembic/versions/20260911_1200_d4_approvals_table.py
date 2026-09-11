"""C4 approvals table (Stream D).

Revision ID: d4approvals0001
Revises: (branch root — see the coordination note)
Create Date: 2026-09-11

Coordination note (why this is a branch root and not a child of the spine's
initial-schema revision)
------------------------------------------------------------------------
Stream D and the spine lane build in parallel worktrees and the spine owns the
initial schema revision, whose id does not exist yet on this branch. Hard-coding
a guess for ``down_revision`` would produce a migration graph that cannot be
resolved. So this revision declares itself a **branch root** with the label
``approvals``, which is honest rather than merely convenient: the table has NO
foreign keys into the spine's schema (see ``core/approvals/table.py`` — C4's
``task_id``/``conversation_id``/``request_id`` are contract strings), so it has
no real dependency to express.

At integration the spine lane does one of two things, both one-liners:

* ``alembic upgrade heads`` (plural) and add a merge revision — the standard
  Alembic branch workflow; or
* set ``down_revision = "<spine initial revision>"`` here and delete
  ``branch_labels``, linearising the graph.

Either is fine. What must NOT happen is a second revision also creating an
``approvals`` table: C4 is Stream D's contract (ARCHITECTURE_V2 §3) and this
file is its only schema. Flagged to the Delivery Manager in
``docs/tasks/S-D-approvals.md``.

Two schema decisions are contract requirements, not preferences, and a reviewer
should check them here specifically:

1. ``status`` has **no server default** (C4 §1, OpenAPI ``ApprovalStatus``;
   central-memory lesson 2026-08-17). A creation path that omits the status must
   fail loudly instead of minting a row that reads as decided. The CHECK
   constraint bounds the column to C4's five values.
2. ``continuation`` is ``NOT NULL`` on this row, which is what makes C4 §1's
   restart-safety rule ("the park INSERT commits in the same transaction as the
   persisted continuation state") true by construction: one INSERT, one row.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "d4approvals0001"
down_revision = None
branch_labels = ("approvals",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "approvals",
        sa.Column("id", sa.String(length=64), primary_key=True),
        # No server_default — C4 §1. See the module docstring.
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("tool", sa.String(length=128), nullable=False),
        sa.Column("operation", sa.String(length=128), nullable=False),
        sa.Column("args_hash", sa.String(length=128), nullable=False),
        sa.Column("params_redacted", sa.JSON(), nullable=False),
        sa.Column("request_id", sa.String(length=64), nullable=False),
        sa.Column("conversation_id", sa.String(length=64), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False),
        sa.Column("continuation", sa.JSON(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decided_by", sa.String(length=128), nullable=True),
        sa.Column("decision_reason", sa.String(length=1000), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'approved', 'refused', 'expired', 'consumed')",
            name="ck_approvals_status",
        ),
    )
    # The sweeper's two guards (C4 §1).
    op.create_index(
        "ix_approvals_status_expires_at", "approvals", ["status", "expires_at"]
    )
    op.create_index(
        "ix_approvals_status_decided_at", "approvals", ["status", "decided_at"]
    )
    # C4 §6.5's page order, so the keyset cursor is an index scan.
    op.create_index("ix_approvals_created_at_id", "approvals", ["created_at", "id"])
    op.create_index("ix_approvals_task_id", "approvals", ["task_id"])


def downgrade() -> None:
    op.drop_index("ix_approvals_task_id", table_name="approvals")
    op.drop_index("ix_approvals_created_at_id", table_name="approvals")
    op.drop_index("ix_approvals_status_decided_at", table_name="approvals")
    op.drop_index("ix_approvals_status_expires_at", table_name="approvals")
    op.drop_table("approvals")
