"""C3 §3 linkage point 2 — scope resolution, and the custom entity schema's
read/write helpers.

> `MemoryScope(kind="project", id="pda")` is resolved by the memory *service*
> (SUNIL code) to the project's entity id before hitting the provider; the
> provider only ever sees resolved ids. Unknown ids raise `MemoryScopeError`
> before any vendor call.

Why this lives on the SERVICE side of the seam and not in the provider: a vendor
that resolved keys would have to know the entity schema, which ADR-030 keeps
ours. It would also turn an unresolvable key into a *write that went somewhere*
— a scope nothing else ever reads — instead of the caller bug it is. Raising
before the vendor call is the difference between "you named a project that does
not exist" and "the assistant quietly forgot".

`MemoryScopeError` is deliberately NOT caught by `MemoryService.recall`'s
degrade path (see that module): degrading it would hide a code defect behind
"memory was slow".
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine

from sunil.core.memory.provider import (
    MemoryScope,
    MemoryScopeError,
    MemoryUnavailableError,
)
from sunil.core.memory.tables import ENTITY_TABLES

EntityType = Literal["client", "project", "person"]

#: The scope kinds whose `id` names an ENTITY and therefore needs resolving.
#: `conversation` ids are already ids; `user` scopes have no id at all.
RESOLVABLE_KINDS = frozenset({"entity", "project"})

#: `kind="project"` names a project specifically; `kind="entity"` does not say
#: which kind, so it is looked up across all three tables.
_KIND_TABLES: dict[str, tuple[EntityType, ...]] = {
    "project": ("project",),
    "entity": ("client", "project", "person"),
}


class EntityResolver:
    """Human key → row id, for the scopes that carry one.

    Resolution is idempotent: a scope whose id is ALREADY a row id resolves to
    itself. Without that, a continuation replaying a stored scope (ADR-031's
    resume path) would fail the second time — the key is gone by then, because
    the first resolution replaced it.
    """

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def resolve(self, scope: MemoryScope) -> MemoryScope:
        if scope.kind not in RESOLVABLE_KINDS:
            return scope
        if scope.id is None:
            raise MemoryScopeError(
                f"a {scope.kind!r} scope names no entity (id is None). C3 §2: `id` is "
                "None only for kind='user'."
            )

        try:
            async with self._engine.connect() as conn:
                for entity_type in _KIND_TABLES[scope.kind]:
                    table = ENTITY_TABLES[entity_type]
                    row = (
                        await conn.execute(
                            select(table.c.id).where(
                                (table.c.key == scope.id) | (table.c.id == scope.id)
                            )
                        )
                    ).first()
                    if row is not None:
                        return scope.model_copy(update={"id": row.id})
        except SQLAlchemyError as exc:
            # A lookup that could not run is not "unknown id" — conflating the
            # two would turn an outage into a caller bug and stop the turn
            # degrading (C3 §2).
            raise MemoryUnavailableError(
                f"the entity schema could not be read: {type(exc).__name__}"
            ) from exc

        raise MemoryScopeError(
            f"no {scope.kind} matches {scope.id!r}. C3 §3: an unresolvable scope id is "
            "a caller bug, raised BEFORE any vendor call and never retried — a memory "
            "filed under an invented scope is a memory nothing will ever read."
        )


async def upsert_entity(
    engine: AsyncEngine,
    entity_type: EntityType,
    *,
    key: str,
    name: str,
    **fields: object,
) -> str:
    """Create-or-return an entity row, keyed on its stable human `key`.

    Idempotent on `key` deliberately: two rows for one client is two memory
    scopes for one client, and the second would appear to have no history.
    Existing rows are returned UNCHANGED rather than updated — renaming an
    entity is an edit someone should make on purpose, not a side effect of
    seeding it again.
    """
    table = ENTITY_TABLES[entity_type]
    name_column = "full_name" if entity_type == "person" else "name"
    now = datetime.now(UTC)

    async with engine.begin() as conn:
        existing = (
            await conn.execute(select(table.c.id).where(table.c.key == key))
        ).first()
        if existing is not None:
            return existing.id

        entity_id = str(uuid4())
        await conn.execute(
            table.insert().values(
                id=entity_id,
                key=key,
                created_at=now,
                updated_at=now,
                **{name_column: name},
                **fields,
            )
        )
        return entity_id
