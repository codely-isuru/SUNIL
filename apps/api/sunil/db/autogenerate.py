"""Autogenerate fences — the tables Alembic's comparison must not touch.

Wave-1 ruling R2 (`docs/tasks/integration-w1-rulings.md`), applied in the wave-2
wiring round. `db/alembic/env.py` compares `Base.metadata` against the live
database; anything present on one side and absent from the other becomes an
operation in the generated revision. `approvals` must be on neither side of that
comparison, because the table is **owned elsewhere**:

* its one true declaration is `core/approvals/table.py`, on a private
  `APPROVALS_METADATA` (a recorded Stream D isolation decision) — invisible to
  autogenerate by design;
* it is created and altered by Stream D's hand-written revisions
  (`20260911_1200_d4_approvals_table.py`).

Without the fence, deleting the false ORM `Approval` class would make the next
autogenerate emit `op.drop_table("approvals")` — a silent DROP of an
audit-bearing table — and keeping the class would make it emit ALTERs toward a
VARCHAR-timestamp shape no deployment runs. The fence is what makes the deletion
safe; the two live together and neither is complete alone.

Kept in its own module rather than inline in `env.py` because `env.py` runs
migrations on import and therefore cannot be imported by a test. The property is
security-adjacent (an audit table's continued existence), so it is pinned by
`tests/unit/test_alembic_autogenerate_fence.py`.
"""

from __future__ import annotations

from typing import Any

#: Tables owned by hand-written revisions. Autogenerate neither creates, alters
#: nor drops these — on either side of the comparison. Extending this set is a
#: reviewed code change, and the reviewer's question is "does a hand-written
#: revision own this table's whole lifecycle?".
#:
#: Stream C's five (`0005_memory_and_entities`) answer it the same way `approvals`
#: does: their one declaration is `core/memory/tables.py` on a private
#: `MEMORY_METADATA`, absent from `Base.metadata`. Without the fence the next
#: autogenerate would emit `op.drop_table` for all five — including `memories`,
#: whose rows are the thing the assistant remembers. `memories.embedding` is also
#: a `vector(1536)` column that Alembic's comparison cannot render, so an
#: unfenced ALTER would be unreviewable as well as wrong.
FENCED_TABLES: frozenset[str] = frozenset(
    {
        "approvals",
        "memories",
        "memory_entity_links",
        "clients",
        "projects",
        "people",
    }
)


def include_name(name: str | None, type_: str, parent_names: dict[str, Any]) -> bool:
    """Alembic's reflection-side filter — the DROP half.

    Scoped to `type_ == "table"` deliberately: `include_name` is also asked about
    schemas and columns, and a column named `approvals` on some other table is
    not this table.
    """
    if type_ == "table" and name in FENCED_TABLES:
        return False
    return True


def include_object(
    obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any
) -> bool:
    """Alembic's metadata-side filter — the CREATE/ALTER half.

    Belt and braces today (nothing in `Base.metadata` declares `approvals` since
    R2 step 1), and the guard that matters tomorrow: a future ORM class
    re-declaring the table would otherwise be silently taken as authoritative
    over the deployed shape.
    """
    if type_ == "table" and name in FENCED_TABLES:
        return False
    return True
