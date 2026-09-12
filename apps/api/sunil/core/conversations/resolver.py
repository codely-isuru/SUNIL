"""The database conversation resolver the chat route calls before any turn
machinery runs.

Resolution is an authorisation answer (C5 §2.3's blast radius), so it happens in
the route and in its own transaction: an unknown id and an out-of-lane id both
raise `ConversationNotFound`, the route answers 404 to both, and no existence
oracle exists for a leaked service token.

`tests/fakes/stub_turn_executor.py`'s `FakeConversationStore` implements the same
three rules against an in-memory dict; this is the database half of the identical
contract.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sunil.core.conversations.gateway import resolve_conversation


@dataclass(frozen=True)
class ResolvedConversation:
    """What the route needs from resolution: the id it echoes in the envelope and
    the channel the conversation was created with (C5 §2.3).

    Defined HERE and imported by `api/wiring.py`, not the other way round: the
    import law is `core/` never imports `sunil.api` (ARCHITECTURE_V2 §2), and it
    is enforced by `tests/unit/test_import_law.py`.
    """

    id: str
    channel: str


class DbConversationResolver:
    """`ConversationResolver` over the `conversations` table."""

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def resolve(
        self,
        *,
        lane: str,
        conversation_id: str | None,
        user_id: str | None,
        channel_label: str | None = None,
    ) -> ResolvedConversation:
        async with self._sessionmaker() as session:
            conversation = await resolve_conversation(
                session,
                lane=lane,
                conversation_id=conversation_id,
                user_id=user_id,
                channel_label=channel_label,
            )
            resolved = ResolvedConversation(
                id=conversation.id, channel=conversation.channel
            )
            await session.commit()
        return resolved


__all__ = ["DbConversationResolver", "ResolvedConversation"]
