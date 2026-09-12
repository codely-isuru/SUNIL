"""The parts of C3 the real provider must satisfy WITHOUT a database.

Contract tests 6 (unavailable) and 7 (the frozen signature) need no live
Postgres — 6 is about what happens when there is none — so they live outside
`test_pgvector_parity.py`'s Postgres skip. Otherwise the two properties that
matter most on a machine with no Docker (the turn degrades; the seam signature
did not drift) would be the two that never run there.
"""

from __future__ import annotations

from inspect import signature

import pytest

from sunil.core.memory.provider import (
    MemoryItem,
    MemoryProvider,
    MemoryScope,
    MemoryUnavailableError,
    WriteRules,
)
from sunil.core.memory.service import MemoryService
from sunil.memory_providers.pgvector_provider import PgVectorMemoryProvider
from tests.unit.memory.factory import dead_provider

CONV_1 = MemoryScope(user_id="owner", kind="conversation", id="conv-1")
AUDIT_ID = "audit-evt-1"


def item(content: str = "anything") -> MemoryItem:
    return MemoryItem(
        content=content, memory_type="fact", privacy="internal", source_request_id="req-1"
    )


def rules() -> WriteRules:
    return WriteRules(capture="redacted_full")


# --------------------------------------------------------------------------- #
# C3 contract test 6
# --------------------------------------------------------------------------- #
async def test_c3_6_an_unreachable_database_raises_memory_unavailable() -> None:
    """C3 §4: vendor down/timeout is `MemoryUnavailableError`. A provider
    leaking SQLAlchemy's `OperationalError` would make the service's
    `except MemoryUnavailableError` a no-op and FAIL the turn instead of
    degrading it — which is the one thing C3 §2 says must never happen."""
    broken = dead_provider()

    with pytest.raises(MemoryUnavailableError):
        await broken.recall("anything", CONV_1)

    with pytest.raises(MemoryUnavailableError):
        await broken.write(item(), rules(), scope=CONV_1, audit_event_id=AUDIT_ID)


async def test_c3_6_the_service_degrades_recall_and_surfaces_the_write() -> None:
    """The service half, against the REAL provider's real failure mode (the
    contract suite proves it against the fake's injected flag). Memory being
    down degrades a turn; a lost write stays visible."""

    class RecordingSink:
        def __init__(self) -> None:
            self.rows: list[str] = []

        async def record_memory_write(self, *, scope, item) -> str:
            del scope, item
            self.rows.append(f"audit-{len(self.rows) + 1}")
            return self.rows[-1]

    sink = RecordingSink()
    # A generous budget ON PURPOSE. C3 §2 gives the service two degrade reasons —
    # `budget_exceeded` and `unavailable` — and a real TCP connect to a dead port
    # takes longer than the 800 ms budget, so the default would degrade on the
    # TIMEOUT and this test would never exercise the error translation it exists
    # for. The budget path is covered by the contract suite against the fake.
    service = MemoryService(dead_provider(), audit_sink=sink, budget_s=30.0)

    outcome = await service.recall("anything", CONV_1)
    assert outcome.items == []
    assert outcome.degraded is True
    assert outcome.reason == "unavailable"

    with pytest.raises(MemoryUnavailableError):
        await service.write(item(), rules(), scope=CONV_1)

    # Audit-outside-vendor: the row survives the vendor call that failed.
    assert sink.rows == ["audit-1"]


async def test_an_embedder_failure_degrades_rather_than_leaking(monkeypatch) -> None:
    """The embedding call is the other thing that can be down. C3 §2's degrade
    covers "memory is unavailable", and an embedder that cannot answer makes
    recall unavailable — so it must arrive as the same named error."""
    from sunil.core.memory.embedding import EmbeddingUnavailableError

    provider = dead_provider()

    async def boom(text: str) -> list[float]:
        raise EmbeddingUnavailableError("gateway returned HTTP 500")

    monkeypatch.setattr(provider._embedder, "embed", boom)

    with pytest.raises(MemoryUnavailableError):
        await provider.recall("anything", CONV_1)


# --------------------------------------------------------------------------- #
# C3 contract test 7 — the frozen signature, on the implementation
# --------------------------------------------------------------------------- #
def test_c3_7_the_real_provider_matches_the_frozen_signature() -> None:
    """Contract test 7 pins the PROTOCOL; this pins that the implementation
    still matches it. A keyword-only `scope` that grew a default here would
    reintroduce v1.0.0's F-1 gap in the one place it can actually bite."""
    write = signature(PgVectorMemoryProvider.write)
    recall = signature(PgVectorMemoryProvider.recall)

    assert list(write.parameters) == ["self", "item", "rules", "scope", "audit_event_id"]
    for name in ("scope", "audit_event_id"):
        assert write.parameters[name].kind.name == "KEYWORD_ONLY"
        assert write.parameters[name].default is write.empty
    assert list(recall.parameters) == ["self", "query", "scope", "limit"]
    assert recall.parameters["limit"].default == 8


def test_the_real_provider_satisfies_the_protocol_structurally() -> None:
    provider: MemoryProvider = dead_provider()

    assert provider.name == "pgvector"


def test_the_provider_refuses_an_embedder_of_the_wrong_width() -> None:
    """The column is `vector(EMBEDDING_DIM)`. An embedder of another width is a
    migration, not a config flip, and the failure belongs at construction —
    where it names both numbers — rather than at the first INSERT, where it is
    a driver error nobody can read."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from sunil.core.memory.embedding import EMBEDDING_DIM, HashingEmbedder

    engine = create_async_engine("postgresql+psycopg://u:p@127.0.0.1:1/none")
    with pytest.raises(ValueError) as err:
        PgVectorMemoryProvider(engine=engine, embedder=HashingEmbedder(dimension=8))

    assert "8" in str(err.value) and str(EMBEDDING_DIM) in str(err.value)
