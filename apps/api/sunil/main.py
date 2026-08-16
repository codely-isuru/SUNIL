"""FastAPI application factory.

T1 ships a bare app with logging configured. Middleware (CORS, request
context, session), auth dependencies and routers are T5's job, added to
this same function in the same lane (`docs/M1_BUILD_PLAN.md` §2 T5:
"Extends (same lane): sunil/main.py — the middleware list and router
registration"). T1 deliberately does not pre-build that list.
"""

from __future__ import annotations

from fastapi import FastAPI

from sunil.logging import configure_logging
from sunil.settings import get_settings


def create_app() -> FastAPI:
    """Build and return the FastAPI application."""
    settings = get_settings()
    configure_logging(log_level=settings.log_level)

    return FastAPI(title="SUNIL API")


# Module-level instance for `uvicorn sunil.main:app` (docs/ARCHITECTURE_V1.md
# §14.1's documented dev command).
app = create_app()
