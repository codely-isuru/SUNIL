"""tasks.project_key — the C6 §3 / ADR-036 (Q2) schema delta

A nullable `project_key` on `tasks`, written once at task creation from the
`ValidatedPlan`. Its own revision rather than an edit to `0001`: `0001` has been
applied to real databases, and rewriting an applied migration is how two
environments end up with the same revision id and different schemas.

Nullable with no backfill, deliberately. Existing rows predate the column and
their project can only be inferred from `audit_events.plan_created.detail`;
writing a guessed value would make an inference indistinguishable from a fact in
the very column the Tasks filter trusts. Old rows are simply absent from
`?project_key=…` results, which is the honest answer.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("project_key", sa.String(length=100), nullable=True))
    op.create_index(op.f("ix_tasks_project_key"), "tasks", ["project_key"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tasks_project_key"), table_name="tasks")
    op.drop_column("tasks", "project_key")
