"""Unit tests for `sunil.db.session` (T2): engine construction and the
migration-head startup guard.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine
from sunil.db.session import AlembicHeadMismatch, assert_alembic_head, get_engine
from sunil.settings import Settings

_REQUIRED = {
    "ANTHROPIC_API_KEY": "sk-ant-fake",
    "GITHUB_TOKEN": "github_pat_fake",
    "SESSION_SECRET": "fake-secret",
    "OWNER_USERNAME": "test-owner",
    "OWNER_PASSWORD": "fake-password",
}


def _settings(**overrides: str) -> Settings:
    return Settings(_env_file=None, **_REQUIRED, **overrides)


def _file_backed_settings(tmp_path: Path, name: str) -> Settings:
    # A file-backed URL, not a bare in-memory one: separate connections
    # from the pool must see the same database, and SQLite's `:memory:`
    # gives every new connection its own private, empty one.
    db_path = tmp_path / name
    return _settings(DATABASE_URL=f"sqlite+aiosqlite:///{db_path.as_posix()}")


def test_get_engine_builds_an_async_engine_from_database_url(tmp_path: Path) -> None:
    settings = _file_backed_settings(tmp_path, "engine_build.db")
    engine = get_engine(settings)

    assert isinstance(engine, AsyncEngine)
    assert "sqlite" in str(engine.url)


@pytest.mark.asyncio
async def test_assert_alembic_head_raises_when_table_does_not_exist(tmp_path: Path) -> None:
    """No migration has been run at all — must fail closed, never boot
    silently against an unmigrated database."""
    settings = _file_backed_settings(tmp_path, "no_migration.db")
    engine = get_engine(settings)
    try:
        with pytest.raises(AlembicHeadMismatch):
            await assert_alembic_head(engine, expected_head="0001")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_assert_alembic_head_raises_on_a_revision_mismatch(tmp_path: Path) -> None:
    settings = _file_backed_settings(tmp_path, "mismatch.db")
    engine = get_engine(settings)
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
            )
            await conn.exec_driver_sql("INSERT INTO alembic_version VALUES ('not_the_head')")

        with pytest.raises(AlembicHeadMismatch):
            await assert_alembic_head(engine, expected_head="0001")
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_assert_alembic_head_passes_when_revision_matches(tmp_path: Path) -> None:
    settings = _file_backed_settings(tmp_path, "matches.db")
    engine = get_engine(settings)
    try:
        async with engine.begin() as conn:
            await conn.exec_driver_sql(
                "CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"
            )
            await conn.exec_driver_sql("INSERT INTO alembic_version VALUES ('0001')")

        await assert_alembic_head(engine, expected_head="0001")  # must not raise
    finally:
        await engine.dispose()
