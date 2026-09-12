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

**Where each operation is served from** (QA wave-1 finding B1, fixed here). C4
§4's ``ApprovalsService`` protocol declares two methods — ``park`` and
``consume`` — and C4 §1 names their single caller, the Tool Manager. This
surface used to await four more off that same object, which no conformant
service has to provide, so the mounted routes answered an authorised owner 500
(``TypeError: object ApprovalListResponse can't be used in 'await' expression``).
They are now placed where the contract puts them:

| operation | served by | contract |
|---|---|---|
| list | ``core/approvals/read_model.py`` over the ``approvals`` table | C4 §6.5's law; the C6 read-model precedent |
| detail | the same read model | C4 OpenAPI; ``get`` is on no protocol |
| decide | the wired C4 service | C4 §6.2 — normative for the service layer |
| finalise refusal / schedule continuation | the wired service, **if it offers them** | C4 §3 states the effect, names no method |

Status mapping lives here and nowhere else, which is why
``ApprovalsService.decide`` returns ``Approval | StateConflict | None`` instead
of raising (C4 §6.2, normative since v1.0.1; **awaitable and service-clocked
since v1.2.0** — wave-1 ruling R7, which retired this module's extra-contractual
501 posture: a wired seam whose ``decide`` is not awaitable is now a wiring
defect of the same class as an unset ``app.state.approvals_service``):

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

from sunil.core.approvals import read_model
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

    **An absent ``Origin`` is a mismatch** — ADR-008 **Amendment 1** (2026-09-12,
    wave-1 ruling R3), applied here in the wave-2 wiring round. This function
    previously implemented the Decision's letter: tolerate absence, and
    additionally soft-skip the whole comparison when ``app.state.web_origin`` was
    unset. Two consequences, both now closed:

    * ``cookie + X-SUNIL-Client: web + no Origin`` answered 200 on the C4/C6
      routes and 403 on ``/api/v1/chat`` (``deps.require_client_header``, already
      conformant) — one credential shape, two answers, so the pair's second
      factor was optional for anyone who simply omitted it. The only legitimate
      cookie-lane caller is the browser app, which is cross-origin
      (``localhost:3001`` → ``localhost:8000``) and therefore always sends
      ``Origin``, on GET too. Dev ``curl`` sends the full browser sentence;
      machine callers have ADR-035's bearer lane and were never entitled to this
      one.
    * the ``getattr(..., None)`` default meant **unset wiring waived the check**.
      ``web_origin`` is required wiring, not an optional attribute: unset is a
      locked door (403), never a control quietly removed.
    """
    if request.headers.get(CLIENT_HEADER) != CLIENT_VALUE:
        raise ApiError(
            403,
            "forbidden_client",
            f"{CLIENT_HEADER} must be {CLIENT_VALUE!r}",
        )
    origin = request.headers.get("origin")
    allowed = getattr(request.app.state, "web_origin", None)
    if allowed is None or origin != allowed:
        # One message for both halves: naming which of "no Origin", "wrong
        # Origin" or "this app has no configured origin" applied would tell an
        # unauthorised caller about the deployment's wiring.
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
    does not exist would hide it.

    Reached by the DECISION route only. C4 §4's protocol is ``park``/``consume``
    — the Tool Manager's seam — and C4 §6.2 adds ``decide`` normatively for the
    service layer; the two reads go to the database read model instead, so no
    route demands a method the contract does not give a conformant service
    (QA wave-1 B1).
    """
    service = getattr(request.app.state, "approvals_service", None)
    if service is None:
        raise RuntimeError(
            "app.state.approvals_service is not set — wire the approvals "
            "service before mounting this router"
        )
    return service


def get_read_engine(request: Request):
    """The engine C4's and C6's read models query.

    One resolver for both surfaces (``ops_read_model.get_engine`` is this
    function) so the approvals queue and the ops reads cannot end up pointed at
    two different databases. A missing engine raises rather than returning an
    empty page: an unwired read route answering ``{"approvals": []}`` looks
    exactly like an empty queue, which is the one answer an approvals dashboard
    must never invent.
    """
    engine = getattr(request.app.state, "ops_engine", None)
    if engine is None:
        engine = getattr(
            getattr(request.app.state, "approvals_service", None), "engine", None
        )
    if engine is None:
        raise RuntimeError(
            "app.state.ops_engine is not set — wire a read engine before "
            "mounting the ops routers"
        )
    return engine


def refuse_service_bearer(request: Request) -> None:
    """ADR-035 — the machine lane does not exist on the owner-only routes, so a
    request that presents a bearer is refused as unauthenticated, before the
    CSRF pair is considered → 401 ``unauthenticated``.

    Two frozen contracts require this answer and neither is satisfied by a 403:
    C6 §1 ("a bearer-only request is 401") and C5 contract test 5 (a valid
    ``SUNIL_SERVICE_TOKEN`` on ``GET /api/v1/approvals`` → 401 once Stream D
    lands). Before it, a bearer-only request answered 403 ``forbidden_client``
    because ADR-008's client-header check ran first and a machine caller sends
    no ``X-SUNIL-Client``.

    403 would also be the wrong *thing to say*. It names the client header as the
    obstacle, which invites the caller to add one — and no header makes this lane
    accept a bearer. 401 is the true answer and the one that discloses nothing.

    The token is **not validated here** and never reaches
    ``deps.require_service_token``: on this lane a bearer is refused whether it
    is real or forged, so there is no comparison to time and no path on which a
    valid machine credential is treated as more interesting than an invalid one.

    ADR-008's ordering is untouched for the case it exists to cover. A browser
    cross-site request cannot set ``Authorization`` at all, so a forged request
    still meets the client-header check first and is still refused 403 before
    anything session-backed runs (``test_routes.py::
    test_the_client_header_is_checked_before_the_session``).
    """
    if request.headers.get("Authorization") is not None:
        raise ApiError(
            401, "unauthenticated", "this endpoint has no service-token lane"
        )


async def require_owner_lane(request: Request) -> None:
    """The owner lane's gate, in contract order: ADR-035 first (above), then
    ADR-008's CSRF pair. Composed rather than merged so ``require_web_client``
    keeps its single meaning and its own tests."""
    refuse_service_bearer(request)
    await require_web_client(request)


OwnerSession = Annotated[str, Depends(require_owner_session)]
#: Every C4 and C6 route takes this one annotation, so the lane cannot be
#: half-applied: a route that forgets it has no owner check at all, rather than
#: one control out of two.
WebClient = Annotated[None, Depends(require_owner_lane)]


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
# The one seam call, and the post-decision effects that are not on any protocol
# --------------------------------------------------------------------------- #
async def run_post_decision_effect(
    service: object, approval_id: str, decision: str
) -> None:
    """C4 §3's two after-effects: refuse finalises the task ``failed`` /
    ``approval_refused``; approve schedules the continuation.

    Neither is on C4 §4's protocol and neither has a named method in the
    contract — §3 states the effect, not the caller — so each is invoked only
    when the wired service offers it, and its absence is a WARNING rather than a
    500. That is the treatment ``main._build_sweeper`` already gives the same
    class of gap ("no sweeper" on a service with no schedule): a service without
    a task gateway has no task to finalise, and refusing to answer the owner
    would turn a missing collaborator into an outage on a decision the owner has
    already made.

    A failing effect is logged and the 200 stands, for the same reason: the CAS
    has committed, the decision is the owner's, and C4 §3's startup
    reconciliation picks up an approved-but-unscheduled approval on the next
    boot. An exception here would tell the owner their decision failed when it
    did not.
    """
    if decision == "refuse":
        finalise = getattr(service, "finalise_refusal", None)
        if finalise is None:
            logger.warning(
                "approval refused but the wired service has no finalise_refusal(); "
                "C4 §3's task finalisation did not run for %s",
                approval_id,
            )
            return
        try:
            await finalise(approval_id)
        except Exception:  # noqa: BLE001
            logger.exception("failed to finalise refusal for %s", approval_id)
        return

    scheduler = getattr(service, "scheduler", None)
    if scheduler is None:
        logger.warning(
            "approval approved but the wired service has no continuation "
            "scheduler; ADR-031's resume does not run for %s",
            approval_id,
        )
        return
    try:
        await scheduler.schedule(approval_id)
    except Exception:  # noqa: BLE001
        logger.exception("failed to schedule continuation for %s", approval_id)


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
        engine = get_read_engine(request)
        response.headers.update(NOSNIFF)
        try:
            async with engine.connect() as conn:
                return await read_model.list_approvals(
                    conn, status=status, limit=limit, cursor=cursor
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
        engine = get_read_engine(request)
        async with engine.connect() as conn:
            approval = await read_model.get_approval(conn, approval_id)
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
        """The only mutating endpoint, and the only one that reaches the C4
        seam. Approving schedules the continuation; refusing finalises the
        parked task as ``failed`` / ``approval_refused`` (C4 §3). Both
        post-transition effects run only after the CAS reports a win, so a lost
        race schedules nothing and finalises nothing.
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

        await run_post_decision_effect(service, approval_id, body.decision)
        return JSONResponse(
            status_code=200, content=result.model_dump(mode="json"), headers=NOSNIFF
        )

    return router
