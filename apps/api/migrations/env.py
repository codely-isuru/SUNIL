"""Alembic environment — async (ADR-002).

The database URL is never hard-coded here or in `alembic.ini`; it comes
from a `Settings.database_url` read the same way the running application
reads it, so `alembic upgrade head` always targets the database the app
will actually connect to.

**A fresh `Settings()`, deliberately, not the cached `get_settings()`**
(ADR-018 §5). `get_settings()` is `@lru_cache`d process-wide; if anything
in an in-process test run had already read settings before this script
ran (QA's harness calls `create_app()` once per test, each with its own
`DATABASE_URL`), `get_settings()` would still return the *first* test's
settings and `alembic upgrade head` would silently migrate a different
database than the one the test just configured. A fresh read costs
microseconds and is the only way this module always targets the
environment as it stands at the moment migrations actually run.
"""

import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

# Import every model module so it registers on `Base.metadata` before
# Alembic reads it — required for `--autogenerate` (used only as a draft,
# per ADR-002; every revision is hand-reviewed).
from sunil.db import models  # noqa: F401
from sunil.db.base import Base
from sunil.settings import Settings

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

config.set_main_option("sqlalchemy.url", Settings().database_url.get_secret_value())


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection ("offline" mode)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Drive Alembic's sync migration API from the async engine — the
    documented `connectable.run_sync(do_run_migrations)` pattern (ADR-002)."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
