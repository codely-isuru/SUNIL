"""Alembic environment.

Two rules worth stating, because both are security- or correctness-relevant:

1. **The URL comes from `Settings`, not from `alembic.ini`.** `settings.py` is the
   single env seam; a `sqlalchemy.url` in the ini file would be a second copy of
   a credential-bearing string, in git.
2. **Migrations run on the SYNC driver.** `DATABASE_URL` is
   `postgresql+psycopg://…` (psycopg v3), which serves both SQLAlchemy 2's async
   engine and this sync path — that is exactly why §5's driver ruling picked it
   over `+asyncpg`. The `+aiosqlite` unit-test URL is downgraded to plain
   `sqlite://` here for the same reason.
3. **`approvals` is fenced out of the comparison, both sides** (`db/autogenerate.py`,
   wave-1 ruling R2). The table is owned by `core/approvals/table.py` and Stream
   D's hand-written revisions; it is absent from `Base.metadata` and present in
   every deployed database, so without the fence the next autogenerate would
   emit `op.drop_table("approvals")` — a silent DROP of an audit-bearing table.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

from sunil.db.autogenerate import include_name, include_object
from sunil.db.base import Base
from sunil.db.models import *  # noqa: F401,F403 — import for metadata registration
from sunil.settings import Settings

config = context.config
target_metadata = Base.metadata

# A fresh `Settings()` — never the process-cached `get_settings()`: Alembic is a
# no-`app` context and must read the environment it was actually invoked with.
_ASYNC_TO_SYNC = {"+aiosqlite": "", "+asyncpg": "+psycopg"}


def _sync_url() -> str:
    url = Settings().database_url.get_secret_value()
    for async_token, sync_token in _ASYNC_TO_SYNC.items():
        url = url.replace(async_token, sync_token)
    return url


def run_migrations_offline() -> None:
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        include_name=include_name,
        include_object=include_object,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            include_name=include_name,
            include_object=include_object,
            # SQLite cannot ALTER most things in place; batch mode is what keeps
            # ONE history portable across both engines (ADR-001).
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
