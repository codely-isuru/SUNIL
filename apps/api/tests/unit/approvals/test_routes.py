"""C4's HTTP surface against the real service — status mapping and auth.

``C4-approvals-openapi.yaml`` is the contract under test: the three routes, the
five error kinds, the 409 body that carries ``current_status``, and the absence
of a creation endpoint. Every test drives a real ``DatabaseApprovalsService`` on
a real engine through ``httpx.ASGITransport``, so nothing here is mocked except
the owner session (whose signing is ADR-007 middleware the spine owns).
"""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI, Request

from sunil.api.routes.approvals import (
    CLIENT_HEADER,
    CLIENT_VALUE,
    create_router,
    install_error_handlers,
)
from sunil.core.approvals.base import ApprovalStatus

from tests.fakes.clock import FakeClock
from tests.unit.approvals import factory
from tests.unit.approvals.test_real_service_contract import park_request

WEB_ORIGIN = "http://localhost:3001"
AUTH = {CLIENT_HEADER: CLIENT_VALUE, "Origin": WEB_ORIGIN}


class RecordingScheduler:
    def __init__(self) -> None:
        self.scheduled: list[str] = []

    async def schedule(self, approval_id: str) -> None:
        self.scheduled.append(approval_id)


class RecordingTasks:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    async def is_finalised(self, task_id: str) -> bool:
        return False

    async def finalise_failed(self, task_id: str, *, failure_kind: str) -> None:
        self.calls.append((task_id, failure_kind))


@pytest.fixture
async def app_and_service():
    """A minimal app carrying just this router, plus a session middleware stub
    standing in for ADR-007's. Deliberately minimal: the spine's ``create_app``
    does not exist in this worktree, and a test that needed it could not run."""
    engine = await factory.make_engine(factory.SQLITE_URL)
    clock = FakeClock()
    scheduler = RecordingScheduler()
    tasks = RecordingTasks()
    service = factory.make_service(
        engine, clock=clock.now, scheduler=scheduler, tasks=tasks
    )

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(create_router())
    app.state.approvals_service = service
    app.state.web_origin = WEB_ORIGIN
    app.state.session_owner = "owner"

    @app.middleware("http")
    async def session_stub(request: Request, call_next):
        # Stands in for ADR-007 session middleware: establishes the identity on
        # request.state exactly as the route's dependency expects to find it.
        owner = request.app.state.session_owner
        if owner:
            request.state.owner_user_id = owner
        return await call_next(request)

    try:
        yield app, service, clock, scheduler, tasks
    finally:
        await engine.dispose()


@pytest.fixture
async def client(app_and_service):
    app = app_and_service[0]
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as c:
        yield c


async def _park(service, clock, **kwargs) -> str:
    parked = await service.park(park_request(**kwargs))
    clock.advance(seconds=1)
    return parked.approval_id


# --------------------------------------------------------------------------- #
# Happy paths
# --------------------------------------------------------------------------- #
async def test_list_returns_the_contract_envelope(client, app_and_service) -> None:
    """``ApprovalListResponse`` = ``{approvals, next_cursor}``, both required."""
    _, service, clock, _, _ = app_and_service
    first = await _park(service, clock)
    second = await _park(service, clock)

    response = await client.get("/api/v1/approvals", headers=AUTH)

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"approvals", "next_cursor"}
    assert [a["id"] for a in body["approvals"]] == [second, first]
    assert body["next_cursor"] is None


async def test_list_filters_and_pages_exactly_as_the_service_does(
    client, app_and_service
) -> None:
    """The route adds no ordering or paging of its own — C4 §6.5's rules,
    including the exactly-full-final-page cursor QA pinned."""
    _, service, clock, _, _ = app_and_service
    ids = [await _park(service, clock) for _ in range(4)]
    await service.decide(ids[0], "refuse")

    pending = await client.get(
        "/api/v1/approvals", params={"status": "pending"}, headers=AUTH
    )
    assert [a["id"] for a in pending.json()["approvals"]] == [ids[3], ids[2], ids[1]]

    page = await client.get("/api/v1/approvals", params={"limit": 2}, headers=AUTH)
    assert page.json()["next_cursor"] == ids[2]
    final = await client.get(
        "/api/v1/approvals",
        params={"limit": 2, "cursor": ids[2]},
        headers=AUTH,
    )
    assert [a["id"] for a in final.json()["approvals"]] == [ids[1], ids[0]]
    assert final.json()["next_cursor"] == ids[0]  # full page, nothing left


async def test_detail_returns_every_required_approval_field(
    client, app_and_service
) -> None:
    """C4 OpenAPI ``Approval``'s required list, and the continuation's absence:
    it is persisted but never serialised over HTTP (C4 §4)."""
    _, service, clock, _, _ = app_and_service
    approval_id = await _park(service, clock)

    body = (await client.get(f"/api/v1/approvals/{approval_id}", headers=AUTH)).json()

    for field in (
        "id",
        "status",
        "created_at",
        "expires_at",
        "agent_id",
        "tool",
        "operation",
        "args_hash",
        "params_redacted",
        "request_id",
        "conversation_id",
        "task_id",
        "summary",
    ):
        assert field in body, field
    assert "continuation" not in body
    assert body["status"] == "pending"


async def test_approve_returns_the_row_and_schedules_the_continuation(
    client, app_and_service
) -> None:
    """C4 §3 — the decision endpoint returns immediately and the service
    schedules the continuation (ADR-031)."""
    _, service, clock, scheduler, tasks = app_and_service
    approval_id = await _park(service, clock)

    response = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "approve"},
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert response.json()["decided_by"] == "owner"
    assert scheduler.scheduled == [approval_id]
    assert tasks.calls == []


async def test_refuse_finalises_the_task_and_schedules_nothing(
    client, app_and_service
) -> None:
    """C4 §3 — refuse → no execution, task finalised ``approval_refused``."""
    _, service, clock, scheduler, tasks = app_and_service
    approval_id = await _park(service, clock)

    response = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "refuse", "reason": "too expensive"},
        headers=AUTH,
    )

    assert response.status_code == 200
    assert response.json()["status"] == "refused"
    assert response.json()["decision_reason"] == "too expensive"
    assert scheduler.scheduled == []
    assert tasks.calls == [("task-1", "approval_refused")]


# --------------------------------------------------------------------------- #
# Status mapping — C4 §5
# --------------------------------------------------------------------------- #
async def test_unknown_approval_is_404_in_the_contract_envelope(client) -> None:
    """C4 §5 / the YAML's ``NotFound`` response."""
    for method, path in (
        ("get", "/api/v1/approvals/apr-nope"),
        ("post", "/api/v1/approvals/apr-nope/decision"),
    ):
        response = await getattr(client, method)(
            path, headers=AUTH, **({"json": {"decision": "approve"}} if method == "post" else {})
        )
        assert response.status_code == 404
        assert response.json()["error"]["kind"] == "not_found"


@pytest.mark.parametrize("second", ["approve", "refuse"])
async def test_a_repeated_decision_is_409_with_the_true_status(
    client, app_and_service, second: str
) -> None:
    """C4 §5 — "Decision idempotency is deliberately NOT provided: repeating a
    decision returns 409 so the UI must show the true state rather than a
    comforting echo." The body's ``current_status`` is the winner's, not the
    repeat caller's intent."""
    _, service, clock, scheduler, _ = app_and_service
    approval_id = await _park(service, clock)
    await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "approve"},
        headers=AUTH,
    )

    response = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": second},
        headers=AUTH,
    )

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["kind"] == "state_conflict"
    assert error["current_status"] == "approved"
    assert "message" in error
    # The loser scheduled nothing: only the winning transition may resume.
    assert scheduler.scheduled == [approval_id]


async def test_expiry_at_decision_time_is_a_409_expired_not_a_410(
    client, app_and_service
) -> None:
    """C4 §5 — "expiry at decision time is a 409 with
    ``current_status=expired``, not a separate 410". One conflict shape means
    the dashboard has one branch to render, not two."""
    _, service, clock, scheduler, _ = app_and_service
    approval_id = await _park(service, clock)
    clock.advance(hours=73)

    response = await client.post(
        f"/api/v1/approvals/{approval_id}/decision",
        json={"decision": "approve"},
        headers=AUTH,
    )

    assert response.status_code == 409
    assert response.json()["error"]["current_status"] == "expired"
    assert scheduler.scheduled == []
    assert (await service.get(approval_id)).status == ApprovalStatus.EXPIRED


@pytest.mark.parametrize(
    "body",
    [
        {},  # `decision` is required
        {"decision": "maybe"},  # not in the enum
        {"decision": "approve", "extra": 1},  # additionalProperties: false
        {"decision": "approve", "reason": "x" * 1001},  # maxLength 1000
    ],
    ids=["missing", "bad-enum", "extra-property", "over-long-reason"],
)
async def test_a_bad_decision_body_is_422_in_the_contract_envelope(
    client, app_and_service, body: dict
) -> None:
    """C4 ``DecisionRequest`` has ``additionalProperties: false`` and a 1000-char
    reason cap. FastAPI's default 422 body is ``{"detail": [...]}``, which is
    NOT C4's ``ErrorResponse`` — so the handler is what makes the YAML's 422
    true rather than aspirational."""
    _, service, clock, _, _ = app_and_service
    approval_id = await _park(service, clock)

    response = await client.post(
        f"/api/v1/approvals/{approval_id}/decision", json=body, headers=AUTH
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "validation_error"
    assert "detail" not in response.json()
    assert (await service.get(approval_id)).status == ApprovalStatus.PENDING


@pytest.mark.parametrize(
    "params", [{"limit": 0}, {"limit": 201}, {"status": "invented"}]
)
async def test_bad_list_parameters_are_422(client, params: dict) -> None:
    """The YAML's bounds: ``limit`` 1..200, ``status`` in the enum."""
    response = await client.get("/api/v1/approvals", params=params, headers=AUTH)

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "validation_error"


async def test_an_unknown_cursor_is_422_not_page_one(client, app_and_service) -> None:
    """An unresolvable cursor must fail loudly. Serving page one instead would
    turn a stale "Load more" into an infinite loop that silently re-shows rows
    the user already decided."""
    _, service, clock, _, _ = app_and_service
    await _park(service, clock)

    response = await client.get(
        "/api/v1/approvals", params={"cursor": "apr-nope"}, headers=AUTH
    )

    assert response.status_code == 422
    assert response.json()["error"]["kind"] == "validation_error"


# --------------------------------------------------------------------------- #
# Auth — C4's two security schemes
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "headers,expected",
    [
        ({}, 403),  # no client header at all
        ({CLIENT_HEADER: "curl"}, 403),  # wrong value
        ({CLIENT_HEADER: CLIENT_VALUE, "Origin": "http://evil.example"}, 403),
        # ADR-008 Amendment 1 (wave-1 ruling R3): an ABSENT `Origin` is a
        # mismatch, not a tolerated omission.
        ({CLIENT_HEADER: CLIENT_VALUE}, 403),
    ],
    ids=["no-header", "wrong-header", "wrong-origin", "absent-origin"],
)
async def test_the_client_header_and_origin_gate_every_route(
    client, headers: dict, expected: int
) -> None:
    """C4 ``clientHeader`` / ADR-008 — 403 ``forbidden_client``. Applied to the
    READ routes too, not just the mutating one: the queue is a list of the
    owner's pending privileged actions, which is itself information worth
    protecting."""
    for path in ("/api/v1/approvals", "/api/v1/approvals/apr-1"):
        response = await client.get(path, headers=headers)
        assert response.status_code == expected
        assert response.json()["error"]["kind"] == "forbidden_client"


async def test_an_unset_web_origin_refuses_rather_than_waiving_the_comparison(
    client, app_and_service
) -> None:
    """ADR-008 Amendment 1 rule 2 — the comparison must not soft-skip on unset
    state. `web_origin` is required wiring, not an optional attribute: an app
    that never set it serves a locked door, not the CSRF pair with one control
    silently removed (integration-w1 §2.2 gap 3, demonstrated once already).

    Driven through the route rather than the function, because the failure this
    prevents is a deployment one: the `getattr(..., None)` default made a wiring
    omission indistinguishable from a policy decision.
    """
    app = app_and_service[0]
    del app.state.web_origin

    response = await client.get("/api/v1/approvals", headers=AUTH)

    assert response.status_code == 403
    assert response.json()["error"]["kind"] == "forbidden_client"


async def test_no_owner_session_is_401(client, app_and_service) -> None:
    """C4 ``sessionCookie`` — approvals are owner-only."""
    app = app_and_service[0]
    app.state.session_owner = None

    response = await client.get("/api/v1/approvals", headers=AUTH)

    assert response.status_code == 401
    assert response.json()["error"]["kind"] == "unauthenticated"


async def test_the_route_fails_closed_when_session_middleware_is_absent() -> None:
    """The failure mode that matters: an app wired WITHOUT ADR-007's session
    middleware must serve 401, not serve approvals unauthenticated. A locked
    door, not an open one."""
    engine = await factory.make_engine(factory.SQLITE_URL)
    try:
        app = FastAPI()
        install_error_handlers(app)
        app.include_router(create_router())
        app.state.approvals_service = factory.make_service(
            engine, clock=FakeClock().now
        )
        app.state.web_origin = WEB_ORIGIN
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://testserver",
            # A forged, unverified session cookie must not substitute for the
            # middleware's verified identity.
            cookies={"sunil_session": "forged"},
        ) as c:
            response = await c.get("/api/v1/approvals", headers=AUTH)
        assert response.status_code == 401
        assert response.json()["error"]["kind"] == "unauthenticated"
    finally:
        await engine.dispose()


async def test_the_client_header_is_checked_before_the_session(
    client, app_and_service
) -> None:
    """Ordering, pinned: a request with no session AND no client header gets
    403, so a forged cross-site request is refused before any session-backed
    logic runs."""
    app = app_and_service[0]
    app.state.session_owner = None

    response = await client.get("/api/v1/approvals")

    assert response.status_code == 403


# --------------------------------------------------------------------------- #
# Scope + the plain-text rule's server-side half
# --------------------------------------------------------------------------- #
async def test_there_is_no_approval_creation_endpoint(client) -> None:
    """C4 §5's scope note — approvals are minted only by the in-process ``park``
    seam. An HTTP creation surface would let a caller mint a row with no
    persisted continuation and a binding the server did not compute."""
    response = await client.post(
        "/api/v1/approvals", json={"tool": "github"}, headers=AUTH
    )

    assert response.status_code == 405


async def test_untrusted_summary_and_params_survive_byte_for_byte(
    client, app_and_service
) -> None:
    """C4 §4 / Security review item 8, server-side half.

    ``summary`` embeds attacker-influenceable values. The API returns them as
    JSON string data, unchanged — NOT HTML-escaped, because escaping here would
    corrupt the value for every non-HTML consumer and would let the dashboard
    believe it had been made safe upstream. Containment is the renderer's job;
    the API's job is to transmit the bytes faithfully and to forbid sniffing.
    """
    _, service, clock, _, _ = app_and_service
    hostile = '<script>alert("x")</script> & "quotes" ‮RLO'
    approval_id = await _park(service, clock, summary=hostile)

    response = await client.get(f"/api/v1/approvals/{approval_id}", headers=AUTH)

    assert response.json()["summary"] == hostile
    assert response.headers["content-type"].startswith("application/json")
    assert response.headers["x-content-type-options"] == "nosniff"
    # No HTML entity substitution happened anywhere in the body.
    assert "&lt;script&gt;" not in response.text


async def test_every_error_response_also_carries_nosniff(client) -> None:
    """The error envelope is a rendering surface too — a 422 message or a 409
    body must not be sniffable as HTML either."""
    for response in (
        await client.get("/api/v1/approvals"),  # 403
        await client.get("/api/v1/approvals", params={"limit": 0}, headers=AUTH),  # 422
        await client.get("/api/v1/approvals/apr-nope", headers=AUTH),  # 404
    ):
        assert response.headers["x-content-type-options"] == "nosniff"
