"""Shared fixtures for `sunil.core.tasks` unit tests (T11a).

`StaticPool` in-memory SQLite so every connection in a test sees the same
schema (`tests/unit/test_models.py`'s own pattern) — a plain in-memory
SQLite URL would otherwise hand out a fresh, empty database per
connection.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sunil.db.base import Base
from sunil.db.models import Conversation, User, Workflow


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with sessionmaker() as s:
        yield s

    await engine.dispose()


@pytest_asyncio.fixture
async def user_and_conversation(session: AsyncSession) -> tuple[User, Conversation]:
    """A minimal owner user + conversation row, the FK targets a task and
    workflow need to exist against."""
    user = User(
        name="Test Owner",
        username="test-owner",
        password_hash="scrypt$16384$8$1$fake$fake",
        preferences={},
        security_settings={},
    )
    session.add(user)
    await session.flush()

    conversation = Conversation(user_id=user.id)
    session.add(conversation)
    await session.commit()

    return user, conversation


@pytest_asyncio.fixture
async def workflow(
    session: AsyncSession, user_and_conversation: tuple[User, Conversation]
) -> Workflow:
    user, _conversation = user_and_conversation
    wf = Workflow(
        owner_user_id=user.id,
        trigger="chat_message",
        status="pending",
        schedule=None,
        request_id="req-1",
    )
    session.add(wf)
    await session.commit()
    return wf
