"""The reaper's deletion leg, against a real database.

`test_reaper.py` grades the runner; this grades the SQL the runner calls —
`PgVectorMemoryProvider.delete_expired()`. Postgres-gated for this suite's
standing reason: `memories` has a `vector(1536)` column, so there is no SQLite
leg to be falsely green on.

Four properties, each one a way this could be wrong in production:

* it deletes what recall already hides (`expires_at < now`), and nothing else;
* a NULL `expires_at` — "keep until superseded" — is never touched;
* it is idempotent, so the runner's containment is safe to retry;
* the `memory_entity_links` children go with the row, via the schema's
  ON DELETE CASCADE, so a reap cannot leave orphan links pointing at nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest_asyncio
from sqlalchemy import func, select

from sunil.core.memory.provider import EntityRef, MemoryItem, MemoryScope, WriteRules
from sunil.core.memory.reaper import MemoryReaper
from sunil.core.memory.tables import memories_table, memory_entity_links_table
from tests.unit.memory import factory
from tests.unit.memory.factory import requires_postgres

pytestmark = requires_postgres

SCOPE = MemoryScope(user_id="owner", kind="conversation", id="conv-1")
FIXED_NOW = datetime(2026, 9, 12, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def engine():
    url = factory.postgres_url()
    assert url is not None
    async for made in factory.engine_for(url):
        yield made


def item(content: str, *, refs: list[EntityRef] | None = None) -> MemoryItem:
    return MemoryItem(
        content=content,
        memory_type="fact",
        privacy="internal",
        source_request_id="req-1",
        entity_refs=refs or [],
    )


async def counts(engine) -> tuple[int, int]:
    async with engine.connect() as conn:
        memories = (
            await conn.execute(select(func.count()).select_from(memories_table))
        ).scalar_one()
        links = (
            await conn.execute(
                select(func.count()).select_from(memory_entity_links_table)
            )
        ).scalar_one()
    return memories, links


async def test_expired_rows_are_deleted_and_live_ones_are_not(engine) -> None:
    """The whole point of S2-C §7.4: what recall filters, the reaper removes.
    A TTL the owner set is a promise the content goes away — a filter alone
    leaves it readable to a backup, a psql session or a future feature."""
    provider = factory.make_provider(engine, clock=lambda: FIXED_NOW)
    await provider.write(
        item("expired one"),
        WriteRules(capture="redacted_full", ttl_days=1),
        scope=SCOPE,
        audit_event_id="audit-1",
    )
    await provider.write(
        item("still live"),
        WriteRules(capture="redacted_full", ttl_days=30),
        scope=SCOPE,
        audit_event_id="audit-2",
    )
    await provider.write(
        item("kept until superseded"),
        WriteRules(capture="redacted_full"),  # ttl_days=None → expires_at NULL
        scope=SCOPE,
        audit_event_id="audit-3",
    )

    later = factory.make_provider(engine, clock=lambda: FIXED_NOW + timedelta(days=2))
    deleted = await later.delete_expired()

    assert deleted == 1
    async with engine.connect() as conn:
        rows = (await conn.execute(select(memories_table.c.content))).fetchall()
    assert sorted(row.content for row in rows) == ["kept until superseded", "still live"]


async def test_the_delete_is_idempotent(engine) -> None:
    """A second pass over the same rows matches nothing — which is what makes the
    runner's "swallow the error and try again next tick" containment safe."""
    provider = factory.make_provider(engine, clock=lambda: FIXED_NOW)
    await provider.write(
        item("expired"),
        WriteRules(capture="redacted_full", ttl_days=1),
        scope=SCOPE,
        audit_event_id="audit-1",
    )
    later = factory.make_provider(engine, clock=lambda: FIXED_NOW + timedelta(days=2))

    assert await later.delete_expired() == 1
    assert await later.delete_expired() == 0


async def test_entity_links_go_with_the_memory(engine) -> None:
    """`memory_entity_links` cascades. An orphan link would make entity-scoped
    recall join to a memory that no longer exists, repeatedly and forever."""
    provider = factory.make_provider(engine, clock=lambda: FIXED_NOW)
    await provider.write(
        item("expired", refs=[EntityRef(entity_type="project", entity_id="pda")]),
        WriteRules(capture="redacted_full", ttl_days=1),
        scope=SCOPE,
        audit_event_id="audit-1",
    )
    assert await counts(engine) == (1, 1)

    later = factory.make_provider(engine, clock=lambda: FIXED_NOW + timedelta(days=2))
    await later.delete_expired()

    assert await counts(engine) == (0, 0)


async def test_the_runner_drives_the_real_store(engine) -> None:
    """`ExpiredMemoryStore` is a structural Protocol, so a signature drift
    between the runner and the provider would only surface in production, on an
    hourly timer, on the path that destroys data. This is that wiring, end to
    end — and the audit row the batch mints carries the count alone."""
    provider = factory.make_provider(engine, clock=lambda: FIXED_NOW)
    for n in range(3):
        await provider.write(
            item(f"expired {n}"),
            WriteRules(capture="redacted_full", ttl_days=1),
            scope=SCOPE,
            audit_event_id=f"audit-{n}",
        )
    rows: list[dict] = []

    class Sink:
        async def record_memory_reap(self, **payload) -> None:
            rows.append(payload)

    later = factory.make_provider(engine, clock=lambda: FIXED_NOW + timedelta(days=2))
    reaped = await MemoryReaper(later, audit_sink=Sink()).run_once()

    assert reaped == 3
    assert rows == [{"deleted": 3}]
    assert await counts(engine) == (0, 0)
