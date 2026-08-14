"""`GET /api/v1/health` — the frozen §6 contract: `200 {status, revision}`."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sunil.api.schemas import HealthResponse
from sunil.db.session import get_session

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health", response_model=HealthResponse)
async def health(session: AsyncSession = Depends(get_session)) -> HealthResponse:
    """Liveness, plus the Alembic revision actually applied to this
    database.

    Does not re-run the fail-closed head assertion — that already happened
    once, at process startup (`sunil.main`'s lifespan): the app would not
    be serving requests at all if the database were not at head. This
    handler only reports the value, cheaply, on the request path.
    """
    result = await session.execute(text("SELECT version_num FROM alembic_version"))
    row = result.first()
    revision = row[0] if row is not None else "unknown"

    return HealthResponse(status="ok", revision=revision)
