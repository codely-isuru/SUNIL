"""`sunil.core.conversations.gateway` (T11a) — FR-021, FR-140.

FR-021: "Every message (owner-authored and SUNIL-authored) is persisted
with its conversation_id, user_id, and timestamp."
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from sunil.core.conversations.gateway import (
    UnknownConversationError,
    get_or_create_conversation,
    next_message_seq,
    persist_message,
)
from sunil.db.models import User


async def test_get_or_create_conversation_creates_a_new_one_when_none_is_given(
    session: AsyncSession, user: User
) -> None:
    conversation = await get_or_create_conversation(session, user_id=user.id, conversation_id=None)

    assert conversation.id
    assert conversation.user_id == user.id


async def test_get_or_create_conversation_loads_an_existing_one(
    session: AsyncSession, user: User
) -> None:
    created = await get_or_create_conversation(session, user_id=user.id, conversation_id=None)

    loaded = await get_or_create_conversation(session, user_id=user.id, conversation_id=created.id)

    assert loaded.id == created.id


async def test_get_or_create_conversation_rejects_an_unknown_id(
    session: AsyncSession, user: User
) -> None:
    with pytest.raises(UnknownConversationError):
        await get_or_create_conversation(session, user_id=user.id, conversation_id="does-not-exist")


async def test_next_message_seq_starts_at_one(session: AsyncSession, user: User) -> None:
    conversation = await get_or_create_conversation(session, user_id=user.id, conversation_id=None)

    seq = await next_message_seq(session, conversation.id)

    assert seq == 1


async def test_next_message_seq_increments_after_a_persisted_message(
    session: AsyncSession, user: User
) -> None:
    conversation = await get_or_create_conversation(session, user_id=user.id, conversation_id=None)
    await persist_message(
        session,
        conversation_id=conversation.id,
        role="user",
        content="hello",
        request_id="req-1",
    )

    seq = await next_message_seq(session, conversation.id)

    assert seq == 2


async def test_persist_message_stores_role_content_and_request_id(
    session: AsyncSession, user: User
) -> None:
    conversation = await get_or_create_conversation(session, user_id=user.id, conversation_id=None)

    message = await persist_message(
        session,
        conversation_id=conversation.id,
        role="user",
        content="Check on Sample Project.",
        request_id="req-1",
    )

    assert message.id
    assert message.conversation_id == conversation.id
    assert message.role == "user"
    assert message.content == "Check on Sample Project."
    assert message.request_id == "req-1"
    assert message.seq == 1
    assert message.created_at is not None


async def test_persist_message_sets_capture_columns(session: AsyncSession, user: User) -> None:
    conversation = await get_or_create_conversation(session, user_id=user.id, conversation_id=None)

    message = await persist_message(
        session,
        conversation_id=conversation.id,
        role="assistant",
        content="All quiet on Sample Project.",
        request_id="req-1",
    )

    assert message.capture_policy == "redacted_full"
    assert message.sensitivity == "internal"
    assert message.retention_class == "standard"
    assert message.training_eligible is True


async def test_persist_message_redacts_a_registered_secret_from_content(
    session: AsyncSession, user: User
) -> None:
    from sunil import redaction

    secret_value = "fake-test-secret-needle-for-message-redaction"
    redaction.register(secret_value, name="test_secret")
    try:
        conversation = await get_or_create_conversation(
            session, user_id=user.id, conversation_id=None
        )

        message = await persist_message(
            session,
            conversation_id=conversation.id,
            role="user",
            content=f"here is my token {secret_value}",
            request_id="req-1",
        )

        assert secret_value not in (message.content or "")
    finally:
        redaction.reset_registry_for_tests()


async def test_second_message_in_a_conversation_gets_seq_two(
    session: AsyncSession, user: User
) -> None:
    conversation = await get_or_create_conversation(session, user_id=user.id, conversation_id=None)
    first = await persist_message(
        session, conversation_id=conversation.id, role="user", content="a", request_id="req-1"
    )
    second = await persist_message(
        session,
        conversation_id=conversation.id,
        role="assistant",
        content="b",
        request_id="req-1",
    )

    assert first.seq == 1
    assert second.seq == 2
