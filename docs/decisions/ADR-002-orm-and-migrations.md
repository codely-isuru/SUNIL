# ADR-002 — SQLAlchemy 2.0 (async) + Alembic

**Status:** Proposed (Gate 2) · **Date:** 2026-08-14 · **Decider:** Solution Architect
**Context refs:** ADR-001, `docs/ARCHITECTURE_V1.md` §7, FR-002, SRS Q8.

## Context

ADR-001 requires one schema to run on both SQLite and PostgreSQL, with a real migration history from
the first commit. The application is fully async (`ARCHITECTURE_V1.md` §3.2), so the data layer must
be too, or every query blocks the event loop that is also holding a 20-second LLM call.

## Decision

- **SQLAlchemy 2.0 async ORM** — `create_async_engine`, `async_sessionmaker`, typed
  `Mapped[...]`/`mapped_column` declarative models in `sunil/db/models.py`. Drivers: `aiosqlite` and
  `psycopg` v3 (`postgresql+psycopg://`). `greenlet` is pulled in by SQLAlchemy's async layer.
- **Alembic** for migrations. Single linear history. M1 ships exactly one revision, `0001_initial`.
- **Autogenerate is a draft, never a commit.** SQLite reflection misses constraints; every revision
  is hand-reviewed before it lands.
- `downgrade()` is implemented so the suite can round-trip.
- **A merged revision is never edited.** Corrections are new revisions.
- Migrations run as an **explicit step** (`alembic upgrade head`), not automatically inside the app
  process. The app asserts `alembic_version` equals head at startup and **refuses to boot** otherwise.

## Rejected alternatives

| Rejected | Why |
|---|---|
| **SQLModel** | Attractive (one class for table + API schema) but it couples the persistence model to the wire model, which this design deliberately separates (`db/models.py` vs `api/schemas.py`). Its Alembic story is thinner, and it adds a layer between the engineer and SQLAlchemy exactly where portability bugs (ADR-001 §7.2) will surface. |
| **Raw SQL + asyncpg/aiosqlite, hand-written migrations** | Fastest at runtime and honest, but it means writing dialect-specific SQL twice — the one thing ADR-001 exists to avoid — plus a home-made migration runner in a three-day window. |
| **Tortoise ORM / Piccolo** | Both async-native and pleasant, but smaller ecosystems, fewer engineers who know them, and their migration tooling is less battle-tested than Alembic. Unfamiliarity is a schedule risk. |
| **Prisma Client Python** | Requires a Node toolchain in the Python build, generates a client at install time, and its Python client has had maintenance gaps. Two runtimes to build one backend is the wrong trade. |
| **Sync SQLAlchemy + `run_in_threadpool`** | Works, but silently caps concurrency and hides blocking calls in a codebase whose §3.2 rule is "no blocking calls in `core/`". |

## Consequences

- Engineers must use `AsyncSession` throughout; a sync session in a request path is a defect, not a
  style choice.
- Lazy relationship loading is a footgun on async sessions — relationships are loaded explicitly
  (`selectinload`) or not declared at all. M1's queries are simple enough that most joins are
  explicit `select()` statements.
- Alembic's `env.py` must be wired for async (`connectable.run_sync(do_run_migrations)`), which is a
  known, documented pattern and part of task T2.
