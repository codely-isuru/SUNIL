"""Shared fixtures for `sunil.core.tool_framework` unit tests (T8).

Builds a `Registries` instance directly in memory (mirroring
`tests/unit/orchestrator/conftest.py`'s own builder, duplicated rather
than imported across packages — pytest's rootdir-relative `conftest`
module-name collision risk when two sibling packages both define a
`conftest.py` and a test file does a bare `from conftest import ...`,
per this task's own T9 lesson) and a real, schema-migrated in-memory
SQLite session factory so `ToolManager`'s actual `INSERT` path is
exercised, not mocked away.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sunil.capture import CaptureKind, CapturePolicy, CaptureRule, RetentionClass, Sensitivity
from sunil.core.orchestrator.guards import ExecutionMetadata
from sunil.core.orchestrator.plan_models import ValidatedPlan
from sunil.core.orchestrator.plan_validator import validate_plan
from sunil.core.registry.agents import AgentDefinition, AgentRegistry
from sunil.core.registry.capture import CaptureRegistry
from sunil.core.registry.loader import Registries
from sunil.core.registry.model_catalogue import CapabilityDefinition, ModelDefinition, ModelRegistry
from sunil.core.registry.permissions import PermissionRegistry
from sunil.core.registry.projects import GithubCoordinates, ProjectDefinition, ProjectRegistry
from sunil.core.registry.tools import ToolDefinition, ToolOperationDefinition, ToolRegistry
from sunil.db.base import Base


def build_test_registries(*, grant: str = "allow") -> Registries:
    agents = AgentRegistry(
        {
            "project_manager": AgentDefinition(
                id="project_manager",
                role="Manage software projects and identify risks.",
                instructions=["Review recent project activity."],
                objectives=["Report current project status."],
                memory_scope=["short_term"],
                preferred_capability="general_reasoning",
                escalation_capability="complex_reasoning",
                tools={"github": ["list_recent_activity"]},
            )
        }
    )

    permissions = PermissionRegistry(
        {"project_manager": {"github": {"list_recent_activity": grant}}}
    )

    projects = ProjectRegistry(
        {
            "sample_project": ProjectDefinition(
                key="sample_project",
                display_name="Sample Project",
                github=GithubCoordinates(owner="sample-owner", repo="sample-repo"),
            )
        }
    )

    tools = ToolRegistry(
        {
            "github": ToolDefinition(
                name="github",
                display_name="GitHub",
                operations={
                    "list_recent_activity": ToolOperationDefinition(
                        name="list_recent_activity",
                        read_only=True,
                        description="Recent commits, open PRs and open issues.",
                        timeout_s=15,
                        params={"project_key": {"type": "string", "required": True}},
                    )
                },
            )
        }
    )

    models = ModelRegistry(
        pricing_version="2026-08-14",
        models={
            "claude-sonnet-5": ModelDefinition(
                model_id="claude-sonnet-5",
                provider="anthropic",
                context_window=1_000_000,
                max_output=128_000,
                input_usd_per_mtok=Decimal("2"),
                output_usd_per_mtok=Decimal("10"),
                supports_structured_output=True,
            )
        },
        capabilities={
            "general_reasoning": CapabilityDefinition(
                capability="general_reasoning",
                provider="anthropic",
                model="claude-sonnet-5",
                max_tokens=1024,
                timeout_s=20,
            )
        },
    )

    capture = CaptureRegistry(
        defaults={
            kind: CaptureRule(
                capture_policy=CapturePolicy.REDACTED_FULL,
                sensitivity=Sensitivity.INTERNAL,
                retention_class=RetentionClass.STANDARD,
            )
            for kind in CaptureKind
        },
        project_overrides={},
    )

    return Registries(
        agents=agents,
        permissions=permissions,
        projects=projects,
        models=models,
        tools=tools,
        capture=capture,
    )


@pytest.fixture
def registries() -> Registries:
    return build_test_registries()


def _valid_plan_dict() -> dict:
    return {
        "intent": "project_status_review",
        "confidence": 0.9,
        "privacy_level": "internal",
        "objective": "Check on Sample Project.",
        "project_key": "sample_project",
        "agents": ["project_manager"],
        "tools": ["github"],
        "steps": [
            {"id": "s1", "action": "resolve_project", "tool": "none"},
            {"id": "s2", "action": "list_recent_activity", "tool": "github"},
            {"id": "s3", "action": "summarise_activity", "tool": "none"},
        ],
    }


@pytest.fixture
def validated_plan(registries: Registries) -> ValidatedPlan:
    """A genuine `ValidatedPlan`, minted the only legal way — through
    `plan_validator.validate_plan()` — so every manager test exercises
    the real guard site 3 rather than a stand-in."""
    return validate_plan(_valid_plan_dict(), registries)


@pytest.fixture
def execution_metadata(validated_plan: ValidatedPlan) -> ExecutionMetadata:
    return ExecutionMetadata(
        validated_plan_id=validated_plan.plan_id,
        request_id="req-1",
        task_id="task-1",
        agent_id="project_manager",
    )


@pytest_asyncio.fixture
async def sessionmaker() -> AsyncGenerator[async_sessionmaker[AsyncSession]]:
    """A fresh, isolated in-memory schema for exactly one test —
    `StaticPool` so every connection sees the same database
    (`tests/unit/test_models.py`'s own pattern)."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield async_sessionmaker(engine, expire_on_commit=False)

    await engine.dispose()
