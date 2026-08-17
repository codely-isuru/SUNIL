"""Short-term memory read/write (FR-140, FR-144).

`read_recent_messages()` supplies "the current conversation's messages...
included as available context" (FR-140) by reading `messages` directly —
the conversation's own durable record is the context, not a duplicate
copy. `record_short_term_memory_retrieval()` writes the auditable
`memories` row stage 3 (`memory_retrieved`) persists, satisfying FR-144
("its `source` field references the originating request/task ID") with
a compact pointer/summary rather than a second copy of message content
(`ARCHITECTURE_V1.md` §21: "Pointer/summary of loaded context for the
current turn").
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from sunil.capture import CaptureKind, ContentSource
from sunil.db.capture import resolve_capture
from sunil.db.models import Memory, MemoryType, Message

_DEFAULT_LIMIT = 20


async def read_recent_messages(
    session: AsyncSession,
    *,
    conversation_id: str,
    limit: int = _DEFAULT_LIMIT,
) -> list[Message]:
    """The most recent `limit` messages in `conversation_id`, returned in
    conversation order (oldest first) — the shape a prompt builder wants,
    not the shape a "most recent N" query naturally returns."""
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.seq.desc())
        .limit(limit)
    )
    rows = list(result.scalars().all())
    rows.reverse()
    return rows


async def record_short_term_memory_retrieval(
    session: AsyncSession,
    *,
    user_id: str,
    source_request_id: str,
    conversation_id: str,
    message_count: int,
) -> Memory:
    """Stage 3's own persistence: one `memories` row per turn, `type=
    short_term`, `source_request_id` set to this request (FR-144).
    """
    decision = resolve_capture(kind=CaptureKind.MEMORY, source=ContentSource.SYSTEM)

    memory = Memory(
        user_id=user_id,
        type=MemoryType.SHORT_TERM.value,
        content=(
            f"Retrieved {message_count} prior message(s) from conversation "
            f"{conversation_id} as context for this request."
        ),
        source_request_id=source_request_id,
        capture_policy=decision.capture_policy.value,
        sensitivity=decision.sensitivity.value,
        retention_class=decision.retention_class.value,
        training_eligible=decision.training_eligible,
    )
    session.add(memory)
    await session.commit()
    return memory
