"""Async engine, session factory, and the migration-head startup guard
(ADR-001, ADR-002, ADR-018).

**Settings, engine and sessionmaker are per-application state, not a
process-global cache** (ADR-018) — `create_app()` builds one engine/
sessionmaker per app from whatever `Settings` it was given (or a fresh
read), stores them on `app.state`, and `get_session()` reads them from
`request.app.state`. Two apps built with different `DATABASE_URL`s in the
same process (QA's harness does exactly this, one app per test) then
never share a database — proven directly in `tests/unit/test_main_app.py`
by logging into two apps seeded with two different users and confirming
neither can authenticate the other's.

`get_settings()` / `get_app_engine()` keep their process-wide `lru_cache`s
(ADR-018 point 3), but their scope **narrows to contexts that have no
`app`**: `scripts/seed-owner.py`, Alembic (`migrations/env.py`, which
already builds a fresh `Settings()` rather than using the cache — see that
module), one-shot CLI work. Nothing on the request path uses either.
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
    """Build a new async engine from `Settings.database_url`.

    Not cached — `create_app()` calls this once per application and
    stores the result on `app.state.engine` (ADR-018). `get_app_engine()`
    below is the separate, process-wide cached accessor for contexts that
    have no `app` at all (scripts, Alembic).
    """
    settings = settings or get_settings()
    return create_async_engine(settings.database_url.get_secret_value())


@lru_cache
def get_app_engine() -> AsyncEngine:
    """The cached engine for **no-`app` contexts only** — scripts,
    one-shot CLI work. Request-path code must never call this: it reads
    `get_settings()`, which is itself process-wide-cached, so it would
    silently pin whichever `DATABASE_URL` was configured when some earlier
    part of the process first asked (ADR-018's own motivating bug).
    """
    return get_engine()


def get_sessionmaker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncGenerator[AsyncSession]:
    """FastAPI dependency: `session: AsyncSession = Depends(get_session)`.

    Takes its sessionmaker from `request.app.state.sessionmaker` — never
    from a module-level or cached engine (ADR-018) — so this always
    queries the database *this* app was built with, even when more than
    one app exists in the same process.
    """
    sessionmaker = request.app.state.sessionmaker
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
