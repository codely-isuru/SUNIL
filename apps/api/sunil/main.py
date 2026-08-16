"""FastAPI application factory.

T1 shipped a bare app with logging configured. T5 (this revision) adds the
explicit middleware list, CORS outermost (§3.3), the lifespan's fail-closed
startup checks, and router registration (`docs/M1_BUILD_PLAN.md` §2 T5:
"Extends (same lane): sunil/main.py — the middleware list and router
registration").
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
from sunil.db.session import assert_alembic_head, get_app_engine
from sunil.logging import configure_logging
from sunil.redaction import register_secrets_from_settings
from sunil.settings import get_settings

# M1 ships exactly one Alembic revision (ADR-002: "single linear history,
# 0001_initial for M1"). Update this alongside the next migration, in the
# same change, when one lands.
EXPECTED_ALEMBIC_HEAD = "0001"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Fail-closed startup checks — a bad edit or an un-migrated database
    must be loud and immediate, on the boot path, not a lazy first-request
    500 (ADR-002 §7.4, ADR-016).
    """
    settings = get_settings()

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
    engine = get_app_engine()
    await assert_alembic_head(engine, expected_head=EXPECTED_ALEMBIC_HEAD)

    yield


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    settings = get_settings()
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

    app.include_router(auth.router)
    app.include_router(health.router)

    return app


# Module-level instance for `uvicorn sunil.main:app` (docs/ARCHITECTURE_V1.md
# §14.1's documented dev command).
app = create_app()
