"""The migration and the table definition must not drift apart.

The service's compare-and-swap statements are written against
``core/approvals/table.py``; what production actually runs on is the Alembic
revision. If the two disagree the suite stays green and production breaks — and
the specific drift that would hurt most is silent: a ``server_default`` added to
``status`` in the migration only would make C4 §1's "no schema default" rule
false in the one place it matters, and every test here would still pass because
the tests create the table from the metadata.

So this module runs the migration's ``upgrade()`` for real (through Alembic's
``Operations`` against a live connection), reflects the result, and compares it
with the metadata the service uses. Both are then also checked against the C4
OpenAPI ``Approval`` schema's field list, so a third source of truth cannot
drift either.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, create_engine, inspect

from sunil.core.approvals.base import Approval
from sunil.core.approvals.table import STATUS_VALUES, TABLE_NAME, approvals_table

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "sunil"
    / "db"
    / "alembic"
    / "versions"
    / "20260911_1200_d4_approvals_table.py"
)


def _load_migration():
    """Import the revision file directly — there is no Alembic ``env.py`` in
    this worktree (the spine lane owns it), and the revision's ``upgrade()`` is
    a plain function that only needs an ``Operations`` context."""
    spec = importlib.util.spec_from_file_location("d4_approvals_migration", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def migrated():
    """A synchronous engine with the migration applied. Sync on purpose:
    Alembic's ``Operations`` API is synchronous, and this test is about DDL, not
    about the async service."""
    engine = create_engine("sqlite://")
    module = _load_migration()
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            module.upgrade()
        yield engine, conn


def test_migration_creates_exactly_the_columns_the_service_queries(migrated) -> None:
    """Column names and nullability, both directions — a column the service
    selects but the migration never creates is an outage on the first request."""
    engine, conn = migrated
    reflected = {
        col["name"]: col for col in inspect(conn).get_columns(TABLE_NAME)
    }

    assert set(reflected) == {c.name for c in approvals_table.columns}
    for column in approvals_table.columns:
        assert reflected[column.name]["nullable"] == column.nullable, column.name


def test_the_migration_gives_status_no_server_default(migrated) -> None:
    """C4 §1 and the central-memory lesson of 2026-08-17, asserted against the
    DDL rather than the Python model: a state column with a default reads as
    that default on every creation path that forgets it, and here an omitting
    path is an error, never a decided row."""
    engine, conn = migrated
    status = next(
        col for col in inspect(conn).get_columns(TABLE_NAME) if col["name"] == "status"
    )

    assert status["default"] is None
    assert status["nullable"] is False
    # …and the model agrees, so neither source can drift alone.
    assert approvals_table.c.status.server_default is None
    assert approvals_table.c.status.default is None


def test_the_status_check_constraint_bounds_the_five_contract_values(
    migrated,
) -> None:
    """The CHECK constraint is what stops a future transition inventing a sixth
    state — a typo in a ``.values(status=...)`` would otherwise persist
    happily and read as an unknown status to every consumer."""
    engine, conn = migrated
    ddl = "".join(
        row[0] or ""
        for row in conn.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name = 'approvals'"
        ).fetchall()
    )

    assert "ck_approvals_status" in ddl
    for value in STATUS_VALUES:
        assert f"'{value}'" in ddl
    assert STATUS_VALUES == ("pending", "approved", "refused", "expired", "consumed")


def test_migration_creates_the_indexes_the_sweeper_and_pager_need(migrated) -> None:
    """The three access paths C4 forces: the sweeper's two guards (§1) and the
    listing's ``(created_at, id)`` page order (§6.5). Without them the sweeper
    is a full scan every 60 s and the dashboard's keyset cursor sorts the whole
    table per page."""
    engine, conn = migrated
    names = {ix["name"] for ix in inspect(conn).get_indexes(TABLE_NAME)}

    assert {
        "ix_approvals_status_expires_at",
        "ix_approvals_status_decided_at",
        "ix_approvals_created_at_id",
        "ix_approvals_task_id",
    } <= names
    assert names == {ix.name for ix in approvals_table.indexes}


def test_the_table_carries_every_c4_approval_field_plus_the_continuation(
    migrated,
) -> None:
    """Third source of truth: the C4 OpenAPI ``Approval`` schema, transcribed in
    ``core/approvals/base.py``. Every one of its fields must be persistable, and
    the only extra column is ``continuation`` — which C4 §4 says never leaves
    this service over HTTP, hence its absence from the response model."""
    engine, conn = migrated
    columns = {col["name"] for col in inspect(conn).get_columns(TABLE_NAME)}

    assert set(Approval.model_fields) <= columns
    assert columns - set(Approval.model_fields) == {"continuation"}


def test_downgrade_removes_the_table(migrated) -> None:
    """A migration that cannot be rolled back is a migration nobody dares
    apply."""
    engine, conn = migrated
    module = _load_migration()
    context = MigrationContext.configure(conn)
    with Operations.context(context):
        module.downgrade()

    assert TABLE_NAME not in inspect(conn).get_table_names()
    assert MetaData() is not None  # sanity: reflection object still usable


def test_the_revision_is_a_documented_branch_root() -> None:
    """The coordination decision, pinned. ``down_revision = None`` plus a branch
    label is deliberate (the spine owns the initial revision and its id does not
    exist on this branch); if someone linearises the graph at integration this
    test is the reminder to update the docstring and the task file rather than
    leaving two contradictory stories."""
    module = _load_migration()

    assert module.revision == "d4approvals0001"
    assert module.down_revision is None
    assert module.branch_labels == ("approvals",)
    assert "branch root" in module.__doc__
