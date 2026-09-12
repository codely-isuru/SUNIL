"""Async engine, session factory, and the migration-head startup guard
(ADR-002, ADR-018).

**Settings, engine and sessionmaker are per-application state, not a
process-global cache.** `create_app()` builds one engine/sessionmaker per app
from whatever `Settings` it was given and stores them on `app.state`;
`get_session()` reads them from `request.app.state`. Two apps built with
different `DATABASE_URL`s in the same process (the test harness does exactly
that, one app per test) then never share a database.

`get_settings()`/`get_app_engine()` keep a process-wide cache, and their scope is
narrow on purpose: contexts that have **no `app`** — Alembic, `scripts/*`,
one-shot CLI work. Nothing on the request path uses either.

The app **never auto-migrates**. It asserts `alembic_version` matches head and
refuses to boot otherwise: running against a half-migrated schema is exactly the
condition where an audit row silently fails to write, and §7's failure posture
says an unauditable app is down, not degraded.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from starlette.requests import Request

from sunil.settings import Settings, get_settings


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """Build a NEW async engine from `Settings.database_url`. Not cached —
    `create_app()` calls this once per application (ADR-018)."""
    settings = settings or get_settings()
    return create_async_engine(settings.database_url.get_secret_value())


@lru_cache
def get_app_engine() -> AsyncEngine:
    """The cached engine for **no-`app` contexts only** (scripts, Alembic).
    Request-path code must never call this: it reads `get_settings()`, which is
    itself process-cached, so it would pin whichever `DATABASE_URL` some earlier
    part of the process happened to ask for first — ADR-018's motivating bug."""
    return get_engine()


def get_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency. Takes its sessionmaker from
    `request.app.state.sessionmaker` — never a module-level or cached engine — so
    it always queries the database *this* app was built with."""
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        yield session


class AlembicHeadMismatch(RuntimeError):
    """The database's `alembic_version` does not match the migration head."""


async def assert_alembic_head(engine: AsyncEngine, *, expected_head: str) -> None:
    """Fail fast, on the boot path, if the database has not been migrated to
    `expected_head` — never a lazy first-request 500."""
    async with engine.connect() as conn:
        try:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            row = result.first()
        except DBAPIError as exc:
            raise AlembicHeadMismatch(
                "could not read alembic_version — has `alembic upgrade head` been "
                f"run against this database? ({exc})"
            ) from exc

    current = row[0] if row else None
    if current != expected_head:
        raise AlembicHeadMismatch(
            f"database is at alembic revision {current!r}, expected head "
            f"{expected_head!r} — run `alembic upgrade head`."
        )
