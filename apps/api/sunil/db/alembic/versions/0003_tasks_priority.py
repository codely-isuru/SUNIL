"""tasks.priority — the column C6's frozen `Task` shape reads

`C6-ops-reads-openapi.yaml` lists `priority` in `Task.required` and sources it
from `tasks.priority` ("V2 writes 'normal' (M1 schema default)"). The V2
transcription of `ARCHITECTURE_V1.md` §7.3 into `db/models.py` dropped it, so
every C6 tasks/activity read was a 500 (`no such column: tasks.priority`) the
moment the routes were mounted on the real schema. Found at integration-w1: each
lane was green alone because Stream D's suite seeds its own read-model tables.

`NOT NULL` with a server default of `'normal'` rather than nullable: the shape
promises a string, and `priority` — unlike `project_key` (0002) — has a true
default rather than an unknowable historical value, so backfilling existing rows
states a fact rather than a guess.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "priority",
            sa.String(length=20),
            nullable=False,
            server_default="normal",
        ),
    )


def downgrade() -> None:
    op.drop_column("tasks", "priority")
