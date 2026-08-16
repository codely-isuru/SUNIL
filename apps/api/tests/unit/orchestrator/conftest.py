"""Shared fixtures for `sunil.core.orchestrator` unit tests (T9).

Builds a `Registries` instance directly in memory — no YAML, no
temp-directory I/O — mirroring T3's minimal valid configuration
(`apps/api/tests/unit/registry/conftest.py`'s `valid_config_files()`)
without depending on that module by name, so this package's `conftest.py`
never collides on import with the registry package's own `conftest.py`.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sunil.capture import CaptureKind, CapturePolicy, CaptureRule, RetentionClass, Sensitivity
from sunil.core.registry.agents import AgentDefinition, AgentRegistry
from sunil.core.registry.capture import CaptureRegistry
from sunil.core.registry.loader import Registries
from sunil.core.registry.model_catalogue import CapabilityDefinition, ModelDefinition, ModelRegistry
from sunil.core.registry.permissions import PermissionRegistry
from sunil.core.registry.projects import GithubCoordinates, ProjectDefinition, ProjectRegistry
from sunil.core.registry.tools import ToolDefinition, ToolOperationDefinition, ToolRegistry


def build_test_registries() -> Registries:
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
        {"project_manager": {"github": {"list_recent_activity": "allow"}}}
    )

    projects = ProjectRegistry(
        {
            "easy_clean_workforce": ProjectDefinition(
                key="easy_clean_workforce",
                display_name="EasyClean Workforce",
                github=GithubCoordinates(owner="codely-isuru", repo="easy_clean_workforce"),
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
    """A minimal, fully-legal plan draft against `registries()` above —
    every test that needs a starting point mutates a copy of this."""
    return {
        "intent": "project_status_review",
        "confidence": 0.9,
        "privacy_level": "internal",
        "objective": "Check on EasyClean Workforce.",
        "project_key": "easy_clean_workforce",
        "agents": ["project_manager"],
        "tools": ["github"],
        "steps": [
            {"id": "s1", "action": "resolve_project", "tool": "none"},
            {"id": "s2", "action": "list_recent_activity", "tool": "github"},
            {"id": "s3", "action": "summarise_activity", "tool": "none"},
        ],
    }


@pytest.fixture
def valid_plan() -> dict:
    """A fresh copy of a minimal, fully-legal plan draft against
    `registries()` above — every test that needs a legal starting point
    takes this fixture and mutates a copy."""
    return _valid_plan_dict()
