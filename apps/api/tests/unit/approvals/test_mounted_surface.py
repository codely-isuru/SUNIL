"""C4's three routes, driven by an AUTHORISED owner through the real application.

The gap this module closes (QA wave-1 finding B1). Every existing approvals test
reached the routes one of two ways: `tests/unit/approvals/test_routes.py` mounts
the router on a hand-built app wired with the real `DatabaseApprovalsService`,
and `tests/unit/test_app_wiring.py` drives the mounted routes only on their
REFUSAL paths (401/403). So nothing asserted that a signed-in owner gets an
answer out of the mounted C4 surface, and the mounted surface answered 500 —
`TypeError: object ApprovalListResponse can't be used in 'await' expression` —
because the routes awaited service methods that C4 §4's frozen protocol does not
declare (`list_approvals`, `get`), which the C4 §6 fake therefore implements
synchronously. The C6 equivalent of this module's first test already existed
(`test_the_ops_read_engine_is_wired_to_the_applications_database`); this is its
C4 mirror.

**Both C4 seam shapes are exercised, because the point is that the surface no
longer depends on which one is wired.** The reads go through the database read
model (`core/approvals/read_model.py`) exactly as the C6 route trio does, so
they answer identically under C4 §6's fake and under the real service; only the
decision route — the one operation C4 §6.2 puts on the service layer
normatively — talks to the seam.

**Schema note — the workaround is gone (wave-1 ruling R2, applied in the wave-2
wiring round).** This module used to create the spine's tables MINUS `approvals`
because `db/models.py::Approval` declared the same table with STRING timestamps,
so a plain `Base.metadata.create_all` built a table no deployment has. That false
declaration has been deleted and `db/autogenerate.py` fences the name out of
Alembic's comparison, so the spine's metadata and Stream D's
`APPROVALS_METADATA` are now disjoint by construction: the full schema is built
here, exactly as a migrated deployment runs it, and a filter that once hid a real
disagreement no longer hides anything.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx

from sunil.core.approvals.base import ApprovalStatus, ParkRequest
from sunil.core.approvals.table import APPROVALS_METADATA

from tests.ops_harness import OWNER_PASSWORD, OWNER_USERNAME, WEB_HEADERS, build_ops_app
from tests.unit.approvals import factory


def park_request(*, summary: str = "github.create_issue requires approval") -> ParkRequest:
    return ParkRequest(
        agent_id="project_manager",
        tool="github",
        operation="create_issue",
        args_hash="a" * 64,
        params_redacted={"repo": "codely/sunil", "title": "<script>x</script>"},
        request_id="req-1",
        conversation_id="conv-1",
        task_id="task-1",
        summary=summary,
        continuation={"plan": [], "cursor": 0},
    )


def real_service(engine):
    """The real C4 service on the application's OWN engine."""
    return factory.make_service(engine, clock=lambda: datetime.now(UTC))


@asynccontextmanager
async def mounted(*, approvals_factory=None) -> AsyncIterator[tuple]:
    """The real `create_app`, a real signed cookie, and the deployed schema.

    Yields `(client, app, engine)`. `approvals_factory` selects the C4 seam; the
    default is C4 §6's fake, which is what `wiring.py` can currently boot
    (integration-w1 §5.3).
    """
    from sunil.api.routes.auth import hash_password
    from sunil.db.base import Base, new_uuid
    from sunil.db.models import User

    app, sessionmaker = build_ops_app(approvals_factory=approvals_factory)
    engine = sessionmaker.kw["bind"]
    async with engine.begin() as connection:
        # The whole deployed schema: the spine's metadata (which no longer
        # declares `approvals` — R2) plus Stream D's, whose `approvals` is the
        # one the migration chain creates.
        await connection.run_sync(Base.metadata.create_all)
        await connection.run_sync(APPROVALS_METADATA.create_all)

    async with sessionmaker() as session:
        session.add(
            User(
                id=new_uuid(),
                name="Owner",
                username=OWNER_USERNAME,
                password_hash=hash_password(OWNER_PASSWORD),
            )
        )
        await session.commit()

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        signed_in = await client.post(
            "/api/v1/auth/login",
            json={"username": OWNER_USERNAME, "password": OWNER_PASSWORD},
            headers=WEB_HEADERS,
        )
        assert signed_in.status_code == 200, signed_in.text
        yield client, app, engine
    await engine.dispose()


# --------------------------------------------------------------------------- #
# The reads — the database read model, under the FAKE seam
# --------------------------------------------------------------------------- #
async def test_the_mounted_list_answers_the_authorised_owner() -> None:
    """`GET /api/v1/approvals` → 200 for a signed-in owner, carrying the parked
    rows newest-first. The C4 mirror of C6's
    `test_the_ops_read_engine_is_wired_to_the_applications_database`."""
    async with mounted() as (client, _app, engine):
        service = real_service(engine)
        first = await service.park(park_request(summary="first"))
        second = await service.park(park_request(summary="second"))

        listed = await client.get("/api/v1/approvals", headers=WEB_HEADERS)

        assert listed.status_code == 200, listed.text
        body = listed.json()
        assert [row["id"] for row in body["approvals"]] == [
            second.approval_id,
            first.approval_id,
        ]
        assert body["next_cursor"] is None
        assert {row["status"] for row in body["approvals"]} == {"pending"}
        assert listed.headers["X-Content-Type-Options"] == "nosniff"


async def test_the_mounted_list_filters_by_status_and_pages() -> None:
    """C4 §6.5's law through the mounted route: the `status` filter and the
    `limit`/`cursor` page walk, which is what the dashboard queue polls."""
    async with mounted() as (client, _app, engine):
        service = real_service(engine)
        parked = [await service.park(park_request()) for _ in range(3)]

        page = await client.get(
            "/api/v1/approvals?status=pending&limit=2", headers=WEB_HEADERS
        )
        assert page.status_code == 200, page.text
        first_page = page.json()
        assert len(first_page["approvals"]) == 2
        assert first_page["next_cursor"] == first_page["approvals"][-1]["id"]

        rest = await client.get(
            f"/api/v1/approvals?limit=2&cursor={first_page['next_cursor']}",
            headers=WEB_HEADERS,
        )
        assert rest.status_code == 200, rest.text
        assert [row["id"] for row in rest.json()["approvals"]] == [
            parked[0].approval_id
        ]

        empty = await client.get("/api/v1/approvals?status=refused", headers=WEB_HEADERS)
        assert empty.status_code == 200
        assert empty.json() == {"approvals": [], "next_cursor": None}


async def test_the_mounted_list_answers_an_unknown_cursor_with_422() -> None:
    """An unresolvable cursor is a client bug, not page one — a "Load more" loop
    that restarts for ever is the failure this 422 exists to prevent."""
    async with mounted() as (client, _app, _engine):
        answered = await client.get(
            "/api/v1/approvals?cursor=apr-nope", headers=WEB_HEADERS
        )
        assert answered.status_code == 422, answered.text
        assert answered.json()["error"]["kind"] == "validation_error"


async def test_the_mounted_detail_answers_200_and_never_leaks_the_continuation() -> None:
    """`GET /api/v1/approvals/{id}` → 200 with the full redacted detail, and
    WITHOUT `continuation` — C4 §4: it never leaves this service over HTTP. The
    untrusted `summary`/`params_redacted` values come back byte-faithful (C4 §4's
    server-side half of the plain-text rule)."""
    async with mounted() as (client, _app, engine):
        service = real_service(engine)
        parked = await service.park(park_request(summary="<b>not markup</b>"))

        detail = await client.get(
            f"/api/v1/approvals/{parked.approval_id}", headers=WEB_HEADERS
        )

        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["id"] == parked.approval_id
        assert body["status"] == "pending"
        assert body["summary"] == "<b>not markup</b>"
        assert body["params_redacted"]["title"] == "<script>x</script>"
        assert "continuation" not in body
        assert detail.headers["X-Content-Type-Options"] == "nosniff"


async def test_the_mounted_detail_answers_404_for_an_unknown_id() -> None:
    async with mounted() as (client, _app, _engine):
        missing = await client.get("/api/v1/approvals/apr-nope", headers=WEB_HEADERS)
        assert missing.status_code == 404, missing.text
        assert missing.json()["error"]["kind"] == "not_found"


# --------------------------------------------------------------------------- #
# The decision — the one operation C4 §6.2 puts on the service layer
# --------------------------------------------------------------------------- #
async def test_the_mounted_decision_approves_for_the_authorised_owner() -> None:
    """`POST /api/v1/approvals/{id}/decision` → 200 through the mounted app, and
    the read the dashboard makes next sees the SAME row decided — proving the
    route's seam and the route's read model are one database, not two."""
    async with mounted(approvals_factory=real_service) as (client, _app, engine):
        service = _app_service(_app)
        parked = await service.park(park_request())

        decided = await client.post(
            f"/api/v1/approvals/{parked.approval_id}/decision",
            json={"decision": "approve", "reason": "looks right"},
            headers=WEB_HEADERS,
        )

        assert decided.status_code == 200, decided.text
        body = decided.json()
        assert body["status"] == ApprovalStatus.APPROVED.value
        assert body["decided_by"] == "owner"
        assert body["decision_reason"] == "looks right"

        again = await client.post(
            f"/api/v1/approvals/{parked.approval_id}/decision",
            json={"decision": "approve"},
            headers=WEB_HEADERS,
        )
        assert again.status_code == 409, again.text
        assert again.json()["error"]["current_status"] == "approved"

        detail = await client.get(
            f"/api/v1/approvals/{parked.approval_id}", headers=WEB_HEADERS
        )
        assert detail.json()["status"] == "approved"


async def test_the_mounted_decision_refuses_and_does_not_500_without_a_task_gateway() -> None:
    """Refuse → 200 and `refused`. C4 §3's task finalisation runs through the
    service's OWN gateway seam; a service wired without one must still answer the
    owner rather than 500 on a post-transition effect."""
    async with mounted(approvals_factory=real_service) as (client, _app, _engine):
        service = _app_service(_app)
        parked = await service.park(park_request())

        refused = await client.post(
            f"/api/v1/approvals/{parked.approval_id}/decision",
            json={"decision": "refuse", "reason": "no"},
            headers=WEB_HEADERS,
        )

        assert refused.status_code == 200, refused.text
        assert refused.json()["status"] == "refused"


async def test_the_mounted_decision_answers_the_contract_codes_end_to_end() -> None:
    """**C4 v1.2.0 (wave-1 ruling R7): the 501 is gone.**

    The wave-1 surface probed the wired seam for an awaitable service-layer
    `decide` and answered 501 when it found none, because C4 §6.2's v1.0.1 shape
    was the fake's — synchronous, with `now` supplied by its caller — and a real
    HTTP layer owns no clock. R7 moved the contract to the shape the database
    service already implements, so the probe is dead code and this is what
    replaces its test: the full status map (200 / 409 / 404) through the mounted
    route on a REAL, bootable wiring, where the seam and the read model are one
    database.

    The fake-wired half of the ruling's replacement (the same request against
    C4 §6's fake) lands with QA's parcel 1, which makes the fake's `decide`
    awaitable — it is their file, and asserting it here before that would fail on
    a shape nobody has changed yet.
    """
    async with mounted(approvals_factory=real_service) as (client, _app, _engine):
        service = _app_service(_app)
        parked = await service.park(park_request())
        path = f"/api/v1/approvals/{parked.approval_id}/decision"

        decided = await client.post(
            path, json={"decision": "approve"}, headers=WEB_HEADERS
        )
        assert decided.status_code == 200, decided.text
        assert decided.json()["status"] == ApprovalStatus.APPROVED.value

        repeated = await client.post(
            path, json={"decision": "refuse"}, headers=WEB_HEADERS
        )
        assert repeated.status_code == 409, repeated.text
        assert repeated.json()["error"]["current_status"] == "approved"

        missing = await client.post(
            "/api/v1/approvals/apr-nope/decision",
            json={"decision": "approve"},
            headers=WEB_HEADERS,
        )
        assert missing.status_code == 404, missing.text
        assert missing.json()["error"]["kind"] == "not_found"


def _app_service(app):
    """The C4 seam the application actually resolved — not a second instance
    over the same engine, which is how a test proves a route works while the
    application's own service is doing something else."""
    return app.state.approvals_service
