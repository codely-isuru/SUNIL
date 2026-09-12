"""C5 §4's route-level fakes.

Source of truth: ``docs/contracts/C5-chat.md`` §4 (v1.0.0, FROZEN 2026-09-10),
which places both the ``StubTurnExecutor`` and its ``FakeConversationStore``
fixture in this module.

**Delivered here: ``FakeConversationStore``** — the lane-scoping fixture, whose
rules are pure data and therefore testable without a route.

**``StubTurnExecutor`` — delivered 2026-09-12 by the chat-lane engineer**
(backend_engineer, Stream S-spine), which is exactly who this module's previous
revision deferred it to: its six behaviours are envelope-shaped, so it could
only be written once the turn seam existed. It is written against
``sunil.core.orchestrator.result.TurnResult`` rather than the pydantic envelope,
because the route's seam returns that and ``sunil/api/envelope.py`` performs the
single mapping onto the C5 wire shape (the import law keeps ``core`` off
``sunil.api``). The observable behaviour is C5 §4's table byte-for-byte — the
same envelope a JSON client sees.

**Additive only.** No assertion, rule or seeded value in this module was changed.
Flagged for QA re-review because this is a contract-suite fixture.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Literal

from sunil.core.orchestrator.result import (
    TurnApproval,
    TurnFailure,
    TurnMessage,
    TurnResult,
    TurnTask,
    TurnTraceEntry,
    TurnUsage,
)

from tests.fakes.clock import FakeClock, to_iso

#: C5 §2.3 — the two authentication lanes. "cookie" is the owner's browser
#: session (+ X-SUNIL-Client + Origin); "bearer" is ADR-035's machine lane.
Lane = Literal["cookie", "bearer"]

#: The conversation channel recorded at creation. The bearer lane may only read
#: and extend conversations it created (C5 §2.3 blast radius).
Channel = Literal["web", "service"]

#: C5 §4 — "omitted id → create … with the lane's channel".
LANE_CHANNEL: dict[str, Channel] = {"cookie": "web", "bearer": "service"}


@dataclass(frozen=True)
class Conversation:
    id: str
    channel: Channel


class ConversationNotFound(Exception):
    """Raised for an unknown id AND for a bearer-lane request naming a
    cookie-lane conversation — the same shape for both, so the route answers 404
    either way and no existence oracle exists (C5 §2.3, §3)."""


class FakeConversationStore:
    """C5 §4 — the route-level conversation fixture.

    Seeded rows: ``conv-1 (channel="web")``, ``conv-svc-1 (channel="service")``.

    Rules:
      * unknown id → 404
      * bearer lane + ``channel="web"`` id → 404 (§2.3 scoping)
      * omitted id → create ``conv-2`` on the cookie lane / ``conv-svc-2`` on the
        bearer lane, with the lane's channel

    The owner (cookie lane) sees ALL conversations, including service-created
    ones — the system is single-owner and the asymmetry is deliberate (§2.3).
    Creation counters continue past the contract's named first ids (``conv-3``,
    ``conv-svc-3``, …) so a suite can create more than one per lane.
    """

    def __init__(self) -> None:
        self.conversations: dict[str, Conversation] = {
            "conv-1": Conversation(id="conv-1", channel="web"),
            "conv-svc-1": Conversation(id="conv-svc-1", channel="service"),
        }
        self._created: dict[str, int] = {"cookie": 1, "bearer": 1}

    def resolve(self, *, lane: Lane, conversation_id: str | None) -> Conversation:
        """Return the conversation this turn belongs to, creating one when the
        request omits the id. Raises :class:`ConversationNotFound` for anything
        the calling lane may not reach."""
        if conversation_id is None:
            return self._create(lane)

        existing = self.conversations.get(conversation_id)
        if existing is None:
            raise ConversationNotFound(conversation_id)
        if lane == "bearer" and existing.channel != "service":
            raise ConversationNotFound(conversation_id)
        return existing

    def _create(self, lane: Lane) -> Conversation:
        self._created[lane] += 1
        prefix = "conv" if lane == "cookie" else "conv-svc"
        created = Conversation(
            id=f"{prefix}-{self._created[lane]}", channel=LANE_CHANNEL[lane]
        )
        self.conversations[created.id] = created
        return created


class FakeConversationResolver:
    """The `ConversationResolver` seam over `FakeConversationStore`.

    The route resolves conversations BEFORE any turn machinery runs (a 404 is an
    authorisation answer), so the C5 suite needs the store behind that seam's
    async shape. It adds no rule of its own: every decision is the store's.

    The one translation it performs is the exception type. The seam's error
    contract is `core.conversations.gateway.ConversationNotFound` (what the real
    resolver raises and what the route maps to 404); this module's own
    `ConversationNotFound` above is the store-level class the frozen C5 fixture
    defines. Re-raising as the seam's type is what makes the route's 404 mapping
    the thing under test, rather than the fake's class identity.
    """

    def __init__(self, store: FakeConversationStore | None = None) -> None:
        self.store = store if store is not None else FakeConversationStore()

    async def resolve(
        self,
        *,
        lane: str,
        conversation_id: str | None,
        user_id: str | None = None,
        channel_label: str | None = None,
    ) -> Any:
        from sunil.core.conversations.gateway import (  # noqa: PLC0415
            ConversationNotFound as SeamConversationNotFound,
        )

        del user_id, channel_label  # the store scopes by lane alone (C5 §2.3)
        try:
            return self.store.resolve(lane=lane, conversation_id=conversation_id)
        except ConversationNotFound as exc:
            raise SeamConversationNotFound(str(exc)) from exc


#: C5 §4 — "common to every response".
STUB_USAGE = TurnUsage(input_tokens=100, output_tokens=25, cost_usd=0.000125)
STUB_TRACE = (
    TurnTraceEntry(stage="request_received", offset_ms=0, detail=None),
    TurnTraceEntry(stage="plan_created", offset_ms=10, detail=None),
    TurnTraceEntry(stage="final_response", offset_ms=20, detail=None),
)
#: C5 §4's `PARK:` row.
STUB_APPROVAL_ID = "apr-stub-1"
STUB_APPROVAL_TTL_HOURS = 72
STUB_APPROVAL_SUMMARY = "fake_tool.write_item requires approval"


class StubTurnExecutor:
    """C5 §4's deterministic turn executor, keyed on the request `message`.

    It exists so the C5 suite runs against the REAL route — auth dependencies,
    body validation, conversation resolution, the envelope builder — without the
    orchestrator, the provider or a database being involved. The six behaviours
    are the contract's table exactly; nothing here is inferred.
    """

    def __init__(self, clock: FakeClock | None = None) -> None:
        self.clock = clock if clock is not None else FakeClock()
        #: Every call, so a test can prove the route did (or did not) reach it.
        self.calls: list[dict[str, Any]] = []

    async def run(
        self,
        *,
        message: str,
        conversation: Any,
        request_id: str,
        lane: str,
        user_id: str | None,
        channel_label: str | None,
    ) -> TurnResult:
        self.calls.append(
            {
                "message": message,
                "conversation_id": conversation.id,
                "lane": lane,
                "channel_label": channel_label,
                "user_id": user_id,
            }
        )
        common = {
            "request_id": request_id,
            "conversation_id": conversation.id,
            "usage": STUB_USAGE,
            "trace": STUB_TRACE,
        }

        if message.startswith("PARK:"):
            expires = to_iso(self.clock.now() + timedelta(hours=STUB_APPROVAL_TTL_HOURS))
            return TurnResult(
                outcome="parked",
                approval=TurnApproval(
                    approval_id=STUB_APPROVAL_ID,
                    expires_at=expires,
                    summary=STUB_APPROVAL_SUMMARY,
                ),
                task=TurnTask(id="task-1", status="parked", assigned_agent="project_manager"),
                **common,
            )

        if message.startswith("FAILP:"):
            return TurnResult(
                outcome="failed", failure=TurnFailure(kind="provider_error"), **common
            )

        if message.startswith("FAILT:"):
            return TurnResult(
                outcome="failed",
                failure=TurnFailure(kind="tool_failed"),
                task=TurnTask(id="task-1", status="failed", assigned_agent="project_manager"),
                **common,
            )

        if message.startswith("REJECT:"):
            return TurnResult(
                outcome="failed", failure=TurnFailure(kind="plan_rejected"), **common
            )

        if message.startswith("NOPROJ:"):
            return TurnResult(
                outcome="failed",
                failure=TurnFailure(
                    kind="unknown_project", known_projects=(("sunil", "SUNIL"),)
                ),
                **common,
            )

        return TurnResult(
            outcome="ok",
            message=TurnMessage(
                id="msg-1", content=f"STUB: {message}", created_at=self.clock.iso()
            ),
            task=TurnTask(id="task-1", status="completed", assigned_agent="project_manager"),
            **common,
        )
