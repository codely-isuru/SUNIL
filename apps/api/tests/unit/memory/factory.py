"""Test factory for the memory lane — engines, schema and the provider.

Database selection mirrors `tests/unit/approvals/factory.py`:
`SUNIL_TEST_DATABASE_URL` (a SQLAlchemy **async** URL) selects Postgres. No
credential is hard-coded — a local dev DSN is still a credential-shaped string
and does not belong in the repo:

    export SUNIL_TEST_DATABASE_URL='postgresql+psycopg://user:pw@127.0.0.1:5435/db'

**Unlike the approvals lane there is no SQLite fallback, and that is the point.**
`memories.embedding` is a `vector(1536)` column and recall is a `<=>` cosine
query; SQLite has neither. A fallback would run the parity suite against a
similarity search that does not exist, i.e. it would be green against nothing —
so the Postgres leg SKIPS LOUDLY instead, naming the variable to set. The fake's
own behaviours stay covered by `tests/contracts/test_c3_memory_provider.py`,
which needs no database at all.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from sunil.core.memory.embedding import HashingEmbedder
from sunil.core.memory.tables import MEMORY_METADATA
from sunil.memory_providers.pgvector_provider import PgVectorMemoryProvider

PG_URL_ENV = "SUNIL_TEST_DATABASE_URL"

SKIP_REASON = (
    "the pgvector memory provider needs a real Postgres with the `vector` "
    f"extension. Set {PG_URL_ENV} to an async psycopg URL "
    "(postgresql+psycopg://…) pointing at a pgvector image. There is no SQLite "
    "fallback on purpose: a vector search SQLite cannot run would pass against "
    "nothing."
)


def postgres_url() -> str | None:
    return os.environ.get(PG_URL_ENV) or None


requires_postgres = pytest.mark.skipif(postgres_url() is None, reason=SKIP_REASON)


async def make_engine(url: str) -> AsyncEngine:
    """An engine with the `vector` extension and a freshly created schema."""
    engine = create_async_engine(url, future=True)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(MEMORY_METADATA.drop_all)
        await conn.run_sync(MEMORY_METADATA.create_all)
    return engine


async def engine_for(url: str) -> AsyncIterator[AsyncEngine]:
    engine = await make_engine(url)
    try:
        yield engine
    finally:
        await engine.dispose()


def make_provider(engine: AsyncEngine, **kwargs) -> PgVectorMemoryProvider:
    return PgVectorMemoryProvider(engine=engine, embedder=HashingEmbedder(), **kwargs)


#: A port nothing listens on, on loopback. Connecting fails fast rather than
#: hanging, which is what "the vendor is down" has to look like in a test.
DEAD_URL = "postgresql+psycopg://nobody:nothing@127.0.0.1:1/none"


def dead_provider() -> PgVectorMemoryProvider:
    """A provider whose database is unreachable — C3 §4's "vendor down".

    Real, not mocked: the point of contract test 6 is that the driver's own
    failure arrives at the caller as `MemoryUnavailableError`, and a mock that
    raised that error directly would prove nothing about the translation.
    """
    return PgVectorMemoryProvider(
        engine=create_async_engine(DEAD_URL, connect_args={"connect_timeout": 1}),
        embedder=HashingEmbedder(),
    )
