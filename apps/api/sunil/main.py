"""FastAPI application factory.

T1 shipped a bare app with logging configured. T5 (this revision) adds the
explicit middleware list, CORS outermost (§3.3), the lifespan's fail-closed
startup checks, router registration, and (ADR-018) makes `create_app()`
the unit of configuration isolation.

**ADR-018 — settings/engine/sessionmaker are per-application, not
process-global.** `create_app(settings=None)` builds a *fresh* `Settings()`
when none is passed — never the process-wide `get_settings()` cache — and
stores it, its engine and its sessionmaker on `app.state`. That is what
lets QA's harness build one app per test, each with its own
`DATABASE_URL`, in the same process, without one test's database leaking
into another's. There is **no module-level `app` object**: run this with
`uvicorn sunil.main:create_app --factory`, not `sunil.main:app`. A
module-level `app = create_app()` would read and pin settings the moment
`sunil.main` is *imported* — before a test importing it has decided what
the environment should say — which is the exact defect this revision
removes.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from sunil.api.middleware import RequestContextMiddleware
from sunil.api.routes import auth, health
from sunil.core.registry.loader import load_registries
from sunil.db.session import assert_alembic_head, get_engine, get_sessionmaker
from sunil.logging import configure_logging
from sunil.redaction import register_secrets_from_settings
from sunil.settings import Settings

# M1 ships exactly one Alembic revision (ADR-002: "single linear history,
# 0001_initial for M1"). Update this alongside the next migration, in the
# same change, when one lands.
EXPECTED_ALEMBIC_HEAD = "0001"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Fail-closed startup checks — a bad edit or an un-migrated database
    must be loud and immediate, on the boot path, not a lazy first-request
    500 (ADR-002 §7.4, ADR-016).

    Reads `app.state.settings`/`app.state.engine` — already resolved by
    `create_app()` below — rather than calling `get_settings()`/
    `get_app_engine()` again, so the lifespan always checks the exact
    settings and engine this app was built with (ADR-018).
    """
    settings = app.state.settings

    # Makes the redaction mechanism (T4) live rather than dormant: every
    # M1 secret is registered *before* anything else can log or persist.
    register_secrets_from_settings(settings)

    # config/*.yaml, cross-validated as one unit (ADR-016) — refuses to
    # boot on a broken edit rather than failing on the first request that
    # happens to touch the bad part of the config.
    registries = load_registries(settings.sunil_config_dir)
    app.state.registries = registries

    # The app never auto-migrates; it asserts `alembic_version` matches
    # head and refuses to boot otherwise (§7.4).
    await assert_alembic_head(app.state.engine, expected_head=EXPECTED_ALEMBIC_HEAD)

    yield


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build and return the FastAPI application.

    `settings`, when omitted, is constructed fresh — `Settings()`, never
    `get_settings()` (ADR-018): the cached accessor is process-wide, so
    the first read in a process would otherwise pin the database (and
    every other setting) for every app built afterward, silently.
    """
    settings = settings or Settings()
    configure_logging(log_level=settings.log_level)

    middleware = [
        # Outermost: error responses need CORS headers too, or a 401 from
        # an inner dependency reaches the browser looking like an opaque
        # network error rather than "not logged in" (§3.3).
        Middleware(
            CORSMiddleware,
            allow_origins=[settings.web_origin],  # never "*" — rejected by
            # every browser once allow_credentials=True (T-07).
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Content-Type", "X-SUNIL-Client", "X-Request-Id"],
            max_age=600,
        ),
        Middleware(RequestContextMiddleware),
        Middleware(
            SessionMiddleware,
            secret_key=settings.session_secret.get_secret_value(),
            session_cookie=settings.session_cookie_name,
            max_age=86400,
            same_site="lax",
            https_only=False,  # local dev is http://localhost; flip when hosted over TLS
            path="/",
        ),
    ]

    app = FastAPI(title="SUNIL API", middleware=middleware, lifespan=lifespan)

    # Per-application state (ADR-018) — request-path code (sunil.db.session
    # .get_session(), the lifespan above) reads these from `request.app
    # .state`/`app.state`, never from a module-level or process-cached
    # engine.
    app.state.settings = settings
    app.state.engine = get_engine(settings)
    app.state.sessionmaker = get_sessionmaker(app.state.engine)

    app.include_router(auth.router)
    app.include_router(health.router)

    return app
