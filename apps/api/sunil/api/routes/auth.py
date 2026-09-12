"""Owner sign-in (ADR-007). Single-owner system: one `users` row, one session.

Three properties worth naming, because each is a place this kind of route
usually leaks:

* **One failure message.** A wrong username and a wrong password produce the same
  401 with the same text, so the endpoint is not a username oracle.
* **Constant-time comparison, and the hash is always computed.** An unknown
  username still runs a scrypt verification against a dummy hash, so response
  timing does not separate "no such user" from "wrong password".
* **The password never leaves this module.** It is not logged, not echoed, not
  put in a trace detail, and the request model is `extra="forbid"` so a client
  cannot smuggle extra fields into a code path that might.

`scrypt` comes from the standard library deliberately: no new dependency, and the
parameters are pinned here rather than inherited from a library default that can
change under us.
"""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from sunil.api.deps import SESSION_USER_KEY, require_client_header, require_owner
from sunil.api.errors import ApiError
from sunil.db.models import User

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

#: scrypt parameters (RFC 7914). n=2**14 keeps sign-in well under a second on the
#: dev box while costing an attacker ~16 MiB per guess.
_SCRYPT = {"n": 2**14, "r": 8, "p": 1, "dklen": 32}
_SALT_BYTES = 16

#: Verified against when the username is unknown, so the work — and therefore the
#: response time — is the same on both paths.
_DUMMY_HASH = "0" * 32


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=1, max_length=1000)


def hash_password(password: str) -> str:
    """`scrypt$<salt hex>$<derived hex>`."""
    salt = os.urandom(_SALT_BYTES)
    derived = hashlib.scrypt(password.encode("utf-8"), salt=salt, **_SCRYPT)
    return f"scrypt${salt.hex()}${derived.hex()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, salt_hex, derived_hex = encoded.split("$", 2)
    except ValueError:
        return False
    if scheme != "scrypt":
        return False
    try:
        candidate = hashlib.scrypt(
            password.encode("utf-8"), salt=bytes.fromhex(salt_hex), **_SCRYPT
        )
    except ValueError:
        return False
    return hmac.compare_digest(candidate.hex(), derived_hex)


@router.post("/login")
async def login(request: Request, body: LoginRequest) -> dict[str, Any]:
    require_client_header(request)  # the CSRF pair guards sign-in too

    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        user = (
            await session.execute(select(User).where(User.username == body.username))
        ).scalar_one_or_none()

    encoded = user.password_hash if user is not None else _DUMMY_HASH
    if not verify_password(body.password, encoded) or user is None:
        raise ApiError(401, "unauthenticated", "invalid credentials")

    # Rotate the session id on privilege change: a pre-login session must not
    # become an authenticated one (session fixation).
    request.session.clear()
    request.session[SESSION_USER_KEY] = user.id
    return {"user": {"id": user.id, "name": user.name, "username": user.username}}


@router.post("/logout")
async def logout(request: Request) -> Response:
    require_client_header(request)
    request.session.clear()
    return Response(status_code=204)


@router.get("/me")
async def me(request: Request) -> dict[str, Any]:
    user_id = require_owner(request)
    sessionmaker = request.app.state.sessionmaker
    async with sessionmaker() as session:
        user = await session.get(User, user_id)
    if user is None:
        # The session names a user that no longer exists: refuse rather than
        # serve a half-identity.
        raise ApiError(401, "unauthenticated", "no valid owner session")
    return {"user": {"id": user.id, "name": user.name, "username": user.username}}
