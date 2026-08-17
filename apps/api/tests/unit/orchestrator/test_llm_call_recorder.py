"""`sunil.core.orchestrator.turn.DatabaseLLMCallRecorder` — the real,
DB-writing `LLMCallRecorder` (T6's seam, "most naturally T11b, which
already persists the turn"). Uses its own `sessionmaker`, mirroring
`ToolManager`'s own pattern (`core/tool_framework/manager.py`) rather
than the per-request `session` `LiveTurnExecutor` itself uses — the
Model Router is a per-app singleton, constructed once in
`sunil.main`'s lifespan, so its recorder must be too.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sunil.core.orchestrator.turn import DatabaseLLMCallRecorder
from sunil.core.routing.router import ProviderAttemptRecord
from sunil.db.base import Base
from sunil.db.models import LLMCall
from sunil.providers.base import ChatTurn, LLMPurpose
from sunil.redaction import register, reset_registry_for_tests


@pytest_asyncio.fixture
async def sessionmaker() -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


def _attempt(**overrides: object) -> ProviderAttemptRecord:
    defaults: dict[str, object] = dict(
        request_id="req-1",
        task_id=None,
        agent_id=None,
        purpose=LLMPurpose.PLAN,
        capability="general_reasoning",
        provider="anthropic",
        model="claude-sonnet-5",
        attempt=1,
        request_system="You are a test.",
        request_messages=[ChatTurn(role="user", content="hello")],
        request_schema=None,
        response_text=None,
        response_json={"intent": "project_status_review"},
        stop_reason="end_turn",
        input_tokens=100,
        output_tokens=50,
        cost_micro_usd=1234,
        pricing_version="2026-08-14",
        latency_ms=250,
        error_kind=None,
        provider_request_id="req_fake_1",
    )
    defaults.update(overrides)
    return ProviderAttemptRecord(**defaults)  # type: ignore[arg-type]


async def test_record_writes_a_real_llm_calls_row(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    recorder = DatabaseLLMCallRecorder(sessionmaker=sessionmaker)

    await recorder.record(_attempt())

    async with sessionmaker() as session:
        result = await session.execute(select(LLMCall).where(LLMCall.request_id == "req-1"))
        rows = list(result.scalars().all())

    assert len(rows) == 1
    row = rows[0]
    assert row.purpose == "plan"
    assert row.provider == "anthropic"
    assert row.model == "claude-sonnet-5"
    assert row.attempt == 1
    assert row.input_tokens == 100
    assert row.output_tokens == 50
    assert row.cost_micro_usd == 1234
    assert row.request_messages == [{"role": "user", "content": "hello"}]
    assert row.response_json == {"intent": "project_status_review"}
    assert row.capture_policy
    assert row.sensitivity
    assert row.retention_class


async def test_record_scrubs_a_registered_secret_out_of_the_request_system(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    reset_registry_for_tests()
    register("sk-ant-test-canary-do-not-use", name="anthropic_api_key")
    try:
        recorder = DatabaseLLMCallRecorder(sessionmaker=sessionmaker)
        await recorder.record(
            _attempt(
                request_id="req-2",
                request_system="the key is sk-ant-test-canary-do-not-use",
            )
        )

        async with sessionmaker() as session:
            result = await session.execute(select(LLMCall).where(LLMCall.request_id == "req-2"))
            row = result.scalar_one()
    finally:
        reset_registry_for_tests()

    assert "sk-ant-test-canary-do-not-use" not in (row.request_system or "")
    assert "«redacted:anthropic_api_key»" in (row.request_system or "")
