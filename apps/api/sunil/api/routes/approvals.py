"""C4's HTTP surface — ``C4-approvals-openapi.yaml``, implemented.

Three routes and exactly one of them mutates:

* ``GET  /api/v1/approvals`` — the dashboard queue (status filter, cursor page)
* ``GET  /api/v1/approvals/{approval_id}`` — one approval, full redacted detail
* ``POST /api/v1/approvals/{approval_id}/decision`` — approve or refuse

**There is deliberately no ``POST /api/v1/approvals``** (C4 §5's scope note).
Approvals are minted only by the in-process ``park`` seam, inside the
transaction that also persists the continuation. An HTTP creation surface would
let a caller mint rows with no continuation and a binding the server did not
compute — an approval that could never be consumed correctly, or one whose
binding an attacker chose.

Status mapping lives here and nowhere else, which is why
``ApprovalsService.decide`` returns ``Approval | StateConflict | None`` instead
of raising (C4 §6.2, normative since v1.0.1):

| service returns | HTTP |
|---|---|
| ``Approval`` | 200 |
| ``StateConflict`` | 409, body carries ``current_status`` |
| ``None`` | 404 ``not_found`` |
| ``ValueError`` from a bad cursor | 422 ``validation_error`` |

**No decision idempotency** (C4 §5): repeating a decision returns 409 with the
true state rather than a comforting echo, so the UI cannot show a user a
decision they did not make.

The plain-text rule (C4 §4, Security review item 8) has a server-side half, and
it is implemented here rather than left entirely to the dashboard:
``summary`` and every ``params_redacted`` value are returned as JSON string
data, byte-for-byte as parked — never HTML-escaped (which would corrupt the
value), never wrapped in markup, and never interpolated into a template. Every
response carries ``X-Content-Type-Options: nosniff`` so a browser cannot be
talked into rendering ``application/json`` as HTML. The rendering rule itself
remains the dashboard's to honour; the API's job is to not make it impossible.
"""

from __future__ import annotations

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from sunil.core.approvals.base import (
    Approval,
    ApprovalListResponse,
    ApprovalStatus,
    DecisionRequest,
    StateConflict,
)

logger = logging.getLogger(__name__)

#: ADR-008's CSRF control: the header must be the literal value "web".
CLIENT_HEADER = "X-SUNIL-Client"
CLIENT_VALUE = "web"

#: Set on every response: JSON must never be sniffed as HTML, because the
#: payload carries attacker-influenceable strings (C4 §4).
NOSNIFF = {"X-Content-Type-Options": "nosniff"}


def error_body(kind: str, message: str) -> dict:
    """The C4 ``ErrorResponse`` envelope. One builder, so no route can invent a
    second error shape for the dashboard to special-case."""
    return {"error": {"kind": kind, "message": message}}


class ApiError(Exception):
    """A contract error with its status code attached.

    Raised by the dependencies and the routes, rendered by
    :func:`install_error_handlers`. An exception rather than a returned response
    so that a dependency can refuse a request before the route body — and so a
    handler cannot forget to return early.
    """

    def __init__(self, status_code: int, kind: str, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.kind = kind
        self.message = message


# --------------------------------------------------------------------------- #
# Auth dependencies — the shapes C4's OpenAPI `security` block declares
# --------------------------------------------------------------------------- #
async def require_web_client(request: Request) -> None:
    """ADR-008 / C4 ``clientHeader`` + Origin check → 403 ``forbidden_client``.

    Runs BEFORE the session check on purpose. This is a CSRF control: a
    cross-site form post cannot set a custom header, so rejecting on the header
    keeps a forged request from ever reaching session-backed logic. Ordering it
    after the session check would still be safe, but it would mean a forged
    request's session was looked up and audited as an authentication attempt.

    A missing ``Origin`` is not rejected here — non-browser callers (curl in
    dev, the test client) legitimately omit it, and the header check is the
    control that matters. A PRESENT Origin that disagrees with ``WEB_ORIGIN``
    is rejected: that is a real cross-origin attempt, not an omission.
    """
    if request.headers.get(CLIENT_HEADER) != CLIENT_VALUE:
        raise ApiError(
            403,
            "forbidden_client",
            f"{CLIENT_HEADER} must be {CLIENT_VALUE!r}",
        )
    origin = request.headers.get("origin")
    allowed = getattr(request.app.state, "web_origin", None)
    if origin is not None and allowed is not None and origin != allowed:
        raise ApiError(403, "forbidden_client", "Origin is not the allowed web origin")


async def require_owner_session(request: Request) -> str:
    """C4 ``sessionCookie`` — approvals are owner-only → 401 ``unauthenticated``.

    The signed-cookie verification itself is ADR-007 session middleware, which
    belongs to the spine lane; this dependency reads the identity that
    middleware established (``request.state.owner_user_id``) and **fails closed
    when it is absent**. So an app that forgot to install the session
    middleware serves 401 to every approvals request rather than serving them
    unauthenticated — the failure mode is a locked door, not an open one.

    Deliberately NOT a fallback that trusts the raw cookie: an unverified
    ``sunil_session`` value is an attacker-supplied string, and accepting it
    because the middleware is missing is exactly the bypass this shape exists to
    make impossible. The spine can also override this dependency wholesale via
    ``app.dependency_overrides`` when it wires its own ``api/deps.py``.
    """
    owner = getattr(request.state, "owner_user_id", None)
    if not owner:
        raise ApiError(401, "unauthenticated", "no valid owner session")
    return owner


def get_approvals_service(request: Request):
    """The service instance the app was wired with. A 500 (not a 404) if it is
    missing: an unwired route is a deployment bug, and pretending the approval
    does not exist would hide it."""
    service = getattr(request.app.state, "approvals_service", None)
    if service is None:
        raise RuntimeError(
            "app.state.approvals_service is not set — wire the approvals "
            "service before mounting this router"
        )
    return service


OwnerSession = Annotated[str, Depends(require_owner_session)]
WebClient = Annotated[None, Depends(require_web_client)]


# --------------------------------------------------------------------------- #
# Error handlers — installed on the app by the spine's create_app
# --------------------------------------------------------------------------- #
def install_error_handlers(app) -> None:
    """Render :class:`ApiError` and Pydantic validation failures in C4's
    envelope.

    FastAPI's default 422 body is ``{"detail": [...]}``, which is NOT C4's
    ``ErrorResponse``. Without this the dashboard would need two error parsers
    and the 422 in the YAML would be a fiction. The message is the validation
    summary only — request field VALUES are never echoed, because a 422 body is
    a rendering surface too and the input is untrusted.
    """

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_body(exc.kind, exc.message),
            headers=NOSNIFF,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = sorted({".".join(str(p) for p in e["loc"][1:]) for e in exc.errors()})
        return JSONResponse(
            status_code=422,
            content=error_body(
                "validation_error",
                "request shape invalid: " + ", ".join(f for f in fields if f),
            ),
            headers=NOSNIFF,
        )


# --------------------------------------------------------------------------- #
# The router
# --------------------------------------------------------------------------- #
def create_router() -> APIRouter:
    """C4's three routes. A factory rather than a module-level singleton so a
    test (and the spine's ``create_app``) can mount a fresh one per app."""
    router = APIRouter(prefix="/api/v1", tags=["approvals"])

    @router.get(
        "/approvals",
        response_model=ApprovalListResponse,
        operation_id="listApprovals",
        summary="List approvals, newest first (dashboard queue + audit browser)",
    )
    async def list_approvals(
        response: Response,
        _client: WebClient,
        _owner: OwnerSession,
        request: Request,
        status: ApprovalStatus | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=200),
        cursor: str | None = Query(default=None),
    ) -> ApprovalListResponse:
        service = get_approvals_service(request)
        response.headers.update(NOSNIFF)
        try:
            return await service.list_approvals(
                status=status, limit=limit, cursor=cursor
            )
        except ValueError as exc:
            # An unresolvable cursor is a client bug. Answering it with page one
            # would make a "Load more" loop restart for ever instead of failing.
            raise ApiError(422, "validation_error", str(exc)) from exc

    @router.get(
        "/approvals/{approval_id}",
        response_model=Approval,
        operation_id="getApproval",
        summary="One approval with full (redacted) detail",
    )
    async def get_approval(
        response: Response,
        _client: WebClient,
        _owner: OwnerSession,
        request: Request,
        approval_id: Annotated[str, Path()],
    ) -> Approval:
        service = get_approvals_service(request)
        approval = await service.get(approval_id)
        if approval is None:
            raise ApiError(404, "not_found", f"no approval with id {approval_id}")
        response.headers.update(NOSNIFF)
        return approval

    @router.post(
        "/approvals/{approval_id}/decision",
        operation_id="decideApproval",
        summary="Approve or refuse a pending approval (owner only)",
        responses={409: {"model": StateConflict}},
    )
    async def decide_approval(
        _client: WebClient,
        owner: OwnerSession,
        request: Request,
        approval_id: Annotated[str, Path()],
        body: DecisionRequest,
    ) -> Response:
        """The only mutating endpoint. Approving schedules the continuation;
        refusing finalises the parked task as ``failed`` /
        ``approval_refused`` (C4 §3). Both post-transition effects run only
        after the CAS reports a win, so a lost race schedules nothing and
        finalises nothing.
        """
        service = get_approvals_service(request)
        result = await service.decide(approval_id, body.decision, body.reason)

        if result is None:
            raise ApiError(404, "not_found", f"no approval with id {approval_id}")
        if isinstance(result, StateConflict):
            return JSONResponse(
                status_code=409,
                content=result.model_dump(mode="json"),
                headers=NOSNIFF,
            )

        if body.decision == "refuse":
            await service.finalise_refusal(approval_id)
        else:
            scheduler = getattr(service, "scheduler", None)
            if scheduler is not None:
                # ADR-031: the endpoint returns immediately and the service
                # schedules the continuation. A scheduling failure must not
                # un-approve a decision the owner has already made, so it is
                # logged and the 200 stands — the startup reconciliation
                # (C4 §3 rule 1) picks the approval up again.
                try:
                    await scheduler.schedule(approval_id)
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "failed to schedule continuation for %s", approval_id
                    )
        return JSONResponse(
            status_code=200, content=result.model_dump(mode="json"), headers=NOSNIFF
        )

    return router
