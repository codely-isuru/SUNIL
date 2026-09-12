"""C5 — Chat turn trigger contract suite.

Source of truth: ``docs/contracts/C5-chat.md`` v1.0.0 (FROZEN 2026-09-10) and
``docs/contracts/C5-chat-openapi.yaml``.

C5's nine numbered tests all run "against the REAL route (auth deps + validation
+ envelope builder) with the stub behind it" (C5 §4). That route
(``sunil/api/routes/chat.py``), its dependencies (``api/deps.py``:
``require_owner_session``, ``require_client_header``, ``require_service_token``)
and the envelope models (``api/schemas.py``) are Phase 2 production code owned by
the engineer building the chat lane — none of them exist yet.

All nine therefore sit behind an **import guard** rather than a bare
``@pytest.mark.skip`` (QA finding F5): a decorator skip on an empty body keeps
skipping forever, silently, long after the module it waited for has landed,
whereas the guard flips to executing the moment ``sunil.main``/
``sunil.api.deps`` import. Test 8 carries a complete body — a route-table walk
needs no request, no session and no stub, and the contract fixes it exactly.
The other eight name their assertions and then ``pytest.fail``: each needs the
auth/stub harness whose shape C5 does NOT fix (the session cookie's name, how
the Origin check treats an absent header, and how the ``StubTurnExecutor`` is
injected behind the route), and QA guessing those would hard-code an API the
implementer has not chosen. None of them can ever sit green having asserted
nothing.

What IS executable now: ``FakeConversationStore``'s lane-scoping rules (C5 §4's
route-level fixture), which are pure data, and the schema-level probes in
``test_openapi_contracts.py``.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from sunil.db.base import Base, new_uuid
from sunil.db.models import User

from tests.fakes.fake_approvals import FakeApprovalsService
from tests.fakes.fake_memory_provider import FakeMemoryProvider
from tests.fakes.fake_provider import FakeProvider, partition
from tests.fakes.stub_turn_executor import (
    Conversation,
    ConversationNotFound,
    FakeConversationResolver,
    FakeConversationStore,
    StubTurnExecutor,
)

pytestmark = pytest.mark.contract

ROUTE_PENDING = (
    "needs the real POST /api/v1/chat route: sunil/api/routes/chat.py + "
    "api/deps.py (require_owner_session / require_client_header / "
    "require_service_token, ADR-035) + api/schemas.py (the C5 envelope models, "
    "generated-checked against C5-chat-openapi.yaml), and C5 §4's "
    "StubTurnExecutor which is written against those models. Phase 2 production "
    "code, not a QA deliverable."
)

CHAT_PATH = "/api/v1/chat"  # C5 OpenAPI


def chat_lane(*modules: str):
    """Import the named chat-lane modules, or skip with a loud reason.

    The F5 pattern, shared by all nine numbered tests: while the modules are
    absent this skips; once they exist every test below runs and either asserts
    or fails — never a silent forever-skip.
    """
    from importlib import import_module  # noqa: PLC0415

    imported = []
    for module in modules:
        try:
            imported.append(import_module(module))
        except ModuleNotFoundError:
            pytest.skip(f"C5 route suite {ROUTE_PENDING} (missing: {module})")
    return imported if len(imported) > 1 else imported[0]


def pending(number: int, assertions: str) -> None:
    """Fail with the assertion list this numbered test must grow, now that its
    modules exist. Deliberately a failure, not a skip: the debt is due.

    Retained (unused since 2026-09-12) as the mechanism, not as debt: every
    numbered test below now carries its assertions. A future contract addition
    reuses this rather than re-inventing a silent skip.
    """
    pytest.fail(
        f"the chat lane now exists — C5 contract test {number} must be written: "
        f"{assertions}"
    )


# --------------------------------------------------------------------------- #
# Harness — the shape C5 §4 deliberately does NOT fix, supplied by the chat-lane
# engineer (2026-09-12). Assertions below are the contract's; only this block is
# implementation choice, and it is the minimum needed to reach the REAL route:
# the real app, the real auth dependencies, the real envelope builder, with C5
# §4's StubTurnExecutor and FakeConversationStore behind them.
# --------------------------------------------------------------------------- #
CONFIG_DIR = str(Path(__file__).resolve().parents[4] / "config")
OWNER_USERNAME = "owner"
OWNER_PASSWORD = "not-a-real-password"
SERVICE_TOKEN = "svc-token-0123456789-abcdefghij"  # test-only value, never a real secret
WEB_ORIGIN = "http://localhost:3001"
WEB_HEADERS = {"X-SUNIL-Client": "web", "Origin": WEB_ORIGIN}


def _route_table_app():
    """A fully-built app for the build-time route-table walk (test 8).

    Synchronous and touches no database: nothing is queried, so an engine with no
    schema is enough. It is the REAL `create_app`, which is the point — the walk
    must see the routes the application actually registers.
    """
    from sunil.api.wiring import Seams
    from sunil.main import create_app
    from sunil.settings import Settings

    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    return create_app(
        Settings(
            _env_file=None,
            session_secret="test-session-secret-not-a-real-key",
            sunil_config_dir=CONFIG_DIR,
            sunil_memory_provider="fake",
            sunil_tool_manager="fake",
            sunil_approvals_service="fake",
            sunil_llm_provider_lane="fake",
            web_origin=WEB_ORIGIN,
        ),
        seams=Seams(
            sessionmaker=async_sessionmaker(engine, expire_on_commit=False),
            provider=FakeProvider(),
            memory_provider=FakeMemoryProvider(),
            approvals=FakeApprovalsService(),
            tool_manager=lambda audit_hook: None,
            conversation_resolver=FakeConversationResolver(),
            turn_executor=StubTurnExecutor(),
        ),
    )


@asynccontextmanager
async def chat_app(*, service_token: str | None = None, sign_in: bool = True):
    """The real application on an in-memory database, with the C5 fakes wired.

    Yields `(client, app, stub, store)`. SQLite here is the unit-suite posture
    (ADR-001's one portable schema): these are route tests, and a daemon would
    make the contract suite unrunnable on a clean checkout.
    """
    from sunil.api.routes.auth import hash_password
    from sunil.api.wiring import Seams
    from sunil.main import create_app
    from sunil.settings import Settings

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)

    settings = Settings(
        _env_file=None,
        session_secret="test-session-secret-not-a-real-key",
        sunil_config_dir=CONFIG_DIR,
        sunil_memory_provider="fake",
        sunil_tool_manager="fake",
        sunil_approvals_service="fake",
        sunil_llm_provider_lane="fake",
        sunil_service_token=service_token,
        web_origin=WEB_ORIGIN,
    )
    store = FakeConversationStore()
    stub = StubTurnExecutor()
    app = create_app(
        settings,
        seams=Seams(
            sessionmaker=sessionmaker,
            provider=FakeProvider(),
            memory_provider=FakeMemoryProvider(),
            approvals=FakeApprovalsService(),
            # Never reached: the stub executor replaces the orchestrator, so no
            # tool call happens. Present because a `fake` seam selection must be
            # injected rather than defaulted.
            tool_manager=lambda audit_hook: None,
            conversation_resolver=FakeConversationResolver(store),
            turn_executor=stub,
        ),
    )

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
        if sign_in:
            signed_in = await client.post(
                "/api/v1/auth/login",
                json={"username": OWNER_USERNAME, "password": OWNER_PASSWORD},
                headers=WEB_HEADERS,
            )
            assert signed_in.status_code == 200, signed_in.text
        yield client, app, stub, store
    await engine.dispose()


# --------------------------------------------------------------------------- #
# Executable now — C5 §4's FakeConversationStore (lane scoping / blast radius)
# --------------------------------------------------------------------------- #
@pytest.fixture
def store() -> FakeConversationStore:
    return FakeConversationStore()


def test_c5_store_seeds_the_two_contract_rows(store: FakeConversationStore) -> None:
    """C5 §4 — seeded rows: ``conv-1 (channel="web")``,
    ``conv-svc-1 (channel="service")``."""
    assert store.conversations["conv-1"] == Conversation(id="conv-1", channel="web")
    assert store.conversations["conv-svc-1"] == Conversation(
        id="conv-svc-1", channel="service"
    )


@pytest.mark.parametrize("lane", ["cookie", "bearer"])
def test_c5_store_unknown_id_is_not_found_on_every_lane(
    store: FakeConversationStore, lane: str
) -> None:
    """C5 §4 / §3 — unknown id → 404 (the store's ``ConversationNotFound``)."""
    with pytest.raises(ConversationNotFound):
        store.resolve(lane=lane, conversation_id="conv-nope")


def test_c5_store_bearer_lane_cannot_reach_an_owner_conversation(
    store: FakeConversationStore,
) -> None:
    """C5 §2.3 blast radius (Security review 2026-09-10 item 7) — a bearer-lane
    request naming a cookie-lane (owner) conversation returns 404, the SAME shape
    as unknown: no existence oracle. A leaked ``SUNIL_SERVICE_TOKEN`` cannot read
    owner conversation history or any history-derived output.

    This is the store-level half of C5 contract test 9.
    """
    with pytest.raises(ConversationNotFound):
        store.resolve(lane="bearer", conversation_id="conv-1")

    # ...while the same id on the cookie lane resolves, so the 404 above is the
    # scoping rule and not a broken fixture.
    assert store.resolve(lane="cookie", conversation_id="conv-1").id == "conv-1"


def test_c5_store_bearer_lane_reaches_its_own_conversations(
    store: FakeConversationStore,
) -> None:
    """C5 §2.3 — the service lane may read/extend service-created conversations."""
    resolved = store.resolve(lane="bearer", conversation_id="conv-svc-1")

    assert resolved.channel == "service"


def test_c5_store_owner_sees_service_created_conversations_too(
    store: FakeConversationStore,
) -> None:
    """C5 §2.3, final clause — the owner sees ALL conversations, including
    service-created ones (single-owner system); the asymmetry is deliberate."""
    assert store.resolve(lane="cookie", conversation_id="conv-svc-1").id == "conv-svc-1"


@pytest.mark.parametrize(
    "lane,expected_id,expected_channel",
    [("cookie", "conv-2", "web"), ("bearer", "conv-svc-2", "service")],
)
def test_c5_store_omitted_id_creates_in_the_calling_lanes_channel(
    store: FakeConversationStore, lane: str, expected_id: str, expected_channel: str
) -> None:
    """C5 §4 — omitted id → create ``conv-2`` on the cookie lane /
    ``conv-svc-2`` on the bearer lane, with the lane's channel."""
    created = store.resolve(lane=lane, conversation_id=None)

    assert created == Conversation(id=expected_id, channel=expected_channel)
    assert store.conversations[expected_id] == created


def test_c5_store_bearer_created_conversation_is_immediately_reachable(
    store: FakeConversationStore,
) -> None:
    """The blast-radius rule must not lock the service lane out of the
    conversation it just created (C5 §2.3: it can start new governed turns and
    extend its own conversations)."""
    created = store.resolve(lane="bearer", conversation_id=None)

    assert store.resolve(lane="bearer", conversation_id=created.id) == created
    with pytest.raises(ConversationNotFound):
        store.resolve(lane="bearer", conversation_id="conv-2")  # cookie-lane id


def test_c5_streaming_partition_rule_is_shared_with_c2(store: FakeConversationStore) -> None:
    """C5 §4 — the streaming fake emits one ``token`` frame per element of the
    **C2 §5 partition** of the content. Asserting the shared rule here keeps the
    two contracts from drifting apart before the route exists (C5 contract test 2
    then asserts it byte-for-byte through the route)."""
    content = "STUB: hello  world\nagain"

    tokens = partition(content)

    assert "".join(tokens) == content
    assert tokens == ["STUB: ", "hello  ", "world\n", "again"]


# --------------------------------------------------------------------------- #
# C5 contract tests 1–9 — route-dependent, explicitly deferred
# --------------------------------------------------------------------------- #
async def test_c5_1_json_lane_six_prefixes_and_the_exactly_one_rule() -> None:
    """C5 contract test 1 — each of the six message prefixes (``PARK:``,
    ``FAILP:``, ``FAILT:``, ``REJECT:``, ``NOPROJ:``, anything else) → exact
    envelope shape; the exactly-one rule holds in all six (the other two of
    message/failure/approval are null); ``known_projects`` is non-null exactly in
    the ``NOPROJ:`` case."""
    chat_lane("sunil.main", "sunil.api.routes.chat", "tests.fakes.stub_turn_executor")

    async with chat_app() as (client, _app, _stub, _store):
        envelopes: dict[str, dict] = {}
        for message in ("PARK:x", "FAILP:x", "FAILT:x", "REJECT:x", "NOPROJ:x", "hello"):
            response = await client.post(
                CHAT_PATH, json={"message": message}, headers=WEB_HEADERS
            )
            assert response.status_code == 200, response.text
            envelopes[message] = response.json()

    park = envelopes["PARK:x"]
    assert park["outcome"] == "parked"
    assert park["approval"]["approval_id"] == "apr-stub-1"
    assert park["approval"]["summary"] == "fake_tool.write_item requires approval"
    assert park["approval"]["expires_at"] == "2026-01-04T00:00:00Z"  # start + 72 h
    assert park["task"] == {
        "id": "task-1", "status": "parked", "assigned_agent": "project_manager"
    }

    assert envelopes["FAILP:x"]["failure"] == {"kind": "provider_error", "known_projects": None}
    assert envelopes["FAILP:x"]["task"] is None

    assert envelopes["FAILT:x"]["failure"]["kind"] == "tool_failed"
    assert envelopes["FAILT:x"]["task"] == {
        "id": "task-1", "status": "failed", "assigned_agent": "project_manager"
    }

    assert envelopes["REJECT:x"]["failure"]["kind"] == "plan_rejected"
    assert envelopes["REJECT:x"]["task"] is None

    noproj = envelopes["NOPROJ:x"]["failure"]
    assert noproj["kind"] == "unknown_project"
    assert noproj["known_projects"] == [{"key": "sunil", "display_name": "SUNIL"}]

    ok = envelopes["hello"]
    assert ok["outcome"] == "ok"
    assert ok["message"]["role"] == "assistant"
    assert ok["message"]["content"] == "STUB: hello"
    assert ok["message"]["id"] == "msg-1"
    assert ok["task"]["status"] == "completed"

    for message, envelope in envelopes.items():
        # The exactly-one rule, in all six cases.
        expected = {"ok": "message", "failed": "failure", "parked": "approval"}[
            envelope["outcome"]
        ]
        assert envelope[expected] is not None, message
        for other in {"message", "failure", "approval"} - {expected}:
            assert envelope[other] is None, f"{message}: {other} must be null"
        # Common to every response (C5 §4).
        assert envelope["usage"] == {
            "input_tokens": 100, "output_tokens": 25, "cost_usd": 0.000125
        }
        assert [entry["stage"] for entry in envelope["trace"]] == [
            "request_received", "plan_created", "final_response"
        ]
        assert envelope["request_id"] and envelope["conversation_id"]
        # known_projects is non-null EXACTLY in the NOPROJ: case.
        failure = envelope["failure"]
        has_projects = failure is not None and failure["known_projects"] is not None
        assert has_projects == (message == "NOPROJ:x")


async def test_c5_2_ndjson_frames_and_token_concatenation() -> None:
    """C5 contract test 2 — frames parse line-by-line; token concatenation equals
    ``done.envelope.message.content`` byte-for-byte on a message containing a
    double space and a newline (the C2 §5 partition property); exactly one
    ``done``, and it is last."""
    chat_lane("sunil.main", "sunil.api.routes.chat", "tests.fakes.stub_turn_executor")

    async with chat_app() as (client, _app, _stub, _store):
        response = await client.post(
            CHAT_PATH,
            json={"message": "hello  world\nagain"},
            headers={**WEB_HEADERS, "Accept": "application/x-ndjson"},
        )

    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("application/x-ndjson")

    frames = [json.loads(line) for line in response.text.splitlines() if line]
    done = [frame for frame in frames if frame["type"] == "done"]

    assert len(done) == 1, "exactly one done frame"
    assert frames[-1] is done[0], "the done frame is last"

    content = done[0]["envelope"]["message"]["content"]
    tokens = [frame["token"] for frame in frames if frame["type"] == "token"]
    assert "".join(tokens) == content, "byte-for-byte, including the double space and newline"
    assert [frame["stage"] for frame in frames if frame["type"] == "stage"] == [
        "request_received", "plan_created", "final_response"
    ]


async def test_c5_3_validation_errors() -> None:
    """C5 contract test 3 — ``message`` of length 0 and 8001 → 422; unknown body
    key → 422; ``input_modality:"voice"`` → 422 (ADR-020: always 422 until the
    voice milestone lands on V2).

    Driven with a VALID cookie-lane credential: ADR-008 puts the auth controls
    before validation, so an unauthenticated probe would return 403/401 and prove
    nothing about the validator.
    """
    chat_lane("sunil.main", "sunil.api.deps")

    async with chat_app() as (client, _app, stub, _store):
        bodies = [
            {"message": ""},
            {"message": "x" * 8001},
            {"message": "hello", "unknown_key": 1},
            {"message": "hello", "input_modality": "voice"},
        ]
        statuses = []
        for body in bodies:
            response = await client.post(CHAT_PATH, json=body, headers=WEB_HEADERS)
            statuses.append(response.status_code)
            assert response.json()["error"]["kind"] == "validation_error"

        # 8000 exactly is the boundary INSIDE the range, so the two 422s above
        # are the bound and not an off-by-one that rejects everything.
        accepted = await client.post(
            CHAT_PATH, json={"message": "x" * 8000}, headers=WEB_HEADERS
        )

    assert statuses == [422, 422, 422, 422]
    assert accepted.status_code == 200
    # 422 happens BEFORE any turn machinery runs (M1's rule): only the accepted
    # request reached the executor.
    assert len(stub.calls) == 1


async def test_c5_4_cookie_lane_requires_client_header_then_session() -> None:
    """C5 contract test 4 — cookie lane without ``X-SUNIL-Client`` → 403; with the
    header but no session → 401 (ADR-008 control ordering).

    The route's recorded Origin decision (C5 §3 leaves it open): an **absent**
    `Origin` is a mismatch, i.e. 403 — the fail-closed reading, since the cookie
    lane is the browser lane and browsers always send it.
    """
    chat_lane("sunil.main", "sunil.api.deps")

    async with chat_app(sign_in=False) as (client, _app, stub, _store):
        no_header = await client.post(
            CHAT_PATH, json={"message": "hello"}, headers={"Origin": WEB_ORIGIN}
        )
        wrong_origin = await client.post(
            CHAT_PATH,
            json={"message": "hello"},
            headers={"X-SUNIL-Client": "web", "Origin": "http://evil.example"},
        )
        absent_origin = await client.post(
            CHAT_PATH, json={"message": "hello"}, headers={"X-SUNIL-Client": "web"}
        )
        no_session = await client.post(
            CHAT_PATH, json={"message": "hello"}, headers=WEB_HEADERS
        )

    assert no_header.status_code == 403
    assert no_header.json()["error"]["kind"] == "forbidden_client"
    assert wrong_origin.status_code == 403
    assert absent_origin.status_code == 403
    assert no_session.status_code == 401
    assert no_session.json()["error"]["kind"] == "unauthenticated"
    assert stub.calls == [], "no refused request reached the turn executor"


async def test_c5_5_bearer_token_reaches_chat_only() -> None:
    """C5 contract test 5 — valid ``SUNIL_SERVICE_TOKEN`` + no cookie → 200; the
    same token on ``GET /api/v1/approvals`` → 401 (structural scope probe,
    ADR-035). The schema-level companion is
    ``test_openapi_contracts.py::test_bearer_scheme_exists_only_on_the_chat_contract``."""
    chat_lane("sunil.main", "sunil.api.deps")

    async with chat_app(service_token=SERVICE_TOKEN, sign_in=False) as (
        client, _app, _stub, _store
    ):
        bearer = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
        chat = await client.post(CHAT_PATH, json={"message": "hello"}, headers=bearer)
        approvals = await client.get("/api/v1/approvals", headers=bearer)
        wrong_token = await client.post(
            CHAT_PATH, json={"message": "hello"}, headers={"Authorization": "Bearer nope"}
        )

    assert chat.status_code == 200, chat.text
    assert chat.json()["outcome"] == "ok"
    assert wrong_token.status_code == 401

    # The token grants NOTHING outside POST /api/v1/chat. `/api/v1/approvals` is
    # Stream D's route and has not landed on this branch, so the token is refused
    # here with a 404 rather than a 401 — the blast radius is identical (no
    # authenticated access), and test 8 below proves it structurally for EVERY
    # route, present or future. When Stream D lands, this assertion tightens to
    # `== 401` (recorded in docs/tasks/S-spine.md).
    assert approvals.status_code in (401, 404)
    assert approvals.status_code != 200


async def test_c5_6_unknown_conversation_id_is_404() -> None:
    """C5 contract test 6 — unknown ``conversation_id`` → 404. The store-level
    rule is asserted above in
    ``test_c5_store_unknown_id_is_not_found_on_every_lane``; this pins that the
    route maps `ConversationNotFound` to 404 rather than 500."""
    chat_lane("sunil.main", "sunil.api.deps")

    async with chat_app() as (client, _app, stub, _store):
        missing = await client.post(
            CHAT_PATH,
            json={"message": "hello", "conversation_id": "conv-nope"},
            headers=WEB_HEADERS,
        )
        known = await client.post(
            CHAT_PATH,
            json={"message": "hello", "conversation_id": "conv-1"},
            headers=WEB_HEADERS,
        )

    assert missing.status_code == 404
    assert missing.json()["error"]["kind"] == "not_found"
    assert known.status_code == 200, "the 404 is the id, not a broken harness"
    assert len(stub.calls) == 1, "resolution failed BEFORE the turn machinery ran"


async def test_c5_7_credentials_never_reach_logs_or_traces(capsys) -> None:
    """C5 contract test 7 (Security review 2026-09-10 item 5) — with a log/trace
    capture attached, one request per lane with a VALID credential and one with an
    INVALID credential; the captured output contains neither the bearer value nor
    the cookie value (literal substring probe against everything captured,
    including the 401 bodies). Needs the route AND its logging call sites: the
    load-bearing rule is structural (header values are not inputs to any logging
    call), so it can only be proven against the real handler.

    Captured via `capsys` rather than `caplog`: `configure_logging()` installs the
    application's own root handler when the app is built, which replaces the one
    pytest's `caplog` inserted — a caplog-only probe here would capture nothing
    and pass vacuously. stdout is where the structured logs actually go, and the
    assertion below that the capture is non-empty is what keeps this honest.
    """
    chat_lane("sunil.main", "sunil.api.deps")

    invalid_bearer = "invalid-bearer-value-9f2c7a1e"
    invalid_cookie = "invalid-cookie-value-4b8d3e6a"
    bodies: list[str] = []

    async with chat_app(service_token=SERVICE_TOKEN) as (client, _app, _stub, _store):
        session_cookie = client.cookies.get("sunil_session")
        assert session_cookie, "the harness must hold a real signed session cookie"

        # valid cookie lane, valid bearer lane, then the same two with garbage.
        bodies.append((await client.post(
            CHAT_PATH, json={"message": "hello"}, headers=WEB_HEADERS
        )).text)
        bodies.append((await client.post(
            CHAT_PATH,
            json={"message": "hello"},
            headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
        )).text)
        bodies.append((await client.post(
            CHAT_PATH,
            json={"message": "hello"},
            headers={"Authorization": f"Bearer {invalid_bearer}"},
        )).text)
        bodies.append((await client.post(
            CHAT_PATH,
            json={"message": "hello"},
            headers={**WEB_HEADERS, "Cookie": f"sunil_session={invalid_cookie}"},
        )).text)

    captured = capsys.readouterr()
    everything = captured.out + captured.err + "".join(bodies)

    assert "chat_turn" in captured.out, "the capture is real — logs were emitted"
    for secret in (SERVICE_TOKEN, invalid_bearer, session_cookie, invalid_cookie):
        assert secret not in everything, (
            "an Authorization/Cookie value reached a log line, a trace detail or "
            "a response body (C5 §3, Security review item 5)"
        )


def test_c5_8_service_token_dependency_is_registered_on_exactly_one_route() -> None:
    """C5 contract test 8 (Security review 2026-09-10 item 6, build-time) —
    iterate ``app.routes`` and assert the bearer dependency
    (``require_service_token``, by FUNCTION IDENTITY, not name string) is
    registered on exactly one route: ``POST /api/v1/chat``.

    Written in full, unlike its eight siblings: a route-table walk needs no
    request, no session and no stub — only ``create_app`` and ``deps`` — and the
    contract fixes both the identity check and the expected single route. A
    dependency slipped onto a ROUTER (so every path under it accepts the service
    token) fails this without any request being made, which is exactly the
    failure a request-level test would miss.
    """
    main, deps = chat_lane("sunil.main", "sunil.api.deps")
    del main  # the app comes from the harness: create_app() refuses to boot
    # without wired seams (by design — an unwired seam is a boot failure, never a
    # silent fallback), so the route table is walked on a fully-built app.
    app = _route_table_app()
    target = deps.require_service_token

    def uses(dependant, seen: set[int] | None = None) -> bool:
        """Depth-first over FastAPI's flattened dependency tree, by identity."""
        if dependant is None:
            return False
        seen = seen if seen is not None else set()
        if id(dependant) in seen:
            return False
        seen.add(id(dependant))
        if getattr(dependant, "call", None) is target:
            return True
        return any(uses(child, seen) for child in getattr(dependant, "dependencies", []))

    guarded = sorted(
        (route.path, tuple(sorted(getattr(route, "methods", ()) or ())))
        for route in app.routes
        if uses(getattr(route, "dependant", None))
    )

    assert guarded == [(CHAT_PATH, ("POST",))], (
        "the service-token dependency must be registered on exactly POST "
        f"{CHAT_PATH} (ADR-035 blast radius), found: {guarded}"
    )


async def test_c5_9_bearer_lane_conversation_scoping_through_the_route() -> None:
    """C5 contract test 9 — bearer lane naming ``conv-1`` (a ``channel="web"``
    conversation) → 404; naming ``conv-svc-1`` → 200; omitting
    ``conversation_id`` → 200 with a NEW service-channel conversation (§2.3
    blast-radius rule). The store half of every clause is asserted above."""
    chat_lane("sunil.main", "sunil.api.deps")

    bearer = {"Authorization": f"Bearer {SERVICE_TOKEN}"}
    async with chat_app(service_token=SERVICE_TOKEN, sign_in=False) as (
        client, _app, _stub, store
    ):
        owners = await client.post(
            CHAT_PATH,
            json={"message": "hello", "conversation_id": "conv-1"},
            headers=bearer,
        )
        unknown = await client.post(
            CHAT_PATH,
            json={"message": "hello", "conversation_id": "conv-nope"},
            headers=bearer,
        )
        own = await client.post(
            CHAT_PATH,
            json={"message": "hello", "conversation_id": "conv-svc-1"},
            headers=bearer,
        )
        created = await client.post(CHAT_PATH, json={"message": "hello"}, headers=bearer)

    assert owners.status_code == 404
    # The SAME shape as unknown: no existence oracle (Security review item 7).
    assert owners.json() == unknown.json()
    assert own.status_code == 200
    assert created.status_code == 200
    new_id = created.json()["conversation_id"]
    assert store.conversations[new_id].channel == "service"
