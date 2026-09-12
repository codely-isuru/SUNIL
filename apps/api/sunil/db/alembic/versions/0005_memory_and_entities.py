"""Long-term memory (pgvector) and the custom entity schema — Stream C.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-12

Parent is ``0004``, the single head at the time of writing (``alembic heads`` →
``0004 (head)``). A linear history has one answer to "what does ``head`` mean",
and the wave-1 lesson recorded on ``20260911_1200_d4_approvals_table.py`` is
that a second head makes ``alembic upgrade head`` ambiguous and a fresh
deployment unmigratable. Nothing here branches.

Five tables, all owned by THIS revision and fenced out of autogenerate
(``db/autogenerate.py``): their one declaration is ``core/memory/tables.py`` on
a private ``MEMORY_METADATA``, deliberately absent from ``Base.metadata``. The
fence is the other half — without it the next autogenerate would emit
``op.drop_table`` for every one of them, because the comparison would see them
in the database and not in the metadata.

**Postgres-only, and it says so loudly.** ``memories.embedding`` is
``vector(1536)`` and recall is a ``<=>`` cosine query. ADR-001's "one portable
schema" bought SQLite for unit tests; it cannot buy a vector index, so this
revision refuses to run on anything but PostgreSQL rather than creating a
schema that silently lacks the column's whole point. The memory suite skips
loudly on a machine without Postgres for the same reason
(``tests/unit/memory/factory.py``).

**``CREATE EXTENSION vector``** is issued here with ``IF NOT EXISTS``. The
Compose image (``pgvector/pgvector:0.8.6-pg17``) already creates it from
``infra/postgres/init/01-init-databases.sh``, but a migration that assumed the
init script had run would fail on any database created another way — a restored
dump, a managed instance, a developer's own ``createdb``. Creating an extension
needs superuser or the ``pg_database_owner`` role; on a managed Postgres where
the app role has neither, the operator must create it once by hand, and the
error this raises names the statement to run.

**Index choice.** HNSW with ``vector_cosine_ops``, matching the provider's
``<=>`` operator — an index built for a different operator class is not used and
its absence is invisible until someone measures. The btree indexes carry the
scope filter and the §4a duplicate probe; the vector index only ranks what
survives them, which is why the scope index is not optional.

**Downgrade drops the tables and NOT the extension.** Another schema may be
using ``vector``, and a downgrade that removed it would break something this
revision never created.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.types import UserDefinedType

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

#: Kept in sync with ``core/memory/embedding.EMBEDDING_DIM`` by
#: ``tests/unit/memory/test_migration_matches_tables.py``. Not imported: a
#: migration that changes meaning when application code changes is not a
#: migration — the DDL an applied revision ran must stay readable in the file.
EMBEDDING_DIM = 1536

_TABLES = ("memory_entity_links", "memories", "people", "projects", "clients")


class _Vector(UserDefinedType):
    """``vector(n)``, declared locally so this revision's DDL is self-contained.

    Deliberately NOT imported from ``core/memory/tables.py``: a migration that
    changes meaning when application code changes is not a migration. The DDL an
    applied revision ran must stay readable in the file, years later, with the
    application at any version.
    """

    cache_ok = True

    def __init__(self, dimension: int) -> None:
        self.dimension = dimension

    def get_col_spec(self, **_: object) -> str:
        return f"vector({self.dimension})"


def _require_postgres() -> None:
    dialect = op.get_bind().dialect.name
    if dialect != "postgresql":
        raise RuntimeError(
            f"revision 0005 creates a pgvector `vector({EMBEDDING_DIM})` column and an "
            f"HNSW index; the connected database is {dialect!r}. SUNIL's deployed "
            "target is PostgreSQL 17 + pgvector (ARCHITECTURE_V2 §1). Refusing to "
            "create a memory schema that cannot store an embedding."
        )


def upgrade() -> None:
    _require_postgres()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # -- the custom entity schema (ADR-030: entities stay ours) ------------- #
    op.create_table(
        "clients",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key", sa.String(128), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_clients_status"),
    )
    op.create_table(
        "projects",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # C3 §3 linkage point 2: `MemoryScope(kind="project", id="pda")` names
        # THIS, and the memory service resolves it to `projects.id` before any
        # vendor call.
        sa.Column("key", sa.String(128), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        # RESTRICT, not CASCADE: deleting a client must not silently delete the
        # projects whose history the owner is asking about.
        sa.Column(
            "client_id",
            sa.String(64),
            sa.ForeignKey("clients.id", ondelete="RESTRICT"),
            nullable=True,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "status IN ('active', 'paused', 'archived')", name="ck_projects_status"
        ),
    )
    op.create_index("ix_projects_client", "projects", ["client_id"])

    op.create_table(
        "people",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("key", sa.String(128), nullable=False, unique=True),
        sa.Column("full_name", sa.String(255), nullable=False),
        # Nullable and NOT unique — see `core/memory/tables.py`.
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("role", sa.String(128), nullable=True),
        sa.Column(
            "client_id",
            sa.String(64),
            sa.ForeignKey("clients.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
    )
    op.create_index("ix_people_client", "people", ["client_id"])
    op.create_index("ix_people_email", "people", ["email"])

    # -- long-term memory --------------------------------------------------- #
    op.create_table(
        "memories",
        sa.Column("id", sa.String(64), primary_key=True),
        # C3 §5 recall step 3's tiebreaker: "real providers use their monotonic
        # insert sequence, because `created_at` alone is not a total order".
        sa.Column("seq", sa.BigInteger(), nullable=False, unique=True),
        sa.Column("scope_user_id", sa.String(128), nullable=False),
        sa.Column("scope_kind", sa.String(32), nullable=False),
        # NULL for `kind="user"` — every comparison on it is IS NOT DISTINCT FROM.
        sa.Column("scope_id", sa.String(128), nullable=True),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_key", sa.Text(), nullable=False),
        sa.Column("memory_type", sa.String(32), nullable=False),
        # NO server default (C3 §2: "REQUIRED, no default"; central-memory lesson
        # 2026-08-17). A write path that omitted the label must fail loudly
        # rather than mint a row that reads as `internal`.
        sa.Column("privacy", sa.String(32), nullable=False),
        sa.Column("source_request_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        # `WriteRules.ttl_days` resolved to an instant; NULL = keep until
        # superseded (C3 §2).
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        # Nullable: content that tokenises to nothing embeds to the zero vector,
        # whose cosine distance is undefined. Such a row is stored and is never
        # a recall candidate — honest, since it could not have matched anything.
        sa.Column("embedding", _Vector(EMBEDDING_DIM), nullable=True),
        sa.CheckConstraint(
            "privacy IN ('public', 'internal', 'confidential', 'local_only')",
            name="ck_memories_privacy",
        ),
        sa.CheckConstraint(
            "memory_type IN ('episodic', 'fact', 'preference', 'decision')",
            name="ck_memories_memory_type",
        ),
        sa.CheckConstraint(
            "scope_kind IN ('conversation', 'user', 'entity', 'project')",
            name="ck_memories_scope_kind",
        ),
    )
    op.create_index(
        "ix_memories_scope", "memories", ["scope_user_id", "scope_kind", "scope_id"]
    )
    op.create_index(
        "ix_memories_dupe",
        "memories",
        ["scope_user_id", "scope_kind", "scope_id", "content_key"],
    )
    op.create_index("ix_memories_seq", "memories", ["seq"])
    # HNSW with `vector_cosine_ops`, matching the provider's `<=>` operator. An
    # index built for a different operator class is simply not used, and its
    # absence is invisible until someone measures.
    op.execute(
        "CREATE INDEX ix_memories_embedding_hnsw ON memories "
        "USING hnsw (embedding vector_cosine_ops)"
    )

    op.create_table(
        "memory_entity_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        # CASCADE: a link to a deleted memory is not a link, and an orphan would
        # make entity-scoped recall return nothing, repeatedly.
        sa.Column(
            "memory_id",
            sa.String(64),
            sa.ForeignKey("memories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("entity_id", sa.String(128), nullable=False),
        # Preserves `entity_refs` ORDER — C3 §3 persists them verbatim.
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "entity_type IN ('client', 'project', 'person')", name="ck_links_entity_type"
        ),
        sa.UniqueConstraint("memory_id", "position", name="uq_links_memory_position"),
        # NO foreign key into clients/projects/people, on purpose: C3 §3 makes
        # entity ids opaque to the provider and puts resolution in the memory
        # service, which raises `MemoryScopeError` BEFORE any vendor call. A FK
        # would turn a caller bug into a lost memory, and would refuse to
        # remember anything about an entity whose row does not exist yet.
    )
    op.create_index("ix_links_entity", "memory_entity_links", ["entity_type", "entity_id"])
    op.create_index("ix_links_memory", "memory_entity_links", ["memory_id"])


def downgrade() -> None:
    _require_postgres()
    for table in _TABLES:
        op.drop_table(table)
    # The `vector` extension is deliberately NOT dropped: another schema may be
    # using it, and a downgrade must not remove something it did not create.
