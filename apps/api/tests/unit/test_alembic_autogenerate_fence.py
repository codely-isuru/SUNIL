"""The `approvals` autogenerate fence — wave-1 ruling R2, step 2.

`db/alembic/env.py` targets `Base.metadata`. Deleting `db/models.py::Approval`
(R2 step 1) removes a *false* second definition of a production table — the ORM
class declared VARCHAR timestamps and one index while the deployed table
(`core/approvals/table.py`, migration `d4approvals0001`) has TIMESTAMPTZ and
four — but deleting it ALONE flips the poison rather than removing it: the
metadata then has no `approvals` while the database does, and the next
autogenerate emits `op.drop_table("approvals")`. A silent DROP of an
audit-bearing table.

So the deletion is only safe paired with this fence, and the fence is only real
if it holds on BOTH sides:

* **reflection** (`include_name`) — what the database has and the metadata does
  not, which is the DROP;
* **metadata** (`include_object`) — what a future re-added ORM class would
  claim, which is the CREATE/ALTER toward a shape no deployment runs.

The owner of the table is `core/approvals/table.py` on its private
`APPROVALS_METADATA` plus Stream D's hand-written revisions. Autogenerate must
never manage a table owned by hand-written revisions.
"""

from __future__ import annotations

import pytest
from sqlalchemy import Column, MetaData, String, Table

from sunil.db.autogenerate import FENCED_TABLES, include_name, include_object

_OTHER = MetaData()
_approvals_like = Table("approvals", _OTHER, Column("id", String(36), primary_key=True))
_tasks_like = Table("tasks", _OTHER, Column("id", String(36), primary_key=True))


def test_the_fence_names_the_hand_written_table() -> None:
    assert "approvals" in FENCED_TABLES


@pytest.mark.parametrize("parent", [None, "public"])
def test_a_reflected_approvals_table_is_excluded(parent: str | None) -> None:
    """The DROP case. Alembic asks `include_name` about every name it reflects;
    answering False keeps `approvals` out of the comparison entirely."""
    assert (
        include_name("approvals", "table", {"schema_name": parent}) is False
    )


def test_every_other_reflected_table_is_still_compared() -> None:
    """A fence that excluded everything would make autogenerate useless while
    looking like it worked."""
    for name in ("tasks", "audit_events", "tool_calls", "users"):
        assert include_name(name, "table", {"schema_name": None}) is True


def test_a_non_table_name_is_never_fenced() -> None:
    """`include_name` is asked about schemas and columns too; the fence is about
    one TABLE, so it must not swallow a column that happens to be called
    `approvals`."""
    assert include_name("approvals", "column", {"table_name": "tasks"}) is True
    assert include_name(None, "schema", {}) is True


def test_an_approvals_table_in_the_target_metadata_is_excluded() -> None:
    """The CREATE/ALTER case: if a future ORM class re-declares `approvals`,
    autogenerate must still not manage it — the shape would be the ORM's, not
    the deployed one, which is exactly the drift R2 removed."""
    assert include_object(_approvals_like, "approvals", "table", False, None) is False


def test_other_metadata_tables_are_still_managed() -> None:
    assert include_object(_tasks_like, "tasks", "table", False, None) is True


def test_the_spines_metadata_no_longer_declares_approvals() -> None:
    """R2 step 1, asserted where it is observable: `Base.metadata` — the
    autogenerate target and what `create_all` builds — must not carry an
    `approvals` definition at all. The ONE true declaration is
    `core/approvals/table.py`, pinned against the migration by
    `tests/unit/approvals/test_migration_matches_table.py`.
    """
    from sunil.db.base import Base

    assert "approvals" not in Base.metadata.tables


def test_the_one_true_approvals_declaration_is_stream_ds() -> None:
    """The counterpart, so "no approvals in Base.metadata" cannot pass by the
    table having disappeared from the codebase entirely."""
    from sunil.core.approvals.table import APPROVALS_METADATA

    assert "approvals" in APPROVALS_METADATA.tables
