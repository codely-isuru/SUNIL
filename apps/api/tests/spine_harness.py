"""Shared fixtures for the spine's own suites (`tests/unit`, `tests/integration`).

Loaded as a pytest plugin by each suite's `conftest.py` rather than by a
top-level `conftest.py`, so nothing here can change how the frozen contract
suites in `tests/contracts/` collect or run.

**Why SQLite here and Postgres in `tests/integration/test_migration.py`.**
ARCHITECTURE_V2 §1 keeps ADR-001's "one portable schema", explicitly so "SQLite
remains usable for unit tests via the same models". That is what lets the spine's
unit suite run with no daemon at all. It is NOT a claim that the app supports
SQLite: the migration test applies the real Alembic revision to the real
Compose Postgres, and §7's failure posture says an app with no database is down,
honestly.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from sunil.db.base import Base
from sunil.settings import Settings

#: Every §5 field a test needs to name explicitly so no assertion can be
#: answered by the developer's shell or a repo-root `.env`.
TEST_SETTINGS_BASE: dict[str, object] = {
    "_env_file": None,
    "session_secret": "test-session-secret-not-a-real-key",
    "sunil_memory_provider": "fake",
    "sunil_tool_manager": "fake",
    "sunil_approvals_service": "fake",
    "sunil_llm_provider_lane": "fake",
}


def build_settings(**overrides: object) -> Settings:
    """A `Settings` for tests: explicit, hermetic, fake seams selected."""
    return Settings(**{**TEST_SETTINGS_BASE, **overrides})  # type: ignore[arg-type]


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """A fresh in-memory database per test.

    `StaticPool` + one shared connection: with the default pool, each new
    connection to `:memory:` gets its OWN empty database, so `create_all()` in
    one connection would be invisible to the next — a test that silently tests
    nothing.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False)

    await engine.dispose()


@pytest.fixture(autouse=True)
def _clean_redaction_registry() -> AsyncIterator[None]:
    """The redaction registry is process-wide module state by design (a secret
    stays registered for the life of the process), so each test scopes itself."""
    from sunil.redaction import reset_registry_for_tests

    reset_registry_for_tests()
    yield
    reset_registry_for_tests()
