# ADR-018 — Settings, engine and clients are per-application state; `create_app()` is the unit of isolation

**Status:** Accepted (Architect ruling, QA question 3, 2026-08-14) · **Decider:** Solution Architect
**Context refs:** `ARCHITECTURE_V1.md` §3.2.1, §14.1; `M1_BUILD_PLAN.md` T1, T2, T5, T18;
FR-005; landed code in `sunil/settings.py`, `sunil/db/session.py`, `sunil/main.py`,
`migrations/env.py`.

## Context

QA's harness calls `create_app()` once per test with a different DB path and a different mock-server
port, and asked whether `Settings` is re-read per call or cached process-wide. Reading the landed
code answers it:

- `get_settings()` is `@lru_cache` — one instance per **process**.
- `get_app_engine()` is `@lru_cache` and builds from `get_settings()`.
- `sunil/main.py` ends with a module-level `app = create_app()`, so **importing the module reads and
  pins settings** before any test has decided what the environment should say.

So the first configuration read in a pytest session wins for the whole session. Today every test
fails earlier, at the import gate, so nothing is passing falsely — but the moment T5 and T11a land,
test two silently migrates and queries test one's database. That is a defect that appears exactly
when the suite starts going green, which is the worst possible time to introduce it and the least
likely time for anyone to look.

`SUNIL_TURN_DEADLINE_S` has the same shape, and ET-8's deadline test depends on being able to build
an app with a short deadline.

## Decision

**The `FastAPI` application object is the unit of configuration isolation.**

```python
def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()          # a fresh read — NOT get_settings()
    app.state.settings = settings
    app.state.engine = get_engine(settings)    # T2 already exposes this uncached
    app.state.sessionmaker = get_sessionmaker(app.state.engine)
```

1. `create_app()` accepts an optional `Settings`; with none it constructs a fresh one, re-reading the
   environment and `.env`. That costs microseconds and happens once per process in production.
2. Request-path code reads `request.app.state.*`. `get_session()` takes its sessionmaker from
   `request.app.state.sessionmaker`, never from a module-level engine.
3. `get_settings()` and `get_app_engine()` keep their caches, and their scope **narrows to contexts
   that have no `app`**: `scripts/seed-owner.py`, Alembic, one-shot CLI work.
4. **The module-level `app = create_app()` is deleted.** The run command becomes
   `uvicorn sunil.main:create_app --factory`. Importing `sunil.main` then has no side effect, which
   is what lets a test import it before deciding what the environment should say.
5. **`migrations/env.py` constructs `Settings()` fresh**, not `get_settings()`. As landed it uses the
   cached accessor, so an in-process `alembic upgrade head` after settings have been read would
   migrate a *different* database than the one under test — silently. One line.
6. `redaction.register()` and `configure_logging()` stay process-global and idempotent. The redaction
   registry accumulating secrets across several apps in one session is safe by direction: it can only
   over-redact.

**The supported way for a test to get a fresh instance is therefore to build one** —
`create_app(Settings(_env_file=None, database_url=..., anthropic_base_url=...))` — not to reach for
a cache-clearing hook. `get_settings.cache_clear()` remains available for the script contexts in (3).

## Rejected alternatives

| Rejected | Why |
|---|---|
| **Keep the process-wide cache and document `get_settings.cache_clear()` as the test seam** | Cheapest, and fragile in the specific way that matters: any module that captured a value at import time still holds the stale one, so clearing the cache fixes some consumers and not others. It also makes correct test isolation a thing every author must remember, which is the definition of a control that will eventually be forgotten. |
| **A `pytest` autouse fixture that clears every cache between tests** | Same fragility, plus it is invisible to anyone reading the application code, and it does nothing for a test that needs *two* differently-configured apps at once. |
| **Module-level `Settings()` with no cache at all** | Re-reads on every access, still process-global, still pinned at import. No isolation gained. |
| **Dependency-injection container / `dependency-injector`** | A new dependency and a new idiom for a problem that `app.state` — already part of Starlette — solves in four lines. |
| **Environment manipulation per test (`monkeypatch.setenv` + reimport)** | Reimporting modules to change configuration is how test suites become order-dependent. |
| **Keep the module-level `app` and add a separate factory** | Two entry points, one of which has import-time side effects, and the wrong one is the one uvicorn's documentation shows first. Deleting it is what makes the seam unmissable. |

## Consequences

- One-line change in `migrations/env.py`, a signature change in `create_app()`, `get_session()`
  moving to `request.app.state`, and a flag in the run command. All within T5's lane, which is in
  flight — which is why this ruling is worth issuing today rather than at review.
- `scripts/dev-api.ps1`, `docs/RUNBOOK.md` (T17) and `Dockerfile.api`'s CMD must use `--factory`.
- ET-8's turn-deadline test becomes expressible without a process restart.
- Anything that needs settings outside a request and outside a script — there is nothing in M1 — must
  be passed them, not reach for a global.
