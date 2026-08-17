"""The ET-12 end-to-end harness: one real turn, real pipeline, faked edges.

Deliberately **not** built on `tests/exit/`'s harness. QA's fixtures are good
and this suite could import them, but a security assertion that inherits QA's
scaffolding also inherits any defect in it: if the fake provider or the mock
upstream is subtly wrong, ET-12 goes green for the wrong reason. Everything
below drives *production* wiring — `LiveTurnExecutor`, the real `ModelRouter`,
the real `ToolManager`, the real `GitHubAdapter` and the real projection — and
fakes only the two genuinely external things: the LLM provider and GitHub's
HTTP responses.

The GitHub edge is faked through the `client` seam on `GitHubAdapter`, which
exists because T19 asked for it before T8 was written ("an adapter whose
external boundary cannot be faked is a finding in its own right"). No network
and no credential is involved.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

import httpx
from security_helpers import REPO_ROOT
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_OWNER_MESSAGE = "Check on EasyClean Workforce"
_PROJECT_KEY = "easy_clean_workforce"


@dataclass
class TurnRecord:
    """What one driven turn produced, read back from the database."""

    outcome: str
    failure_kind: str | None
    assistant_content: str | None
    llm_calls: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]


def _plan_for(registries: Any) -> dict[str, Any]:
    """Build a schema-valid plan from the *live* schema rather than a
    hand-copied literal, so this harness cannot drift out of step with
    `build_plan_schema()` and start failing for a reason unrelated to
    injection."""
    from sunil.core.orchestrator.plan_schema import build_plan_schema

    schema = build_plan_schema(registries)
    step_props = schema["properties"]["steps"]["items"]["properties"]
    actions = step_props["action"]["enum"]
    tool_actions = [a for a in actions if a not in ("summarise", "respond")]
    return {
        "intent": "project_status_review",
        "confidence": 0.9,
        "privacy_level": "internal",
        "objective": "Report current project status.",
        "project_key": _PROJECT_KEY,
        "agents": ["project_manager"],
        "tools": ["github"],
        "steps": [
            {
                "id": "s1",
                "action": tool_actions[0] if tool_actions else actions[0],
                "tool": "github",
            }
        ],
    }


class _ScriptedProvider:
    """Satisfies `sunil.providers.base.LLMProvider` structurally.

    Returns the plan for a schema-requesting call and prose for the analysis
    call. The prose deliberately does not comply with any injected
    instruction: ET-12 asserts the *pipeline* keeps external content out of
    the prompt, and a fake that obeyed an injection would only be testing the
    fake.
    """

    name = "anthropic"

    def __init__(self, plan: dict[str, Any], analysis_text: str) -> None:
        self._plan = plan
        self._analysis_text = analysis_text
        self.requests: list[Any] = []

    def capabilities(self, model: str) -> Any:
        from sunil.providers.base import ModelCapabilities

        return ModelCapabilities(
            context_window=1_000_000,
            max_output=128_000,
            supports_structured_output=True,
            input_usd_per_mtok=Decimal("2"),
            output_usd_per_mtok=Decimal("10"),
        )

    async def generate(self, model: str, request: Any, *, timeout_s: float | None = None) -> Any:
        from sunil.providers.base import LLMResponse

        self.requests.append(request)
        structured = getattr(request, "json_schema", None) is not None
        return LLMResponse(
            text=None if structured else self._analysis_text,
            data=self._plan if structured else None,
            provider=self.name,
            model=model,
            input_tokens=120,
            output_tokens=40,
            stop_reason="end_turn",
            provider_request_id="req_fake",
            latency_ms=5,
        )


def _github_transport(payload: dict[str, list[dict]]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/commits"):
            body = payload.get("commits", [])
        elif path.endswith("/pulls"):
            body = payload.get("pulls", [])
        elif path.endswith("/issues"):
            body = payload.get("issues", [])
        else:
            body = []
        return httpx.Response(200, json=body)

    return httpx.MockTransport(handle)


async def _drive(github_payload: dict[str, list[dict]], *, message: str) -> TurnRecord:
    from sunil.agents.project_manager.agent import ProjectManagerAgent
    from sunil.core.orchestrator.turn import DatabaseLLMCallRecorder, LiveTurnExecutor
    from sunil.core.registry.loader import load_registries
    from sunil.core.routing.router import ModelRouter
    from sunil.core.tool_framework.manager import ToolManager
    from sunil.core.trace.context import LiveTraceContext
    from sunil.db.base import Base
    from sunil.db.models import Conversation, LLMCall, ToolCall, User
    from sunil.providers.registry import ProviderRegistry
    from sunil.tools.github.adapter import GitHubAdapter

    engine = create_async_engine("sqlite+aiosqlite://")
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    registries = load_registries(REPO_ROOT / "config")

    provider = _ScriptedProvider(
        _plan_for(registries),
        "Recent activity looks routine: a handful of commits and one open issue.",
    )
    provider_registry = ProviderRegistry()
    provider_registry.register(provider)

    router = ModelRouter(
        model_registry=registries.models,
        provider_registry=provider_registry,
        recorder=DatabaseLLMCallRecorder(sessionmaker=sessionmaker),
    )

    adapter = GitHubAdapter(
        projects=registries.projects,
        token="github_pat_fake-security-suite-value",
        client=httpx.AsyncClient(
            base_url="http://github.local", transport=_github_transport(github_payload)
        ),
    )
    tool_manager = ToolManager(
        adapters={adapter.name: adapter}, registries=registries, sessionmaker=sessionmaker
    )

    request_id = "11111111-2222-4333-8444-555555555555"
    async with sessionmaker() as session:
        user = User(name="Owner", username="owner", password_hash="x")
        session.add(user)
        await session.commit()
        conversation = Conversation(user_id=user.id, title="t")
        session.add(conversation)
        await session.commit()

        trace = LiveTraceContext(
            request_id=request_id,
            user_id=user.id,
            conversation_id=conversation.id,
            sessionmaker=sessionmaker,
            turn_deadline_s=40.0,
        )
        executor = LiveTurnExecutor(
            session=session,
            registries=registries,
            model_router=router,
            tool_manager=tool_manager,
            agents={"project_manager": ProjectManagerAgent()},
        )
        result = await executor.run_turn(
            request_id=request_id,
            user_id=user.id,
            conversation_id=conversation.id,
            message=message,
            trace=trace,
        )

    async with sessionmaker() as session:
        llm_rows = (await session.execute(select(LLMCall))).scalars().all()
        tool_rows = (await session.execute(select(ToolCall))).scalars().all()
        llm_calls = [
            {
                "purpose": row.purpose,
                "request_system": row.request_system,
                "request_messages": row.request_messages,
                "response_text": row.response_text,
            }
            for row in llm_rows
        ]
        tool_calls = [
            {
                "tool": row.tool,
                "operation": row.operation,
                "parameters": row.parameters,
                "result": row.result,
                "permission_decision": row.permission_decision,
                "status": row.status,
                "validated_plan_id": row.validated_plan_id,
            }
            for row in tool_rows
        ]

    await engine.dispose()
    return TurnRecord(
        outcome=result.outcome,
        failure_kind=result.failure_kind,
        assistant_content=result.assistant_content,
        llm_calls=llm_calls,
        tool_calls=tool_calls,
    )


def run_status_turn(
    github_payload: dict[str, list[dict]], *, message: str = _OWNER_MESSAGE
) -> TurnRecord:
    """Drive one complete turn and return everything it persisted."""
    return asyncio.run(_drive(github_payload, message=message))
