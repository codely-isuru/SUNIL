"""Unit tests for `sunil.api.middleware.RequestContextMiddleware` (T5).

Tested against a minimal standalone Starlette app carrying only this one
middleware — deliberately not `sunil.main.create_app()` — so the test is
scoped to the middleware's own behaviour and does not need a database, a
config directory, or the rest of the lifespan.
"""

from __future__ import annotations

import uuid

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.testclient import TestClient
from sunil.api.middleware import RequestContextMiddleware, is_valid_uuid4


async def _echo(request):
    return JSONResponse(
        {
            "request_id": request.state.request_id,
            "has_turn_clock": hasattr(request.state, "turn_started_monotonic"),
        }
    )


def _build_app() -> Starlette:
    return Starlette(
        routes=[Route("/echo", _echo)],
        middleware=[Middleware(RequestContextMiddleware)],
    )


def test_is_valid_uuid4_accepts_a_real_uuid4() -> None:
    assert is_valid_uuid4(str(uuid.uuid4())) is True


def test_is_valid_uuid4_rejects_garbage() -> None:
    assert is_valid_uuid4("not-a-uuid") is False


def test_is_valid_uuid4_rejects_a_non_v4_uuid() -> None:
    # A well-formed v1 UUID is still a UUID, but not v4.
    v1 = uuid.uuid1()
    assert is_valid_uuid4(str(v1)) is False


def test_a_supplied_valid_uuid4_is_accepted_and_echoed_back() -> None:
    client = TestClient(_build_app())
    request_id = str(uuid.uuid4())

    response = client.get("/echo", headers={"X-Request-Id": request_id})

    assert response.status_code == 200
    assert response.json()["request_id"] == request_id
    assert response.headers["x-request-id"] == request_id


def test_no_supplied_request_id_generates_one() -> None:
    client = TestClient(_build_app())

    response = client.get("/echo")

    assert response.status_code == 200
    generated = response.json()["request_id"]
    assert is_valid_uuid4(generated)
    assert response.headers["x-request-id"] == generated


def test_an_invalid_supplied_request_id_is_rejected_with_422() -> None:
    client = TestClient(_build_app())

    response = client.get("/echo", headers={"X-Request-Id": "not-a-real-uuid"})

    assert response.status_code == 422


def test_turn_clock_is_started_on_every_request() -> None:
    client = TestClient(_build_app())

    response = client.get("/echo")

    assert response.json()["has_turn_clock"] is True


def test_build_session_middleware_unwraps_the_secret_and_is_usable() -> None:
    """`sunil.main.create_app()` used to call
    `settings.session_secret.get_secret_value()` directly, which
    `tests/security/test_import_boundaries.py
    ::test_agents_never_unwrap_a_secret` correctly flags: `sunil/main.py`
    is not on that test's allow-list (`providers/`, `tools/`, `db/`,
    `api/`, `settings.py`, `redaction.py`). This factory moves the unwrap
    into `sunil/api/middleware.py`, which is — `main.py` calls this
    instead of unwrapping the secret itself."""
    from dataclasses import dataclass

    from starlette.applications import Starlette
    from starlette.responses import Response
    from starlette.routing import Route
    from sunil.api.middleware import build_session_middleware

    @dataclass
    class _FakeSecretStr:
        value: str

        def get_secret_value(self) -> str:
            return self.value

    @dataclass
    class _FakeSettings:
        session_secret: _FakeSecretStr
        session_cookie_name: str = "sunil_session"

    settings = _FakeSettings(session_secret=_FakeSecretStr("a-fake-session-secret-for-this-test"))
    middleware = build_session_middleware(settings)

    async def _set_session(request):
        request.session["marker"] = "present"
        return Response(status_code=204)

    app = Starlette(routes=[Route("/set", _set_session, methods=["POST"])], middleware=[middleware])
    client = TestClient(app)

    response = client.post("/set")

    assert response.status_code == 204
    assert "sunil_session" in response.cookies
