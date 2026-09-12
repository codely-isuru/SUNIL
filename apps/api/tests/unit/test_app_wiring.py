"""The integration seam between the spine's `create_app` and Stream D's routers.

Each lane was green alone: the spine mounted `health`/`auth`/`chat`, and Stream
D's C4 + C6 routers were exercised against a hand-built `FastAPI()` in
`tests/unit/{approvals,ops}`. Nothing asserted that the APPLICATION mounts them —
so the merged app served 404 on every ops path while both suites stayed green.
These tests are that assertion, and they are deliberately about the route TABLE
and the app STATE rather than about payloads: the payload laws are C6's and are
already graded in `tests/unit/ops/test_c6_ops_reads.py`.

The route-table walks here repeat two clauses of C6 contract test 9 verbatim.
That is not duplication for its own sake: those two clauses call
`main.create_app()` with no arguments, which wave 1's `wiring.py` cannot satisfy
(see `docs/tasks/integration-w1.md` §3), so they are red on a harness line while
the property they grade holds. Proving the property here keeps it defended while
QA fixes their harness.
"""

from __future__ import annotations

import pytest

from tests.ops_harness import C6_PATHS, SERVICE_TOKEN, WEB_HEADERS, build_ops_app, ops_client

#: C4's HTTP surface (`C4-approvals-openapi.yaml`), which the spine must mount
#: for the same reason: an unmounted approval queue is an owner who cannot
#: approve anything.
C4_PATHS = [
    "/api/v1/approvals",
    "/api/v1/approvals/{approval_id}",
    "/api/v1/approvals/{approval_id}/decision",
]


def methods_by_path(app) -> dict[str, set[str]]:
    registered: dict[str, set[str]] = {}
    for route in app.routes:
        verbs = {
            method
            for method in (getattr(route, "methods", None) or set())
            if method not in {"HEAD", "OPTIONS"}
        }
        if verbs:
            registered.setdefault(route.path, set()).update(verbs)
    return registered


def test_the_five_c6_operations_are_mounted_and_get_only() -> None:
    """C6 §1 — "No mutating verb exists on this surface; a POST/PUT/DELETE on
    these paths is 405 from the framework, not a handler." Read off the route
    table, so it holds without a request."""
    app, _ = build_ops_app()
    registered = methods_by_path(app)

    for path in C6_PATHS:
        assert path in registered, f"{path} is not mounted (C6 OpenAPI paths)"
        assert registered[path] == {"GET"}, (
            f"{path} must be GET-only (C6 §1); found {sorted(registered[path])}"
        )


def test_c4s_three_approval_routes_are_mounted_with_their_contract_verbs() -> None:
    """C4 §5 — three routes and exactly one of them mutates. In particular there
    is NO `POST /api/v1/approvals`: an HTTP creation surface could mint rows with
    no continuation."""
    app, _ = build_ops_app()
    registered = methods_by_path(app)

    assert registered.get("/api/v1/approvals") == {"GET"}
    assert registered.get("/api/v1/approvals/{approval_id}") == {"GET"}
    assert registered.get("/api/v1/approvals/{approval_id}/decision") == {"POST"}


def test_routes_are_mounted_flat_so_the_dependency_tree_stays_walkable() -> None:
    """The mount mechanism is load-bearing, not a style choice: `include_router()`
    on FastAPI >= 0.141 records a lazy `_IncludedRouter` instead of appending the
    routes, and `app.routes` then exposes no per-route `dependant` — which
    silently disarms the ONE audit that bounds a machine token's blast radius
    (C5 contract test 8 / C6 test 9). A regression to `include_router` passes
    every payload test and fails here."""
    app, _ = build_ops_app()

    for path in C6_PATHS + C4_PATHS:
        routes = [route for route in app.routes if getattr(route, "path", None) == path]
        assert routes, f"{path} is not mounted"
        assert all(getattr(route, "dependant", None) is not None for route in routes), (
            f"{path} has no walkable `dependant` — it was mounted via "
            "include_router() rather than flat onto app.router.routes"
        )


def test_no_c6_or_c4_route_accepts_the_adr_035_service_bearer() -> None:
    """C6 §1 / ADR-035, structural half — `require_service_token` is registered on
    `POST /api/v1/chat` ALONE. Matched by FUNCTION IDENTITY through FastAPI's
    flattened dependency tree, which is what catches the dangerous version of the
    bug: a dependency added to a ROUTER rather than a route."""
    from sunil.api import deps

    app, _ = build_ops_app()
    target = deps.require_service_token

    def uses(dependant, seen: set[int] | None = None) -> bool:
        if dependant is None:
            return False
        seen = seen if seen is not None else set()
        if id(dependant) in seen:
            return False
        seen.add(id(dependant))
        if getattr(dependant, "call", None) is target:
            return True
        return any(uses(child, seen) for child in getattr(dependant, "dependencies", []))

    bearer_routes = {
        route.path for route in app.routes if uses(getattr(route, "dependant", None))
    }

    assert bearer_routes & set(C6_PATHS + C4_PATHS) == set()
    assert bearer_routes == {"/api/v1/chat"}


async def test_the_ops_read_engine_is_wired_to_the_applications_database() -> None:
    """`ops_read_model.get_engine` reads `app.state.ops_engine`, and it raises
    rather than returning an empty page when it is unset — "an unwired ops route
    that returns {"tasks": []} looks exactly like a quiet system". The spine owns
    setting it, including when a test injects only a sessionmaker."""
    async with ops_client() as (client, app):
        assert app.state.ops_engine is not None
        assert app.state.ops_engine is app.state.sessionmaker.kw["bind"]
        listed = await client.get("/api/v1/tasks", headers=WEB_HEADERS)
        assert listed.status_code == 200, listed.text
        assert listed.json() == {"tasks": [], "next_cursor": None}


async def test_the_owner_identity_reaches_stream_ds_dependency() -> None:
    """Stream D's `require_owner_session` reads `request.state.owner_user_id`,
    which it documents as "the identity ADR-007 session middleware established".
    Nothing established it before this round, so every ops read 401'd behind a
    valid cookie. The spine publishes it from the session it already signs —
    one definition of the owner, not a second cookie reader."""
    async with ops_client() as (client, _app):
        me = await client.get("/api/v1/auth/me", headers=WEB_HEADERS)
        assert me.status_code == 200
        activity = await client.get("/api/v1/activity", headers=WEB_HEADERS)
        assert activity.status_code == 200, activity.text


async def test_the_cross_origin_check_is_armed_on_stream_ds_routes() -> None:
    """Stream D's `require_web_client` compares `Origin` against
    `app.state.web_origin` and SKIPS the comparison when it is unset. Unset, the
    check is not lenient — it is absent, and the ADR-008 CSRF pair is down to one
    header. The spine sets it from `WEB_ORIGIN`."""
    async with ops_client() as (client, app):
        assert app.state.web_origin == app.state.settings.web_origin
        refused = await client.get(
            "/api/v1/tasks",
            headers={"X-SUNIL-Client": "web", "Origin": "http://evil.invalid"},
        )
        assert refused.status_code == 403
        assert refused.json()["error"]["kind"] == "forbidden_client"


async def test_stream_ds_error_envelope_is_rendered_by_the_application() -> None:
    """`routes/approvals.py` raises its OWN `ApiError` class, not
    `api/errors.ApiError`. An app that registered only the spine's handler would
    turn every Stream D refusal into a 500 — and a 500 on an auth refusal is an
    outage, not a denial. Both classes are handled, and Stream D's carries C4
    §4's nosniff header."""
    async with ops_client(sign_in=False) as (client, _app):
        refused = await client.get("/api/v1/tasks", headers=WEB_HEADERS)
        assert refused.status_code == 401
        assert refused.json() == {
            "error": {"kind": "unauthenticated", "message": "no valid owner session"}
        }
        assert refused.headers["X-Content-Type-Options"] == "nosniff"


async def test_the_spines_own_validation_envelope_is_not_replaced() -> None:
    """Stream D's `install_error_handlers` also rebinds `RequestValidationError`,
    which would silently re-word every 422 the C5 chat route promises. The spine
    registers Stream D's `ApiError` handler ALONE, so both lanes keep their own
    contracted 422 text."""
    async with ops_client() as (client, _app):
        invalid = await client.get("/api/v1/tasks?limit=0", headers=WEB_HEADERS)
        assert invalid.status_code == 422
        assert invalid.json()["error"]["kind"] == "validation_error"


@pytest.mark.parametrize("path", C6_PATHS)
async def test_a_valid_service_bearer_cannot_read_a_c6_route(path: str) -> None:
    """ADR-035 at request level — a leaked service token must not read tasks,
    activity or the audit trail. 401, never 200."""
    concrete = path.replace("{task_id}", "task-1").replace("{request_id}", "req-1")
    async with ops_client(service_token=SERVICE_TOKEN, sign_in=False) as (client, _app):
        answered = await client.get(
            concrete,
            headers={**WEB_HEADERS, "Authorization": f"Bearer {SERVICE_TOKEN}"},
        )
        assert answered.status_code == 401
        assert answered.json()["error"]["kind"] == "unauthenticated"


@pytest.mark.parametrize("path", ["/api/v1/approvals", *C6_PATHS])
async def test_a_bearer_only_request_is_401_on_the_owner_lane_not_403(path: str) -> None:
    """Two frozen contracts meet on this request and only one answer satisfies
    both: C6 §1 — "a bearer-only request is 401" (and C6 §6 test 9 clause 3:
    "never 403") — and C5 contract test 5, which asserts `in (401, 404)` on
    `GET /api/v1/approvals` and records that it "tightens to == 401" the moment
    Stream D lands. It has landed, and before this round the answer was 403,
    because the ADR-008 CSRF pair ran first and a bearer-only request carries no
    `X-SUNIL-Client`.

    The reconciliation is ADR-035's own rule, applied symmetrically: a caller
    presenting an `Authorization` header is a MACHINE-lane attempt, and the
    machine lane does not exist on the owner-only routes. Answering
    `403 forbidden_client` would tell that caller its CLIENT HEADER was the
    problem — an invitation to add one — when no header can make this lane
    accept a bearer. 401 is both the true answer and the one that says nothing.

    The CSRF ordering D-be pinned is untouched: a request with NO bearer and no
    client header is still 403 before any session logic runs
    (`test_the_client_header_is_checked_before_the_session`), because a browser
    cross-site request cannot set `Authorization` in the first place.
    """
    concrete = path.replace("{task_id}", "task-1").replace("{request_id}", "req-1")
    async with ops_client(service_token=SERVICE_TOKEN, sign_in=False) as (client, _app):
        answered = await client.get(
            concrete, headers={"Authorization": f"Bearer {SERVICE_TOKEN}"}
        )
        assert answered.status_code == 401
        assert answered.json()["error"]["kind"] == "unauthenticated"


@pytest.mark.parametrize("path", ["/api/v1/approvals", *C6_PATHS])
async def test_a_cookie_less_browser_request_is_still_refused_at_the_header(
    path: str,
) -> None:
    """The other half of the rule above: with no `Authorization` header the
    ADR-008 ordering is unchanged — no client header → 403 `forbidden_client`,
    before anything session-backed runs."""
    concrete = path.replace("{task_id}", "task-1").replace("{request_id}", "req-1")
    async with ops_client(sign_in=False) as (client, _app):
        answered = await client.get(concrete)
        assert answered.status_code == 403
        assert answered.json()["error"]["kind"] == "forbidden_client"
