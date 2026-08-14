"""`POST /api/v1/auth/login`, `POST /api/v1/auth/logout`,
`GET /api/v1/auth/session` — the frozen §6 contract, ADR-007/ADR-008.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sunil.api.deps import (
    LoginThrottled,
    check_not_locked_out,
    record_login_failure,
    record_login_success,
    require_client_header,
    verify_password,
)
from sunil.api.schemas import LoginRequest, LoginResponse, SessionResponse, UserPublic
from sunil.db.models import User
from sunil.db.session import get_session

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.post("/login", response_model=LoginResponse)
async def login(
    payload: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> LoginResponse:
    # Login is itself a mutating request — ADR-008's CSRF control ("every
    # mutating request must send X-SUNIL-Client: web") applies here too,
    # not only to /chat where the frozen contract's own text happens to
    # spell it out.
    require_client_header(request)

    try:
        check_not_locked_out(payload.username)
    except LoginThrottled as exc:
        raise HTTPException(
            status_code=401, detail="too many failed attempts; try again later"
        ) from exc

    user = await session.scalar(select(User).where(User.username == payload.username))

    if user is None or not verify_password(payload.password, user.password_hash):
        # Same generic message whether the username or the password was
        # wrong — do not tell an attacker which one to fix.
        record_login_failure(payload.username)
        raise HTTPException(status_code=401, detail="invalid username or password")

    record_login_success(payload.username)
    request.session["user_id"] = user.id  # the cookie carries only this — no secrets, no PII

    return LoginResponse(user=UserPublic(id=user.id, name=user.name))


@router.post("/logout", status_code=204)
async def logout(request: Request) -> Response:
    require_client_header(request)
    request.session.clear()
    return Response(status_code=204)


@router.get("/session", response_model=SessionResponse)
async def read_session(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> SessionResponse:
    # Read-only: no X-SUNIL-Client requirement (ADR-008 only requires it
    # for mutating requests).
    user_id = request.session.get("user_id")
    if not user_id:
        return SessionResponse(authenticated=False, user=None)

    user = await session.get(User, user_id)
    if user is None:
        # The session names a user that no longer exists — fail closed
        # rather than report an authenticated session for nobody.
        request.session.clear()
        return SessionResponse(authenticated=False, user=None)

    return SessionResponse(authenticated=True, user=UserPublic(id=user.id, name=user.name))
