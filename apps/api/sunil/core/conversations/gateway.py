"""Conversation resolution (with C5 §2.3's lane scoping) and message
persistence.

**The blast-radius rule, in code.** A bearer-lane (ADR-035) request may create a
new conversation or name one the service lane created; naming a cookie-lane
conversation raises `ConversationNotFound` — the SAME exception as an unknown
id, so the route answers 404 either way and no existence oracle exists. A leaked
`SUNIL_SERVICE_TOKEN` can therefore start governed turns (whose writes still park
via C4) and read its own conversations only; it cannot read the owner's history
or any history-derived output. The owner sees everything, including
service-created conversations — a single-owner system, and the asymmetry is
deliberate (C5 §2.3).

`FakeConversationStore` in `tests/fakes/stub_turn_executor.py` implements the
same three rules; this module is the database half of the identical contract.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sunil.db.base import new_uuid, utc_now
from sunil.db.models import Conversation, Message

#: C5 §2.3 — the channel a conversation is created with, per calling lane.
LANE_CHANNEL = {"cookie": "web", "bearer": "service"}


class ConversationNotFound(Exception):
    """Unknown id, OR a bearer-lane request naming a cookie-lane conversation.
    One exception for both: the route maps it to 404 and the two cases are
    indistinguishable from outside."""


async def resolve_conversation(
    session: AsyncSession,
    *,
    lane: str,
    conversation_id: str | None,
    user_id: str | None,
    channel_label: str | None = None,
) -> Conversation:
    """Return the conversation this turn belongs to, creating one when the
    request omits the id."""
    if conversation_id is None:
        conversation = Conversation(
            id=new_uuid(),
            user_id=user_id,
            channel=LANE_CHANNEL[lane],
            channel_label=channel_label,
        )
        session.add(conversation)
        await session.flush()
        return conversation

    existing = await session.get(Conversation, conversation_id)
    if existing is None:
        raise ConversationNotFound(conversation_id)
    if lane == "bearer" and existing.channel != "service":
        raise ConversationNotFound(conversation_id)
    return existing


async def persist_message(
    session: AsyncSession,
    *,
    conversation_id: str,
    role: str,
    content: str,
    request_id: str,
    resumed_from_approval_id: str | None = None,
) -> Message:
    """Append a message, numbering it from the conversation's own sequence.

    `seq` is computed with `MAX(seq) + 1` inside the caller's transaction rather
    than from a global counter: message order is a per-conversation fact, and the
    index `(conversation_id, seq)` is what the context loader reads.
    """
    next_seq = (
        await session.execute(
            select(func.coalesce(func.max(Message.seq), 0) + 1).where(
                Message.conversation_id == conversation_id
            )
        )
    ).scalar_one()

    message = Message(
        id=new_uuid(),
        conversation_id=conversation_id,
        seq=next_seq,
        role=role,
        content=content,
        request_id=request_id,
        resumed_from_approval_id=resumed_from_approval_id,
    )
    session.add(message)
    await session.flush()
    return message


async def read_recent_messages(
    session: AsyncSession, *, conversation_id: str, limit: int = 20
) -> list[Message]:
    """Short-term context: the last `limit` messages, oldest-first.

    Ordered by `seq` and not by timestamp — two messages written in the same
    millisecond have an unambiguous order only in `seq`.
    """
    rows = list(
        (
            await session.execute(
                select(Message)
                .where(Message.conversation_id == conversation_id)
                .order_by(Message.seq.desc())
                .limit(limit)
            )
        ).scalars()
    )
    return list(reversed(rows))


async def touch_conversation(session: AsyncSession, *, conversation_id: str) -> None:
    conversation = await session.get(Conversation, conversation_id)
    if conversation is not None:
        conversation.updated_at = utc_now()
