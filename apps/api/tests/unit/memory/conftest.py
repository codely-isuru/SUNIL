"""Shared fixtures for `sunil.core.memory` unit tests (T11a)."""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sunil.db.base import Base
from sunil.db.models import Conversation, User


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
