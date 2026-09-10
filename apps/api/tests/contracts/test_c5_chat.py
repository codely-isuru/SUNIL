"""C5 — Chat turn trigger contract suite.

Source of truth: ``docs/contracts/C5-chat.md`` v1.0.0 (FROZEN 2026-09-10) and
``docs/contracts/C5-chat-openapi.yaml``.

C5's nine numbered tests all run "against the REAL route (auth deps + validation
+ envelope builder) with the stub behind it" (C5 §4). That route
(``sunil/api/routes/chat.py``), its dependencies (``api/deps.py``:
``require_owner_session``, ``require_client_header``, ``require_service_token``)
and the envelope models (``api/schemas.py``) are Phase 2 production code owned by
the engineer building the chat lane — none of them exist yet. Those nine tests
are therefore explicit, individually-numbered ``pytest.skip`` stubs: the debt is
visible in the suite and in ``docs/tasks/P0-fakes.md``, and no assertion pretends
to have run.

What IS executable now: ``FakeConversationStore``'s lane-scoping rules (C5 §4's
route-level fixture), which are pure data, and the schema-level probes in
``test_openapi_contracts.py``.
"""

from __future__ import annotations

import pytest

from tests.fakes.fake_provider import partition
from tests.fakes.stub_turn_executor import (
    Conversation,
    ConversationNotFound,
    FakeConversationStore,
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
@pytest.mark.skip(reason=f"C5 contract test 1 (JSON lane, exactly-one rule) — {ROUTE_PENDING}")
def test_c5_1_json_lane_six_prefixes_and_the_exactly_one_rule() -> None:
    """C5 contract test 1 — each of the six message prefixes (``PARK:``,
    ``FAILP:``, ``FAILT:``, ``REJECT:``, ``NOPROJ:``, anything else) → exact
    envelope shape; the exactly-one rule holds in all six (the other two of
    message/failure/approval are null); ``known_projects`` is non-null exactly in
    the ``NOPROJ:`` case."""


@pytest.mark.skip(reason=f"C5 contract test 2 (NDJSON lane, byte-for-byte tokens) — {ROUTE_PENDING}")
def test_c5_2_ndjson_frames_and_token_concatenation() -> None:
    """C5 contract test 2 — frames parse line-by-line; token concatenation equals
    ``done.envelope.message.content`` byte-for-byte on a message containing a
    double space and a newline (the C2 §5 partition property); exactly one
    ``done``, and it is last."""


@pytest.mark.skip(reason=f"C5 contract test 3 (422 wall) — {ROUTE_PENDING}")
def test_c5_3_validation_errors() -> None:
    """C5 contract test 3 — ``message`` of length 0 and 8001 → 422; unknown body
    key → 422; ``input_modality:"voice"`` → 422 (ADR-020: always 422 until the
    voice milestone lands on V2)."""


@pytest.mark.skip(reason=f"C5 contract test 4 (cookie lane CSRF pair) — {ROUTE_PENDING}")
def test_c5_4_cookie_lane_requires_client_header_then_session() -> None:
    """C5 contract test 4 — cookie lane without ``X-SUNIL-Client`` → 403; with the
    header but no session → 401 (ADR-008 control ordering)."""


@pytest.mark.skip(reason=f"C5 contract test 5 (bearer lane scope probe) — {ROUTE_PENDING}")
def test_c5_5_bearer_token_reaches_chat_only() -> None:
    """C5 contract test 5 — valid ``SUNIL_SERVICE_TOKEN`` + no cookie → 200; the
    same token on ``GET /api/v1/approvals`` → 401 (structural scope probe,
    ADR-035). The schema-level companion is
    ``test_openapi_contracts.py::test_bearer_scheme_exists_only_on_the_chat_contract``."""


@pytest.mark.skip(reason=f"C5 contract test 6 (unknown conversation) — {ROUTE_PENDING}")
def test_c5_6_unknown_conversation_id_is_404() -> None:
    """C5 contract test 6 — unknown ``conversation_id`` → 404. The store-level
    rule is asserted above in
    ``test_c5_store_unknown_id_is_not_found_on_every_lane``."""


@pytest.mark.skip(reason=f"C5 contract test 7 (credential log redaction) — {ROUTE_PENDING}")
def test_c5_7_credentials_never_reach_logs_or_traces() -> None:
    """C5 contract test 7 (Security review 2026-09-10 item 5) — with a log/trace
    capture attached, one request per lane with a VALID credential and one with an
    INVALID credential; the captured output contains neither the bearer value nor
    the cookie value (literal substring probe against everything captured,
    including the 401 bodies). Needs the route AND its logging call sites: the
    load-bearing rule is structural (header values are not inputs to any logging
    call), so it can only be proven against the real handler."""


@pytest.mark.skip(reason=f"C5 contract test 8 (route-table scope, build-time) — {ROUTE_PENDING}")
def test_c5_8_service_token_dependency_is_registered_on_exactly_one_route() -> None:
    """C5 contract test 8 (Security review 2026-09-10 item 6, build-time) —
    iterate ``app.routes`` and assert the bearer dependency
    (``require_service_token``, by FUNCTION IDENTITY, not name string) is
    registered on exactly one route: ``POST /api/v1/chat``. A dependency slipped
    onto a router would fail this without any request being made. Needs
    ``sunil/main.py``'s ``create_app`` and ``api/deps.py``."""


@pytest.mark.skip(reason=f"C5 contract test 9 (service-lane blast radius) — {ROUTE_PENDING}")
def test_c5_9_bearer_lane_conversation_scoping_through_the_route() -> None:
    """C5 contract test 9 — bearer lane naming ``conv-1`` (a ``channel="web"``
    conversation) → 404; naming ``conv-svc-1`` → 200; omitting
    ``conversation_id`` → 200 with a NEW service-channel conversation (§2.3
    blast-radius rule). The store half of every clause is asserted above."""
