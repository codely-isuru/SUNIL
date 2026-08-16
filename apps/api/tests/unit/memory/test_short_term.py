"""`sunil.core.memory.short_term` (T11a) — FR-140, FR-144.

FR-140: "the current conversation's messages are included as available
context." FR-144: "any Memory record written during an M1 request... its
`source` field references the originating request/task ID."
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession
from sunil.core.conversations.gateway import persist_message
from sunil.core.memory.short_term import read_recent_messages, record_short_term_memory_retrieval
from sunil.db.models import Conversation, User


async def test_read_recent_messages_returns_messages_in_conversation_order(
    session: AsyncSession, user_and_conversation: tuple[User, Conversation]
) -> None:
    _user, conversation = user_and_conversation
    await persist_message(
        session, conversation_id=conversation.id, role="user", content="first", request_id="r1"
    )
    await persist_message(
        session,
        conversation_id=conversation.id,
        role="assistant",
        content="second",
        request_id="r1",
    )

    messages = await read_recent_messages(session, conversation_id=conversation.id)

    assert [m.content for m in messages] == ["first", "second"]


async def test_read_recent_messages_is_empty_for_a_brand_new_conversation(
    session: AsyncSession, user_and_conversation: tuple[User, Conversation]
) -> None:
    _user, conversation = user_and_conversation

    messages = await read_recent_messages(session, conversation_id=conversation.id)

    assert messages == []


async def test_read_recent_messages_respects_the_limit(
    session: AsyncSession, user_and_conversation: tuple[User, Conversation]
) -> None:
    _user, conversation = user_and_conversation
    for i in range(5):
        await persist_message(
            session,
            conversation_id=conversation.id,
            role="user",
            content=f"msg-{i}",
            request_id="r1",
        )

    messages = await read_recent_messages(session, conversation_id=conversation.id, limit=2)

    # The most recent two, still in conversation order.
    assert [m.content for m in messages] == ["msg-3", "msg-4"]


async def test_record_short_term_memory_retrieval_writes_a_memories_row(
    session: AsyncSession, user_and_conversation: tuple[User, Conversation]
) -> None:
    user, conversation = user_and_conversation

    memory = await record_short_term_memory_retrieval(
        session,
        user_id=user.id,
        source_request_id="req-1",
        conversation_id=conversation.id,
        message_count=3,
    )

    assert memory.id
    assert memory.type == "short_term"
    assert memory.user_id == user.id
    assert memory.source_request_id == "req-1"
    assert "3" in memory.content
    assert memory.sensitivity == "internal"
