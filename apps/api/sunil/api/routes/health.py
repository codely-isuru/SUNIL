"""Liveness and readiness.

`/healthz` answers without touching the database — it is the "is the process up"
probe. `/readyz` runs `SELECT 1`, because ARCHITECTURE_V2 §7's posture is that an
app with no database is DOWN, honestly, rather than up and failing every request
in a way a load balancer reads as healthy.

Neither endpoint reports a version, a hostname, a driver string or an error
detail: an unauthenticated probe is the cheapest reconnaissance surface there is,
so it answers with a status and nothing else.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(request: Request) -> JSONResponse:
    sessionmaker = request.app.state.sessionmaker
    try:
        async with sessionmaker() as session:
            await session.execute(text("SELECT 1"))
    except Exception:  # deliberately blind: the reason is logged, never returned
        request.app.state.logger.warning("readiness_check_failed")
        return JSONResponse(status_code=503, content={"status": "unavailable"})
    return JSONResponse(status_code=200, content={"status": "ok"})
