"""R13 — the `EntityResolver` wired into `MemoryService`, and R12 rule 3's
registry → table materialisation on the write path.

Stream C built the resolver and left it unwired: a `MemoryScope(kind="project",
id="pda")` reached the provider with the human key still in it, so memories were
filed under the literal string "pda" and C3 §3's "the provider only ever sees
resolved ids" was true of nothing. These are the tests owed with that wiring
(R13 item 6), plus R12 rule 3's lazy upsert, which lands in the same parcel.

Two postures are asserted over and over here, because they are the whole point:

* **recall degrades, write surfaces.** An entity schema that cannot be read is
  `MemoryUnavailableError` — recall returns `degraded=True, reason="unavailable"`
  and the turn continues; a write raises, because a lost write must be visible
  (C3 §4).
* **`MemoryScopeError` never degrades, on either path.** It is a caller bug —
  "you named a project that does not exist" — and degrading it would file it
  under "memory was slow" (C3 §3/§4).

Where a database is genuinely required the test is Postgres-gated exactly like
the rest of this suite; the DB-FREE half deliberately uses the REAL
`EntityResolver` over an unreachable engine, because the error translation it
performs (`SQLAlchemyError` → `MemoryUnavailableError`) is the thing under test
and a double that raised the translated error directly would prove nothing.
"""

from __future__ import annotations

import asyncio

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine

from sunil.core.memory.entities import EntityResolver, upsert_entity
from sunil.core.memory.provider import (
    MemoryItem,
    MemoryScope,
    MemoryScopeError,
    MemoryUnavailableError,
    WriteRules,
)
from sunil.core.memory.service import MemoryService
from sunil.core.memory.tables import ENTITY_TABLES
from sunil.core.registry.loader import ProjectDefinition
from tests.fakes.fake_memory_provider import FakeMemoryProvider
from tests.unit.memory import factory
from tests.unit.memory.factory import DEAD_URL, requires_postgres

PDA = MemoryScope(user_id="owner", kind="project", id="pda")
CONV = MemoryScope(user_id="owner", kind="conversation", id="conv-1")


def item(content: str = "the winch course runs in October") -> MemoryItem:
    return MemoryItem(
        content=content,
        memory_type="fact",
        privacy="internal",
        source_request_id="req-1",
    )


RULES = WriteRules(capture="redacted_full")


class RecordingSink:
    """The audit sink, capturing the SCOPE it was given — R13 item 3's property
    is about which scope the row names, so the row's scope is what is kept."""

    def __init__(self) -> None:
        self.scopes: list[MemoryScope] = []

    async def record_memory_write(self, *, scope: MemoryScope, item: MemoryItem) -> str:
        del item
        self.scopes.append(scope)
        return f"audit-{len(self.scopes)}"


class NeverCalledProvider(FakeMemoryProvider):
    """A vendor that fails the test if it is reached at all.

    C3 §3's rule is not "an unresolvable scope eventually errors", it is that it
    is raised **before any vendor call** — a write that reached the provider and
    then failed could still have left a row behind.
    """

    async def write(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("the provider was called with an unresolved scope")

    async def recall(self, *args, **kwargs):  # type: ignore[override]
        raise AssertionError("the provider was called with an unresolved scope")


def dead_resolver() -> EntityResolver:
    """A resolver whose entity schema is unreachable — C3 §3's "outage", real
    rather than mocked (the same device `factory.dead_provider()` uses)."""
    return EntityResolver(
        create_async_engine(DEAD_URL, connect_args={"connect_timeout": 1})
    )


# --------------------------------------------------------------------------- #
# No database needed: the default, the two error postures, and the ONE budget
# --------------------------------------------------------------------------- #
async def test_no_resolver_leaves_every_existing_call_site_unchanged() -> None:
    """R13 item 1 — `resolver` is keyword-only with a `None` default, so the
    fake-wired app and the frozen C3 contract suite keep working untouched: with
    no resolver the scope reaches the provider exactly as given."""
    provider = FakeMemoryProvider()
    service = MemoryService(provider, audit_sink=RecordingSink())

    await service.write(item(), RULES, scope=PDA)

    assert [scope.id for scope, _ in provider.items] == ["pda"]


async def test_an_unresolvable_scope_raises_through_recall_before_the_vendor() -> None:
    """`kind="project"` with no id is a caller bug the resolver names, and it
    must NOT arrive as `degraded=True` — a degraded recall tells the owner memory
    was down, when in fact the code asked for a scope that cannot exist."""
    service = MemoryService(NeverCalledProvider(), resolver=dead_resolver())

    with pytest.raises(MemoryScopeError):
        await service.recall("winch", MemoryScope(user_id="owner", kind="project"))


async def test_an_unresolvable_scope_raises_through_write_before_the_audit_row() -> None:
    """R13 item 3's second half: a write that cannot resolve writes NO audit row.
    The trail must not record a memory that never happened."""
    sink = RecordingSink()
    service = MemoryService(
        NeverCalledProvider(), audit_sink=sink, resolver=dead_resolver()
    )

    with pytest.raises(MemoryScopeError):
        await service.write(
            item(), RULES, scope=MemoryScope(user_id="owner", kind="project")
        )

    assert sink.scopes == []


async def test_an_entity_schema_outage_degrades_recall() -> None:
    """The resolver's `MemoryUnavailableError` joins the EXISTING degrade path —
    same reason token, because from the turn's point of view "the entity tables
    are unreadable" and "the vector store is unreadable" are one fact: memory is
    unavailable, answer without it."""
    service = MemoryService(
        NeverCalledProvider(), resolver=dead_resolver(), budget_s=30.0
    )

    outcome = await service.recall("winch", PDA)

    assert outcome.items == []
    assert outcome.degraded is True
    assert outcome.reason == "unavailable"


async def test_an_entity_schema_outage_surfaces_on_write_with_no_audit_row() -> None:
    """The opposite posture on the write path (C3 §4): the failure is raised, and
    nothing is recorded — an audit row here would name a memory that was never
    filed anywhere."""
    sink = RecordingSink()
    service = MemoryService(
        NeverCalledProvider(), audit_sink=sink, resolver=dead_resolver()
    )

    with pytest.raises(MemoryUnavailableError):
        await service.write(item(), RULES, scope=PDA)

    assert sink.scopes == []


async def test_resolution_and_the_vendor_call_share_one_recall_budget() -> None:
    """R13 item 2, the part a "resolve then recall" implementation gets wrong:
    resolution runs INSIDE `asyncio.timeout(budget_s)`, so two sequential
    database round-trips cannot stack two 800 ms budgets.

    Latency is injected into the real resolver (the `_CrashingAudit` pattern from
    the chokepoint suite): each half is comfortably inside the budget on its own,
    and only their SUM exceeds it. A resolver called outside the timeout would
    make this recall succeed after ~2x the budget — which is the bug.
    """

    class SlowResolver(EntityResolver):
        def __init__(self) -> None:
            super().__init__(engine=None)  # never reached: resolve is replaced

        async def resolve(self, scope: MemoryScope) -> MemoryScope:
            await asyncio.sleep(0.06)
            return scope

    class SlowProvider(FakeMemoryProvider):
        async def recall(self, *args, **kwargs):  # type: ignore[override]
            await asyncio.sleep(0.06)
            return await super().recall(*args, **kwargs)

    service = MemoryService(SlowProvider(), resolver=SlowResolver(), budget_s=0.1)

    outcome = await service.recall("winch", PDA)

    assert outcome.degraded is True
    assert outcome.reason == "budget_exceeded"


async def test_a_conversation_scope_is_passed_through_untouched() -> None:
    """`RESOLVABLE_KINDS` is the resolver's own business, but the service must not
    special-case around it: a conversation id is already an id, and the wired
    service must file it unchanged."""
    provider = FakeMemoryProvider()
    service = MemoryService(
        provider, audit_sink=RecordingSink(), resolver=dead_resolver()
    )

    await service.write(item(), RULES, scope=CONV)

    assert [scope.id for scope, _ in provider.items] == ["conv-1"]


# --------------------------------------------------------------------------- #
# Postgres: the real entity schema
# --------------------------------------------------------------------------- #
@pytest_asyncio.fixture
async def engine():
    url = factory.postgres_url()
    assert url is not None
    async for made in factory.engine_for(url):
        yield made


@pytest.fixture
def sink() -> RecordingSink:
    return RecordingSink()


@requires_postgres
async def test_a_project_key_recall_resolves_to_the_row_id_and_filters(engine) -> None:
    """R13 item 6's first owed test, end to end on the REAL provider: a memory
    written under `id="pda"` is recalled under `id="pda"` — and a memory filed
    under a DIFFERENT project is not, which is what proves the resolved id is
    doing the filtering rather than the human key passing through both ways.
    """
    await upsert_entity(engine, "project", key="pda", name="PDA Learning")
    await upsert_entity(engine, "project", key="ezyclean", name="EzyClean")
    service = MemoryService(
        factory.make_provider(engine),
        audit_sink=RecordingSink(),
        resolver=EntityResolver(engine),
        budget_s=30.0,
    )
    await service.write(item("the winch course runs in October"), RULES, scope=PDA)
    await service.write(
        item("the cleaning roster is weekly"),
        RULES,
        scope=MemoryScope(user_id="owner", kind="project", id="ezyclean"),
    )

    outcome = await service.recall("winch course", PDA)

    assert outcome.degraded is False
    assert [scored.item.content for scored in outcome.items] == [
        "the winch course runs in October"
    ]


@requires_postgres
async def test_the_write_audit_row_names_the_resolved_scope(engine, sink) -> None:
    """R13 item 3: the audit sink records the scope the provider actually files
    under. Lineage that named the human key would point at a scope the store has
    no rows for — unreadable exactly when someone is trying to trace a memory."""
    row_id = await upsert_entity(engine, "project", key="pda", name="PDA Learning")
    service = MemoryService(
        factory.make_provider(engine),
        audit_sink=sink,
        resolver=EntityResolver(engine),
        budget_s=30.0,
    )

    await service.write(item(), RULES, scope=PDA)

    assert [scope.id for scope in sink.scopes] == [row_id]


@requires_postgres
async def test_an_unknown_key_raises_memory_scope_error_on_both_paths(engine) -> None:
    """The key is in neither the table nor the registry — R12 rule 3's last
    sentence. It stays a caller bug on both paths."""
    service = MemoryService(
        factory.make_provider(engine),
        audit_sink=RecordingSink(),
        resolver=EntityResolver(engine),
        budget_s=30.0,
    )
    ghost = MemoryScope(user_id="owner", kind="project", id="no-such-project")

    with pytest.raises(MemoryScopeError):
        await service.recall("anything", ghost)
    with pytest.raises(MemoryScopeError):
        await service.write(item(), RULES, scope=ghost)


# --------------------------------------------------------------------------- #
# R12 rule 3 — registry → table, lazily, on WRITE only
# --------------------------------------------------------------------------- #
def _registry() -> dict[str, ProjectDefinition]:
    return {"pda": ProjectDefinition(key="pda", display_name="PDA Learning")}


async def _project_rows(engine) -> list[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(select(ENTITY_TABLES["project"].c.key))
    return [row.key for row in rows]


@requires_postgres
async def test_a_registry_key_is_materialised_once_on_write(engine, sink) -> None:
    """R12 rule 3, materialisation direction: a `kind="project"` scope unknown to
    the entity table but present in the PROJECT REGISTRY (`config/projects.yaml`)
    upserts a row and resolution proceeds. Idempotent on `key` — two writes must
    not mint two entity rows, because two rows for one project is two memory
    scopes for one project and the second appears to have no history."""
    service = MemoryService(
        factory.make_provider(engine),
        audit_sink=sink,
        resolver=EntityResolver(engine),
        project_registry=_registry(),
        budget_s=30.0,
    )

    await service.write(item("first"), RULES, scope=PDA)
    await service.write(item("second"), RULES, scope=PDA)

    assert await _project_rows(engine) == ["pda"]
    assert len(set(scope.id for scope in sink.scopes)) == 1
    assert sink.scopes[0].id != "pda"  # the row id, not the registry key


@requires_postgres
async def test_recall_never_materialises_a_registry_key(engine) -> None:
    """R12 rule 3's hard half: **recall never creates rows.** A read that
    materialised its scope would let a stray query mint entities, and it is the
    same posture as the TTL filter — reads do not mutate."""
    service = MemoryService(
        factory.make_provider(engine),
        audit_sink=RecordingSink(),
        resolver=EntityResolver(engine),
        project_registry=_registry(),
        budget_s=30.0,
    )

    with pytest.raises(MemoryScopeError):
        await service.recall("anything", PDA)

    assert await _project_rows(engine) == []


@requires_postgres
async def test_a_key_outside_the_registry_is_not_materialised(engine) -> None:
    """The registry is the authority for what may be created: a write naming a
    project neither the table nor `config/projects.yaml` knows stays a
    `MemoryScopeError` — the write path must not be a way to invent entities."""
    service = MemoryService(
        factory.make_provider(engine),
        audit_sink=RecordingSink(),
        resolver=EntityResolver(engine),
        project_registry=_registry(),
        budget_s=30.0,
    )

    with pytest.raises(MemoryScopeError):
        await service.write(
            item(), RULES, scope=MemoryScope(user_id="owner", kind="project", id="ghost")
        )

    assert await _project_rows(engine) == []
