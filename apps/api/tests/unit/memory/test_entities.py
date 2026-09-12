"""C3 §3 linkage point 2 — scope resolution, before any vendor call.

> `MemoryScope(kind="project", id="pda")` is resolved by the memory *service*
> (SUNIL code) to the project's entity id before hitting the provider; the
> provider only ever sees resolved ids. **Unknown ids raise `MemoryScopeError`
> before any vendor call.**

Two properties are being bought. The provider never sees a human key, so it
cannot guess; and an unresolvable id is a CALLER BUG that surfaces as itself —
not as a memory that silently went nowhere, which is what an unresolved key
would produce (a scope nothing else ever writes to or reads from, forever).
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from sunil.core.memory.entities import EntityResolver, upsert_entity
from sunil.core.memory.provider import MemoryScope, MemoryScopeError
from tests.unit.memory import factory
from tests.unit.memory.factory import requires_postgres

pytestmark = requires_postgres


@pytest_asyncio.fixture
async def engine():
    url = factory.postgres_url()
    assert url is not None
    async for made in factory.engine_for(url):
        yield made


@pytest_asyncio.fixture
async def seeded(engine):
    await upsert_entity(engine, "client", key="client_x", name="Client X")
    await upsert_entity(engine, "project", key="pda", name="PDA Learning")
    await upsert_entity(engine, "person", key="mark", name="Mark")
    return EntityResolver(engine)


async def test_a_project_key_resolves_to_the_row_id(seeded, engine) -> None:
    resolved = await seeded.resolve(MemoryScope(user_id="owner", kind="project", id="pda"))

    assert resolved.kind == "project"
    assert resolved.id != "pda"  # a row id, not the human key
    assert resolved.user_id == "owner"


async def test_resolution_is_idempotent_on_an_already_resolved_id(seeded) -> None:
    """A scope resolved twice must not resolve to nothing the second time —
    otherwise a continuation replaying a stored scope would fail."""
    once = await seeded.resolve(MemoryScope(user_id="owner", kind="project", id="pda"))
    twice = await seeded.resolve(once)

    assert twice == once


async def test_an_entity_scope_resolves_against_all_three_tables(seeded) -> None:
    """`kind="entity"` does not say WHICH kind of entity, so the key is looked up
    across clients, projects and people."""
    for key in ("client_x", "pda", "mark"):
        resolved = await seeded.resolve(
            MemoryScope(user_id="owner", kind="entity", id=key)
        )
        assert resolved.id != key


async def test_an_unknown_key_raises_memory_scope_error(seeded) -> None:
    """The whole point of the seam: a caller bug, raised BEFORE any vendor call,
    never retried. The alternative is a memory filed under a scope nothing will
    ever read."""
    with pytest.raises(MemoryScopeError) as err:
        await seeded.resolve(MemoryScope(user_id="owner", kind="project", id="does-not-exist"))

    assert "does-not-exist" in str(err.value)


async def test_conversation_and_user_scopes_pass_through_untouched(seeded) -> None:
    """Only entity-bearing scopes are resolved. A conversation id is already an
    id, and a `kind="user"` scope has no id at all — resolving either would
    invent a lookup that must always fail."""
    conversation = MemoryScope(user_id="owner", kind="conversation", id="conv-1")
    user = MemoryScope(user_id="owner", kind="user", id=None)

    assert await seeded.resolve(conversation) == conversation
    assert await seeded.resolve(user) == user


async def test_a_project_scope_with_no_id_is_a_caller_bug(seeded) -> None:
    """C3 §2: `id` is "None only for kind='user'". A `kind="project"` scope
    without one names no project."""
    with pytest.raises(MemoryScopeError):
        await seeded.resolve(MemoryScope(user_id="owner", kind="project", id=None))


async def test_upsert_is_idempotent_on_the_key(engine) -> None:
    """Seeding an entity twice must not mint a second row with the same key —
    two rows for one client is two memory scopes for one client."""
    first = await upsert_entity(engine, "client", key="acme", name="Acme")
    second = await upsert_entity(engine, "client", key="acme", name="Acme Pty Ltd")

    assert first == second

    resolver = EntityResolver(engine)
    resolved = await resolver.resolve(MemoryScope(user_id="owner", kind="entity", id="acme"))
    assert resolved.id == first
