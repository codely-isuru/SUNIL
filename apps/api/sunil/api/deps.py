"""Route dependencies — the two authentication lanes and the CSRF pair.

**Ordering is ADR-008's, not an accident.** On the cookie lane the client/Origin
check runs BEFORE the session check, so a cross-site page that already holds the
owner's cookie is refused at the header (403) rather than reaching a code path
that answers "your session is valid". C5 contract test 4 pins that order.

**The bearer lane is structurally scoped** (ADR-035): `require_service_token` is
registered on exactly one route, `POST /api/v1/chat`. Nothing here is a router
default and nothing is applied by `include_router(dependencies=…)` — a dependency
slipped onto a router would silently widen a static token's blast radius to every
path beneath it, which is what C5 contract test 8 walks the route table to catch.

**Credentials are never inputs to a logging call** (C5 §3, Security review item
5). No function in this module logs, formats or echoes an `Authorization` or
`Cookie` value — including on the failure paths, where an invalid bearer is
exactly the value most worth not recording. The redaction registry is the second
line, not the first.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Request

from sunil.api.errors import ApiError

#: ADR-008's literal header value (C5 OpenAPI `clientHeader`).
CLIENT_HEADER = "X-SUNIL-Client"
CLIENT_HEADER_VALUE = "web"

#: The session key the owner's user id is stored under (ADR-007).
SESSION_USER_KEY = "user_id"


@dataclass(frozen=True)
class CallerIdentity:
    """Who is making this turn request, and on which lane."""

    lane: str  # "cookie" | "bearer"
    user_id: str | None  # the owner on the cookie lane; None for a machine caller
    channel_label: str | None  # ADR-035: which workflow called (bearer lane only)


def get_settings(request: Request) -> Any:
    """Settings come off `app.state` (ADR-018), never from a module-level cache:
    two apps with two configurations must be able to coexist in one process."""
    return request.app.state.settings


def require_client_header(request: Request) -> None:
    """ADR-008's CSRF pair: the literal `X-SUNIL-Client: web` header AND an
    `Origin` matching `WEB_ORIGIN`.

    **An absent `Origin` is a mismatch** (a route decision C5 §3 leaves open, and
    recorded here as the fail-closed one): the cookie lane is the browser lane,
    browsers always send `Origin` on a cross-origin POST, and accepting its
    absence would hand every non-browser client the cookie lane's authority
    without the control that makes the cookie safe to trust.
    """
    settings = get_settings(request)
    if request.headers.get(CLIENT_HEADER) != CLIENT_HEADER_VALUE:
        raise ApiError(403, "forbidden_client", f"{CLIENT_HEADER} must be 'web'")
    if request.headers.get("Origin") != settings.web_origin:
        raise ApiError(403, "forbidden_client", "Origin is not the configured web origin")


def require_owner_session(request: Request) -> str:
    """The signed session cookie (ADR-007). Returns the owner's user id."""
    session = getattr(request, "session", {})
    user_id = session.get(SESSION_USER_KEY)
    if not user_id:
        raise ApiError(401, "unauthenticated", "no valid owner session")
    return str(user_id)


async def require_service_token(request: Request) -> str | None:
    """ADR-035's machine lane, and the ONLY dependency that accepts a bearer.

    Returns the caller's channel label when a valid `SUNIL_SERVICE_TOKEN` is
    presented, and `None` when the request carries no bearer at all (so the
    cookie lane can proceed). A bearer that is present and wrong is a 401 here —
    it never falls through to the cookie lane, because falling through would let
    a failed machine attempt be answered by an ambient browser session.

    `compare_digest` keeps the comparison constant-time; the presented value is
    not logged, echoed or used to build the error message.
    """
    header = request.headers.get("Authorization")
    if header is None:
        return None

    scheme, _, presented = header.partition(" ")
    if scheme.lower() != "bearer" or not presented:
        raise ApiError(401, "unauthenticated", "invalid authorization header")

    settings = get_settings(request)
    configured = settings.sunil_service_token
    if configured is None:
        # The machine lane is OFF (the fail-closed application default). A bearer
        # is refused rather than ignored: silently ignoring it would answer the
        # machine caller with whatever ambient session the request also carried.
        raise ApiError(401, "unauthenticated", "service token lane is not enabled")

    if not secrets.compare_digest(presented, configured.get_secret_value()):
        raise ApiError(401, "unauthenticated", "invalid service token")

    label = request.headers.get("X-SUNIL-Channel-Label")
    return label or "service"


def authenticate_chat_caller(
    request: Request,
    service_caller: str | None = Depends(require_service_token),
) -> CallerIdentity:
    """The chat route's single auth dependency, covering both lanes.

    It depends on `require_service_token` rather than duplicating it, so the
    route-table walk in C5 contract test 8 finds the bearer dependency by
    identity on exactly this route.
    """
    if service_caller is not None:
        return CallerIdentity(lane="bearer", user_id=None, channel_label=service_caller)

    require_client_header(request)  # ADR-008: before the session check
    return CallerIdentity(
        lane="cookie", user_id=require_owner_session(request), channel_label=None
    )


def require_owner(request: Request) -> str:
    """The owner-only lane for every non-chat route: the CSRF pair and then the
    session. The ADR-035 bearer is never valid here — it is not even consulted."""
    require_client_header(request)
    return require_owner_session(request)
