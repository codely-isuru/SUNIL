"""C5 §4's route-level fakes.

Source of truth: ``docs/contracts/C5-chat.md`` §4 (v1.0.0, FROZEN 2026-09-10),
which places both the ``StubTurnExecutor`` and its ``FakeConversationStore``
fixture in this module.

**Delivered here: ``FakeConversationStore``** — the lane-scoping fixture, whose
rules are pure data and therefore testable without a route.

**Deferred: ``StubTurnExecutor``.** Its six behaviours are envelope-shaped
(``outcome``/``message``/``task``/``failure``/``approval``/``trace``/``usage``),
so it can only be written against the C5 envelope models, which live in
``sunil/api/schemas.py`` — "generated-checked against C5 OpenAPI"
(ARCHITECTURE_V2 §2) and owned by the engineer building the chat route. Writing
those models here would fork the source of truth for the envelope. Recorded as
debt in ``docs/tasks/P0-fakes.md``; the skipped C5 tests in
``tests/contracts/test_c5_chat.py`` name it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

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
