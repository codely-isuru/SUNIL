"""Revision 0005 and `core/memory/tables.py` must not drift apart.

The provider's SQL is written against the metadata; what production runs on is
the Alembic revision. If the two disagree the suite stays green and production
breaks — and the drift that would hurt most is silent: a `server_default` added
to `memories.privacy` in the migration only would make C3 §2's "REQUIRED, no
default" false in the one place it matters, while every test here, which creates
the schema from the metadata, kept passing.

So this module runs `upgrade()` for real against a live Postgres, reflects the
result, and compares it column-for-column with the metadata the provider uses.
Postgres and not SQLite, unlike the approvals lane's equivalent: `vector(1536)`
and HNSW are not renderable anywhere else, which is the same reason `upgrade()`
refuses to run on another dialect at all.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import pytest_asyncio
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import MetaData, create_engine, inspect, text

from sunil.core.memory.embedding import EMBEDDING_DIM
from sunil.core.memory.tables import MEMORY_METADATA, MEMORY_TABLE_NAMES
from sunil.db.autogenerate import FENCED_TABLES, include_name, include_object
from tests.unit.memory.factory import postgres_url, requires_postgres

pytestmark = [
    requires_postgres,
    # SQLAlchemy's reflector does not know pgvector's `vector` type and says so.
    # Expected and harmless HERE — this module compares column NAMES,
    # nullability and (for `embedding`) `format_type()` straight from the
    # catalogue, which is exactly the check reflection cannot do. Silenced so
    # the suite's output stays pristine and a real warning is visible.
    pytest.mark.filterwarnings("ignore:Did not recognize type 'vector':Warning"),
]

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "sunil"
    / "db"
    / "alembic"
    / "versions"
    / "0005_memory_and_entities.py"
)


def _load_migration():
    spec = importlib.util.spec_from_file_location("memory_migration_0005", MIGRATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sync_url() -> str:
    url = postgres_url()
    assert url is not None
    return url


@pytest_asyncio.fixture
async def migrated():
    """A SYNC engine with `upgrade()` applied to an empty schema.

    Sync on purpose: Alembic's `Operations` API is synchronous, and this test is
    about DDL, not about the async provider.
    """
    engine = create_engine(_sync_url(), future=True)
    module = _load_migration()
    with engine.begin() as conn:
        # An EMPTY schema — the fresh-deploy case. Dropping first is what makes
        # "this revision creates everything it needs" a claim and not a hope.
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context):
            module.upgrade()
    try:
        yield engine
    finally:
        with engine.begin() as conn:
            conn.execute(text("DROP SCHEMA public CASCADE"))
            conn.execute(text("CREATE SCHEMA public"))
        engine.dispose()


def test_the_revision_creates_every_table_the_provider_uses(migrated) -> None:
    created = set(inspect(migrated).get_table_names())

    assert set(MEMORY_TABLE_NAMES) <= created


def test_migration_columns_match_the_metadata(migrated) -> None:
    """Name-for-name and nullability-for-nullability, on every table."""
    reflected = MetaData()
    reflected.reflect(bind=migrated, only=list(MEMORY_TABLE_NAMES))

    for name in MEMORY_TABLE_NAMES:
        declared = MEMORY_METADATA.tables[name]
        live = reflected.tables[name]
        assert set(live.columns.keys()) == set(declared.columns.keys()), name
        for column in declared.columns:
            assert live.columns[column.name].nullable == column.nullable, (
                f"{name}.{column.name} nullability"
            )


def test_memories_privacy_has_no_server_default(migrated) -> None:
    """C3 §2: `privacy` is REQUIRED with no default (§26.9). A creation path that
    omits a privacy label must FAIL, not mint a row that reads as `internal` —
    the central-memory lesson of 2026-08-17, applied to the field where getting
    it wrong means confidential content in a prompt to a non-local model."""
    columns = {c["name"]: c for c in inspect(migrated).get_columns("memories")}

    assert columns["privacy"]["default"] is None
    assert columns["privacy"]["nullable"] is False


def test_the_embedding_column_is_a_vector_of_the_embedder_width(migrated) -> None:
    """The one number that must agree between the schema and
    `core/memory/embedding.py`. The migration hard-codes it (a revision must not
    change meaning when application code does), so something has to compare
    them, and this is it."""
    with migrated.begin() as conn:
        rendered = conn.execute(
            text(
                "SELECT format_type(atttypid, atttypmod) FROM pg_attribute "
                "WHERE attrelid = 'memories'::regclass AND attname = 'embedding'"
            )
        ).scalar_one()

    assert rendered == f"vector({EMBEDDING_DIM})"


def test_the_vector_index_uses_the_cosine_operator_class(migrated) -> None:
    """The provider ranks with `<=>` (cosine). An HNSW index built for L2 would
    simply never be used — a performance bug with no symptom until someone
    measures."""
    with migrated.begin() as conn:
        definition = conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE indexname = 'ix_memories_embedding_hnsw'")
        ).scalar_one()

    assert "hnsw" in definition
    assert "vector_cosine_ops" in definition


def test_the_scope_and_dupe_indexes_exist(migrated) -> None:
    """The vector index only ranks what the scope filter and the §4a duplicate
    probe have already selected, so these two are not optional."""
    names = {index["name"] for index in inspect(migrated).get_indexes("memories")}

    assert {"ix_memories_scope", "ix_memories_dupe"} <= names


def test_entity_links_have_no_foreign_key_into_the_entity_tables(migrated) -> None:
    """C3 §3 makes entity ids OPAQUE to the provider, with resolution (and
    `MemoryScopeError`) in the memory service before any vendor call. A FK here
    would move that failure to the write — an unresolvable entity would come
    back as a lost memory rather than a caller bug — and would refuse to
    remember anything about an entity whose row does not exist yet."""
    targets = {
        fk["referred_table"]
        for fk in inspect(migrated).get_foreign_keys("memory_entity_links")
    }

    assert targets == {"memories"}


def test_the_revision_refuses_to_run_on_a_non_postgres_dialect() -> None:
    """"Postgres-only, and it says so loudly." A revision that quietly created a
    memory schema without the embedding column would leave a deployment where
    every write succeeds and every recall returns nothing."""
    module = _load_migration()
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        context = MigrationContext.configure(conn)
        with Operations.context(context), pytest.raises(RuntimeError) as err:
            module.upgrade()

    assert "sqlite" in str(err.value)


# --------------------------------------------------------------------------- #
# The autogenerate fence — the other half of "owned by a hand-written revision"
# --------------------------------------------------------------------------- #
def test_every_memory_table_is_fenced_out_of_autogenerate() -> None:
    """`core/memory/tables.py` is on a private MetaData, so `Base.metadata` has
    none of these while every deployed database has all five. Unfenced, the next
    autogenerate emits `op.drop_table("memories")` — a silent DROP of what the
    assistant remembers."""
    assert set(MEMORY_TABLE_NAMES) <= FENCED_TABLES

    for name in MEMORY_TABLE_NAMES:
        assert include_name(name, "table", {"schema_name": None}) is False
        assert include_object(None, name, "table", True, None) is False


def test_the_fence_still_lets_spine_tables_through() -> None:
    """A fence that excluded everything would make autogenerate useless while
    looking like it worked."""
    for name in ("tasks", "audit_events", "tool_calls", "users", "messages"):
        assert include_name(name, "table", {"schema_name": None}) is True
