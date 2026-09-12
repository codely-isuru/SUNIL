"""The long-term memory schema and the CUSTOM entity schema (C3 §3, ADR-030).

One private `MetaData`, the pattern `core/approvals/table.py` established and
`db/autogenerate.py` fences: these tables are owned by a hand-written Alembic
revision, so autogenerate must neither create, alter nor drop them. They are
deliberately absent from `Base.metadata` — a second, ORM-shaped declaration of a
production table is how the approvals lane ended up with VARCHAR timestamps in
one place and TIMESTAMPTZ in the other.

Five tables:

* `memories` — the long-term store. Postgres-only: `embedding` is `vector(1536)`
  and recall is a `<=>` cosine query, neither of which SQLite has.
* `memory_entity_links` — C3 §3 linkage point 1, `MemoryItem.entity_refs`
  persisted so recall can filter by entity "without joining SUNIL tables" (the
  join here is to a child table of `memories` itself, not to `clients`).
* `clients`, `projects`, `people` — the custom entity schema (ADR-030: "entity
  schema stays custom", it is not a vendor's).

Three decisions a reviewer should check here specifically.

**1. `privacy` has no server default** (C3 §2: "REQUIRED, no default"; the same
rule C4 applies to `approvals.status`, and the central-memory lesson of
2026-08-17). A write path that omitted the label must fail loudly rather than
mint a row that reads as `internal`. The CHECK constraint bounds the column to
§26.9's four values, so an unknown label cannot be stored at all.

**2. `seq` is a monotonic identity, and it is the recall tiebreaker.** C3 §5
recall step 3 says it in as many words: "real providers use their monotonic
insert sequence, because `created_at` alone is not a total order". Two memories
written in the same millisecond would otherwise come back in planner order.

**3. `memory_entity_links` has NO foreign key into `clients`/`projects`/`people`,
on purpose.** C3 §3 makes entity ids OPAQUE to the provider and puts resolution
in the memory *service*, which raises `MemoryScopeError` for an unknown id
*before any vendor call*. A foreign key would move that failure to the write, so
an unresolvable entity would come back as a lost memory instead of a caller bug
— and it would make the provider refuse to remember anything about an entity
whose row has not been created yet, which is exactly the case a note about a new
client is.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.types import UserDefinedType

from sunil.core.memory.embedding import EMBEDDING_DIM

#: Private metadata — see the module docstring, and `db/autogenerate.py`.
MEMORY_METADATA = MetaData()

MEMORIES_TABLE = "memories"
LINKS_TABLE = "memory_entity_links"
CLIENTS_TABLE = "clients"
PROJECTS_TABLE = "projects"
PEOPLE_TABLE = "people"

#: Every table in this module, for the autogenerate fence and the migration test.
MEMORY_TABLE_NAMES = (
    MEMORIES_TABLE,
    LINKS_TABLE,
    CLIENTS_TABLE,
    PROJECTS_TABLE,
    PEOPLE_TABLE,
)

PRIVACY_VALUES = ("public", "internal", "confidential", "local_only")
MEMORY_TYPE_VALUES = ("episodic", "fact", "preference", "decision")
ENTITY_TYPE_VALUES = ("client", "project", "person")


class Vector(UserDefinedType):
    """The pgvector `vector(n)` column type, in ~15 lines.

    Hand-rolled rather than `pip install pgvector`: `tests/unit/providers/
    test_runtime_dependencies.py` enforces that every third-party import is a
    declared runtime dependency, and adding a dependency to obtain a DDL string
    and a list-to-`'[…]'` serialiser is a poor trade. Everything else this layer
    needs (`<=>`) is an operator, which SQLAlchemy passes through as text.
    """

    cache_ok = True

    def __init__(self, dimension: int = EMBEDDING_DIM) -> None:
        self.dimension = dimension

    def get_col_spec(self, **_: Any) -> str:
        return f"vector({self.dimension})"

    def bind_processor(self, dialect: Any):
        def process(value: list[float] | None) -> str | None:
            if value is None:
                return None
            return "[" + ",".join(repr(float(item)) for item in value) + "]"

        return process

    def result_processor(self, dialect: Any, coltype: Any):
        def process(value: Any) -> list[float] | None:
            if value is None:
                return None
            if isinstance(value, list):
                return [float(item) for item in value]
            return [float(part) for part in str(value).strip("[]").split(",") if part]

        return process


memories_table = Table(
    MEMORIES_TABLE,
    MEMORY_METADATA,
    Column("id", String(64), primary_key=True),
    # The monotonic insert sequence — C3 §5 recall step 3's tiebreaker.
    Column("seq", BigInteger, nullable=False, autoincrement=True, unique=True),
    # The scope the write filed into (C3 §2, v1.1.0). `scope_id` is NULL for
    # `kind="user"`, which is why every comparison on it is IS NOT DISTINCT FROM.
    Column("scope_user_id", String(128), nullable=False),
    Column("scope_kind", String(32), nullable=False),
    Column("scope_id", String(128), nullable=True),
    Column("content", Text, nullable=False),
    # §4a's duplicate key: `content.strip()` compared case-insensitively. Stored
    # rather than computed per query so the duplicate probe is an index hit and
    # not a sequential scan with a function on every row.
    Column("content_key", Text, nullable=False),
    Column("memory_type", String(32), nullable=False),
    # NO server default — see the module docstring.
    Column("privacy", String(32), nullable=False),
    Column("source_request_id", String(128), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    # `WriteRules.ttl_days` resolved to an instant. NULL = keep until superseded.
    Column("expires_at", DateTime(timezone=True), nullable=True),
    # Nullable because a content that tokenises to nothing (punctuation only)
    # embeds to the zero vector, whose cosine distance is undefined. Such a row
    # is stored and is never a recall candidate, which is honest: it could not
    # have matched anything anyway.
    Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
    CheckConstraint(
        "privacy IN " + str(PRIVACY_VALUES), name="ck_memories_privacy"
    ),
    CheckConstraint(
        "memory_type IN " + str(MEMORY_TYPE_VALUES), name="ck_memories_memory_type"
    ),
    CheckConstraint(
        "scope_kind IN ('conversation', 'user', 'entity', 'project')",
        name="ck_memories_scope_kind",
    ),
    # The recall candidate filter, and the §4a duplicate probe.
    Index("ix_memories_scope", "scope_user_id", "scope_kind", "scope_id"),
    Index(
        "ix_memories_dupe", "scope_user_id", "scope_kind", "scope_id", "content_key"
    ),
    Index("ix_memories_seq", "seq"),
)

memory_entity_links_table = Table(
    LINKS_TABLE,
    MEMORY_METADATA,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column(
        "memory_id",
        String(64),
        # ON DELETE CASCADE: a link to a deleted memory is not a link, and an
        # orphan would make the entity-scoped recall return nothing, repeatedly.
        ForeignKey(f"{MEMORIES_TABLE}.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column("entity_type", String(32), nullable=False),
    Column("entity_id", String(128), nullable=False),
    # Preserves `entity_refs` ORDER — C3 §3 says they are persisted verbatim,
    # and a set would silently reorder what the caller wrote.
    Column("position", Integer, nullable=False),
    CheckConstraint(
        "entity_type IN ('client', 'project', 'person')", name="ck_links_entity_type"
    ),
    UniqueConstraint("memory_id", "position", name="uq_links_memory_position"),
    Index("ix_links_entity", "entity_type", "entity_id"),
    Index("ix_links_memory", "memory_id"),
)


def _entity_columns() -> list[Column]:
    """The three entity tables share an identity shape; only their body differs."""
    return [
        Column("id", String(64), primary_key=True),
        Column("created_at", DateTime(timezone=True), nullable=False),
        Column("updated_at", DateTime(timezone=True), nullable=False),
    ]


clients_table = Table(
    CLIENTS_TABLE,
    MEMORY_METADATA,
    *_entity_columns(),
    # The stable human handle a scope can be resolved from — `MemoryScope(
    # kind="entity", id="client_x")` in C3's own examples is this, not the row id.
    Column("key", String(128), nullable=False, unique=True),
    Column("name", String(255), nullable=False),
    Column("status", String(32), nullable=False, server_default="active"),
    Column("notes", Text, nullable=True),
    CheckConstraint("status IN ('active', 'archived')", name="ck_clients_status"),
)

projects_table = Table(
    PROJECTS_TABLE,
    MEMORY_METADATA,
    *_entity_columns(),
    # C3 §3 linkage point 2: `MemoryScope(kind="project", id="pda")` names THIS,
    # and the memory service resolves it to `projects.id` before the vendor call.
    Column("key", String(128), nullable=False, unique=True),
    Column("name", String(255), nullable=False),
    Column(
        "client_id",
        String(64),
        # RESTRICT, not CASCADE: deleting a client must not silently delete the
        # projects whose history the owner is asking about.
        ForeignKey(f"{CLIENTS_TABLE}.id", ondelete="RESTRICT"),
        nullable=True,
    ),
    Column("status", String(32), nullable=False, server_default="active"),
    Column("notes", Text, nullable=True),
    CheckConstraint(
        "status IN ('active', 'paused', 'archived')", name="ck_projects_status"
    ),
    Index("ix_projects_client", "client_id"),
)

people_table = Table(
    PEOPLE_TABLE,
    MEMORY_METADATA,
    *_entity_columns(),
    Column("key", String(128), nullable=False, unique=True),
    Column("full_name", String(255), nullable=False),
    # Nullable and NOT unique: two people can share a shared inbox, and a person
    # SUNIL knows of may have no email at all. A unique constraint here would
    # make the second such row an integrity error at write time.
    Column("email", String(320), nullable=True),
    Column("role", String(128), nullable=True),
    Column(
        "client_id",
        String(64),
        ForeignKey(f"{CLIENTS_TABLE}.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("notes", Text, nullable=True),
    Index("ix_people_client", "client_id"),
    Index("ix_people_email", "email"),
)

#: `entity_type` → the table that owns those ids. Used by the entity resolver,
#: which is SUNIL code on the service side of the seam (C3 §3).
ENTITY_TABLES = {
    "client": clients_table,
    "project": projects_table,
    "person": people_table,
}


def content_key(content: str) -> str:
    """C3 §4a's duplicate key: `content.strip()` compared case-insensitively.

    `casefold`, not `lower`: `lower()` leaves 'ß' and 'ẞ' distinct, so two
    German-language memories that ARE the same content would append twice and
    the widening rule would never see them as duplicates.
    """
    return content.strip().casefold()
