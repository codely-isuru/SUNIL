"""Stream D's own thin test factory for the approvals service.

Deliberately self-contained (Stream D task brief): it imports **no spine
module** — no ``sunil.settings``, no ``sunil.db.session``, no
``sunil.db.models`` — because those may not exist in this worktree yet. The
service takes its engine, its config and its clock through constructor
arguments, so this factory only has to build those three things.

Database selection
------------------
``SUNIL_TEST_DATABASE_URL`` (a SQLAlchemy **async** URL) selects Postgres; when
it is unset the factory falls back to in-memory SQLite so the suite is green on
a machine with no Docker. No credential is hard-coded here — a local dev DSN is
still a credential-shaped string and does not belong in the repo. Example:

    export SUNIL_TEST_DATABASE_URL='postgresql+psycopg://user:pw@127.0.0.1:5433/db'

ARCHITECTURE_V2 §1 is the licence for the fallback: "ADR-001's 'one portable
schema' is kept, so SQLite remains usable for unit tests via the same models".
The compare-and-swap proof is run on **both** when Postgres is available — the
CAS is the property that must hold on the real engine (see
``test_cas_race.py``).
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from sunil.core.approvals.config import ApprovalsConfig
from sunil.core.approvals.ids import ulid_approval_id
from sunil.core.approvals.table import APPROVALS_METADATA
from sunil.core.approvals.service import DatabaseApprovalsService

#: Set to a SQLAlchemy async Postgres URL to run against Postgres.
PG_URL_ENV = "SUNIL_TEST_DATABASE_URL"
SQLITE_URL = "sqlite+aiosqlite:///:memory:"


def postgres_url() -> str | None:
    """The Postgres async URL from the environment, or None."""
    return os.environ.get(PG_URL_ENV) or None


def engine_urls() -> list[str]:
    """Every engine URL this machine can run the suite against, SQLite first."""
    urls = [SQLITE_URL]
    pg = postgres_url()
    if pg:
        urls.append(pg)
    return urls


def label(url: str) -> str:
    """A short, credential-free id for a URL — safe to print in test ids."""
    return url.split("://", 1)[0]


async def make_engine(url: str) -> AsyncEngine:
    """An engine with the approvals table created.

    SQLite in-memory needs ``StaticPool`` so every connection in the pool sees
    the same database; without it each checkout gets a fresh empty file and the
    CAS tests silently pass against nothing.
    """
    kwargs: dict = {"future": True}
    if url.startswith("sqlite"):
        from sqlalchemy.pool import StaticPool

        kwargs["poolclass"] = StaticPool
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_async_engine(url, **kwargs)
    async with engine.begin() as conn:
        await conn.run_sync(APPROVALS_METADATA.drop_all)
        await conn.run_sync(APPROVALS_METADATA.create_all)
    return engine


async def engine_for(url: str) -> AsyncIterator[AsyncEngine]:
    engine = await make_engine(url)
    try:
        yield engine
    finally:
        await engine.dispose()


def make_service(
    engine: AsyncEngine,
    *,
    clock,
    consume_grace_hours: int = 1,
    ttl_hours: int = 72,
    notifier=None,
    audit=None,
    tasks=None,
    scheduler=None,
) -> DatabaseApprovalsService:
    """The real service, wired for a test. ``clock`` is a zero-arg callable
    returning an aware ``datetime`` (C4 §6's injectable clock)."""
    return DatabaseApprovalsService(
        engine=engine,
        config=ApprovalsConfig(
            ttl_hours=ttl_hours,
            consume_grace_hours=consume_grace_hours,
            notify_webhook_url=None,
        ),
        clock=clock,
        id_factory=ulid_approval_id,
        notifier=notifier,
        audit=audit,
        tasks=tasks,
        scheduler=scheduler,
    )
