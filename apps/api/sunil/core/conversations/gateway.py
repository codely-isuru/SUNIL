"""`conversations` + `messages` writers (FR-021, FR-140).

Stage 1 (`message_received`) persists the owner's message; stage 12
(`final_response`) persists the assistant's, on success only (a failed
turn has no agent summary to persist — `ARCHITECTURE_V1.md` §3.4). Both
go through `persist_message()`, so capture-policy resolution (ADR-014)
and redaction (ADR-006) happen in exactly one place regardless of which
role is being written.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from sunil.capture import CaptureKind, ContentSource
from sunil.db.capture import apply_capture_to_content, resolve_capture
from sunil.db.models import Conversation, Message
from sunil.redaction import scrub

_ROLE_TO_SOURCE = {
    "user": ContentSource.OWNER,
    "assistant": ContentSource.AGENT,
    "system": ContentSource.SYSTEM,
}


class UnknownConversationError(Exception):
    """Raised when a caller supplies a `conversation_id` that does not
    exist. M1 is single-user (ADR-000 Q3), so this is always a stale or
    malformed client-supplied id, never a cross-user access question."""

    def __init__(self, conversation_id: str) -> None:
        self.conversation_id = conversation_id
        super().__init__(f"no conversation with id {conversation_id!r}")


async def get_or_create_conversation(
    session: AsyncSession,
    *,
    user_id: str,
    conversation_id: str | None,
) -> Conversation:
    """Load `conversation_id` if given, or start a new conversation for
    `user_id`. Raises `UnknownConversationError` for a supplied id that
    does not exist — never silently creates a replacement, which would
    make the client's own id meaningless.
    """
    if conversation_id is None:
        conversation = Conversation(user_id=user_id)
        session.add(conversation)
        await session.commit()
        return conversation

    conversation = await session.get(Conversation, conversation_id)
    if conversation is None:
        raise UnknownConversationError(conversation_id)
    return conversation


async def next_message_seq(session: AsyncSession, conversation_id: str) -> int:
    """1-indexed, per conversation (`ARCHITECTURE_V1.md` §7.3: "a stable
    `seq` for ordering")."""
    current_max = await session.scalar(
        select(func.max(Message.seq)).where(Message.conversation_id == conversation_id)
    )
    return (current_max or 0) + 1


async def persist_message(
    session: AsyncSession,
    *,
    conversation_id: str,
    role: str,
    content: str,
    request_id: str | None = None,
    model_used: str | None = None,
    tokens_in: int | None = None,
    tokens_out: int | None = None,
    cost_micro_usd: int | None = None,
    project_key: str | None = None,
) -> Message:
    """Write one `messages` row (FR-021), with its `seq` computed fresh
    and its four ADR-014 capture columns resolved fresh — every insert on
    a capture table must set all four explicitly (`db/models.py`'s own
    `CaptureColumns` docstring), and redaction (ADR-006) applied to
    `content` before it ever reaches the database.
    """
    seq = await next_message_seq(session, conversation_id)

    decision = resolve_capture(
        kind=CaptureKind.MESSAGE,
        project_key=project_key,
        source=_ROLE_TO_SOURCE.get(role, ContentSource.SYSTEM),
    )
    stored_content = apply_capture_to_content(decision, scrub(content))

    message = Message(
        conversation_id=conversation_id,
        seq=seq,
        role=role,
        content=stored_content,
        request_id=request_id,
        model_used=model_used,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_micro_usd=cost_micro_usd,
        capture_policy=decision.capture_policy.value,
        sensitivity=decision.sensitivity.value,
        retention_class=decision.retention_class.value,
        training_eligible=decision.training_eligible,
    )
    session.add(message)
    await session.commit()
    return message
