"""Async engine, session factory, and the migration-head startup guard
(ADR-001, ADR-002).

One engine per process, built from `Settings.database_url`.
`get_session()` is a FastAPI-shaped async generator dependency; T5 wires it
in as `Depends(get_session)` when the routes land.
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

from sunil.settings import Settings, get_settings


def get_engine(settings: Settings | None = None) -> AsyncEngine:
    """Build a new async engine from `Settings.database_url`.

    Not cached — `get_app_engine()` below is the process-wide cached
    accessor used by the running application. A bare, uncached
    `get_engine()` is exposed separately so tests and `scripts/seed-owner.py`
    can point at a different URL without disturbing that cache.
    """
    settings = settings or get_settings()
    return create_async_engine(settings.database_url.get_secret_value())


@lru_cache
def get_app_engine() -> AsyncEngine:
    """The one engine the running application shares, so every caller in
    the process reuses the same connection pool (§3.2 — a client/engine is
    created once at startup and reused, never per request)."""
    return get_engine()


def get_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency: `session: AsyncSession = Depends(get_session)`."""
    sessionmaker = get_sessionmaker(get_app_engine())
    async with sessionmaker() as session:
        yield session


class AlembicHeadMismatch(RuntimeError):
    """Raised when the database's `alembic_version` does not match the
    migration head. The app must refuse to boot rather than run against a
    half- or un-migrated schema (ADR-002, §7.4)."""


async def assert_alembic_head(engine: AsyncEngine, *, expected_head: str) -> None:
    """Fail fast if the database has not been migrated to `expected_head`.

    `ARCHITECTURE_V1.md` §7.4: "the app does not auto-migrate at startup;
    it asserts alembic_version matches head and refuses to boot otherwise."
    T2 provides the check; T5 calls it from the FastAPI lifespan (same
    lane's `sunil/main.py` extension).
    """
    async with engine.connect() as conn:
        try:
            result = await conn.execute(text("SELECT version_num FROM alembic_version"))
            row = result.first()
        except DBAPIError as exc:
            raise AlembicHeadMismatch(
                "could not read alembic_version — has `alembic upgrade head` "
                f"been run against this database? ({exc})"
            ) from exc

    current = row[0] if row else None
    if current != expected_head:
        raise AlembicHeadMismatch(
            f"database is at alembic revision {current!r}, expected head "
            f"{expected_head!r} — run `alembic upgrade head`."
        )
