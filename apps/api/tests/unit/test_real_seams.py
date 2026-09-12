"""`SUNIL_*=real` — the seams `api/wiring.py` refused to resolve until this round.

Wave 1 shipped every implementation and wired none of them: `resolve_*('real')`
raised `SeamUnavailable` naming the owning stream, so the ONLY bootable
configuration was one a test injected. That is a safe default and a useless
product — the app could not come up on its own.

These tests are the real resolutions, and they are about the SHAPE of what boots:

* the tool registry is built from `config/tools.yaml` + `config/permissions.yaml`
  (ADR-034's "callable IFF configured AND granted"), with the real
  `PermissionEngineHook` — not a permissive stand-in;
* a tool that cannot start is **absent** from the registry rather than
  half-present, and its absence is a WARNING, not a boot failure (C1 §5,
  S-A-tools §4);
* the C4 seam is the real `DatabaseApprovalsService` on the application's own
  engine — two engines would let the queue read a different database than the
  chokepoint writes;
* the chokepoint gets the C-1 transactional seam, because it can: the real
  service and the real audit hook share one engine;
* an `agents.yaml` grant naming a tool the wired catalogue does not offer is a
  startup WARNING (wave-1 ruling R1's follow-up) — never a refusal, because that
  exact file is a legal state today (`fake_tool`).

Injection is unaffected and still wins: `fake` requires it, and a passed seam is
used verbatim.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr
from structlog.testing import capture_logs
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from sunil.api import wiring
from sunil.api.wiring import Seams
from sunil.core.approvals.service import DatabaseApprovalsService
from sunil.core.tool_framework.manager import ToolManager
from sunil.settings import Settings

CONFIG_DIR = str(Path(__file__).resolve().parents[2].parent.parent / "config")


def settings(**overrides) -> Settings:
    return Settings(
        _env_file=None,
        session_secret="test-session-secret-not-a-real-key",
        sunil_config_dir=CONFIG_DIR,
        sunil_llm_provider_lane="fake",
        **overrides,
    )


@pytest.fixture
def engine():
    made = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    yield made


# --------------------------------------------------------------------------- #
# C4 — the real approvals service
# --------------------------------------------------------------------------- #
def test_the_real_c4_seam_is_the_database_service_on_the_apps_engine(engine) -> None:
    resolved = wiring.resolve_approvals(
        settings(sunil_approvals_service="real"), Seams(), engine=engine
    )

    assert isinstance(resolved, DatabaseApprovalsService)
    assert resolved.engine is engine


def test_the_real_c4_seam_takes_its_ttl_and_grace_from_settings(engine) -> None:
    """C4 §1's windows are operator configuration (§5), and a service that
    ignored them would expire approvals on a schedule nobody chose."""
    resolved = wiring.resolve_approvals(
        settings(
            sunil_approvals_service="real",
            sunil_approval_ttl_hours=5,
            sunil_approval_consume_grace_hours=2,
        ),
        Seams(),
        engine=engine,
    )

    assert (resolved.config.ttl_hours, resolved.config.consume_grace_hours) == (5, 2)


def test_a_real_c4_selection_without_an_engine_is_a_boot_failure() -> None:
    """The seam is a database service; resolving it against nothing would give
    the queue a service with no rows rather than a named failure."""
    with pytest.raises(wiring.SeamUnavailable, match="engine"):
        wiring.resolve_approvals(settings(sunil_approvals_service="real"), Seams())


def test_an_injected_c4_seam_still_wins(engine) -> None:
    injected = object()
    assert (
        wiring.resolve_approvals(
            settings(sunil_approvals_service="real"), Seams(approvals=injected), engine=engine
        )
        is injected
    )


def test_a_fake_c4_selection_without_injection_is_still_a_boot_failure() -> None:
    with pytest.raises(wiring.SeamUnavailable):
        wiring.resolve_approvals(settings(sunil_approvals_service="fake"), Seams())


# --------------------------------------------------------------------------- #
# C1 — the real tool registry and chokepoint
# --------------------------------------------------------------------------- #
def test_the_real_tool_registry_is_built_from_config(engine) -> None:
    """`config/tools.yaml` is the authority (ADR-034). With no GITHUB_TOKEN and
    no n8n token in this `Settings`, both credential-bearing tools are absent and
    said so out loud; the app still boots, because a missing credential is an
    operator state, not a code bug."""
    with capture_logs() as logged:
        registry = wiring.build_tool_registry(
            settings(github_token=None, sunil_n8n_mcp_auth_token=None)
        )

    assert [a.name for a in registry.adapters] == []
    skipped = {name for name, _ in registry.skipped}
    assert skipped == {"github", "github_mcp", "n8n_mcp"}
    # Captured through structlog rather than a stream, because the renderer is
    # configured once per process and a second test's configuration must not be
    # able to make this assertion vacuous.
    warned = {entry["tool"] for entry in logged if entry["event"] == "tool_unavailable"}
    assert warned == {"github", "github_mcp", "n8n_mcp"}


def test_a_tool_whose_credentials_are_present_is_registered(engine) -> None:
    registry = wiring.build_tool_registry(
        settings(
            github_token=SecretStr("ghp-not-a-real-token"),
            sunil_n8n_mcp_auth_token=SecretStr("n8n-not-a-real-token"),
        )
    )

    names = {adapter.name for adapter in registry.adapters}
    assert {"github_mcp", "n8n_mcp"} <= names
    # …and the operations are the FILE's, never the server's self-description.
    by_name = {adapter.name: adapter for adapter in registry.adapters}
    assert set(by_name["github_mcp"].operations) == {"issues_list", "issues_close"}


def test_the_real_chokepoint_carries_the_permission_engine_and_the_tx_seam(engine) -> None:
    """The manager is built per plan execution (ADR-004 Amendment 1), so the seam
    resolves to a FACTORY. What it produces must be the real `ToolManager` with
    the C-1 transactional collaborator — which is only possible because the C4
    service and the audit hook share this engine."""
    from sunil.core.audit.hooks import DbToolAuditHook

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    resolved = settings(sunil_tool_manager="real", github_token=None)
    approvals = wiring.resolve_approvals(
        settings(sunil_approvals_service="real"), Seams(), engine=engine
    )

    factory = wiring.resolve_tool_manager(
        resolved,
        Seams(),
        approvals=approvals,
        sessionmaker=sessionmaker,
        registry=wiring.build_tool_registry(resolved),
    )
    manager = factory(DbToolAuditHook(sessionmaker, validated_plan_id="plan-1"))

    assert isinstance(manager, ToolManager)
    assert manager._transaction is not None
    # Default-deny is structural: an ungranted triple is denied by the engine,
    # not by the absence of a grant file.
    decision = manager._permission_hook(
        agent_id="nobody", tool="github", operation="list_recent_activity"
    )
    assert decision.decision.value == "deny"


def test_a_real_chokepoint_over_an_in_memory_c4_seam_gets_no_tx_collaborator(engine) -> None:
    """The transactional path needs a shared database transaction. An injected
    in-memory C4 fake has none, so the manager is built WITHOUT the collaborator
    rather than with one that cannot honour its contract — the fallback C1 §6
    describes, chosen at boot and never sniffed on the request path."""
    from sunil.core.audit.hooks import DbToolAuditHook

    from tests.fakes.fake_approvals import FakeApprovalsService

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    resolved = settings(sunil_tool_manager="real", github_token=None)

    factory = wiring.resolve_tool_manager(
        resolved,
        Seams(),
        approvals=FakeApprovalsService(),
        sessionmaker=sessionmaker,
        registry=wiring.build_tool_registry(resolved),
    )
    manager = factory(DbToolAuditHook(sessionmaker, validated_plan_id="plan-1"))

    assert manager._transaction is None


def test_a_database_c4_seam_with_a_non_conforming_audit_hook_refuses_to_boot(
    engine,
) -> None:
    """Security residual R-1a — the SILENT-DOWNGRADE combination, named.

    The two conditions in the old guard meant two different things and had two
    different correct answers. `approvals` without an `engine` is a legitimate
    configuration (the in-memory fake above): there is no transaction to share,
    and building without the collaborator is right. An audit hook without
    `attempt_on` while the C4 service IS database-backed is not a configuration
    at all — it is a broken deployment, and `and`-ing the two made it boot
    QUIETLY on the non-transactional path, reopening the exact window Security
    condition C-1 closed: a crash between the consume CAS and the audit write
    leaves the approval spent with no `tool_calls` row.

    So the factory guards on the engine alone and lets `TransactionalApprovals`'
    constructor raise, which is what it was written to do ("checked at
    construction, so a misconfiguration is a boot failure rather than a silently
    non-transactional call path")."""

    class _HookWithoutAttemptOn:
        """A two-phase C1 §2.2 hook that cannot write on a caller's connection."""

        async def attempt(self, record):  # pragma: no cover - never reached
            raise AssertionError("boot should have failed before any call")

        async def finalise(self, audit_id, **kwargs):  # pragma: no cover
            raise AssertionError("boot should have failed before any call")

    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    resolved = settings(sunil_tool_manager="real", github_token=None)
    approvals = wiring.resolve_approvals(
        settings(sunil_approvals_service="real"), Seams(), engine=engine
    )

    factory = wiring.resolve_tool_manager(
        resolved,
        Seams(),
        approvals=approvals,
        sessionmaker=sessionmaker,
        registry=wiring.build_tool_registry(resolved),
    )

    with pytest.raises(TypeError, match="attempt_on"):
        factory(_HookWithoutAttemptOn())


# --------------------------------------------------------------------------- #
# R1 follow-up — the grants-vs-catalogue startup warning
# --------------------------------------------------------------------------- #
def test_a_grant_for_a_tool_the_catalogue_does_not_offer_warns() -> None:
    """Wave-1 ruling R1's follow-up. `load_registries` cross-validates nothing in
    the grants→tools direction, so an operator typo (`github` → `githbu`) is a
    tool that can never be planned and never says why. A WARNING, never a
    refusal: `config/agents.yaml`'s `fake_tool` grant is a legal state the
    ruling explicitly preserved."""
    from sunil.core.registry.loader import AgentDefinition, Registries

    registries = Registries(
        agents={
            "project_manager": AgentDefinition(
                id="project_manager",
                role="project_manager",
                preferred_capability="general_reasoning",
                tools={"githbu": ("list_recent_activity",), "github": ("list_recent_activity",)},
            )
        },
        projects={},
    )

    with capture_logs() as logged:
        wiring.warn_on_ungrantable_catalogue(registries, catalogue_tools={"github"})

    [warning] = [e for e in logged if e["event"] == "granted_tool_not_in_catalogue"]
    assert warning["granted_but_unwired"] == ["githbu"]
    assert warning["wired_catalogue"] == ["github"]  # the line names both sides
    assert warning["log_level"] == "warning"


def test_the_grant_warning_is_silent_when_every_grant_is_wired() -> None:
    from sunil.core.registry.loader import AgentDefinition, Registries

    registries = Registries(
        agents={
            "project_manager": AgentDefinition(
                id="project_manager",
                role="project_manager",
                preferred_capability="general_reasoning",
                tools={"github": ("list_recent_activity",)},
            )
        },
        projects={},
    )

    with capture_logs() as logged:
        wiring.warn_on_ungrantable_catalogue(
            registries, catalogue_tools={"github", "n8n_mcp"}
        )

    assert logged == []


# --------------------------------------------------------------------------- #
# config/projects.yaml — the repo mapping the native GitHub tool needs
# --------------------------------------------------------------------------- #
def test_a_project_can_declare_the_repository_the_native_tool_reads(tmp_path) -> None:
    """M1's T-16 rule, ported with the adapter: `list_recent_activity`'s ONLY
    parameter is `project_key`, and the owner/repo it resolves to is
    configuration. Without a place to put that mapping the native tool cannot be
    wired at all — it would need the plan to name a repository, which is the one
    thing the parameter shape exists to prevent."""
    from sunil.core.registry.loader import load_registries

    (tmp_path / "agents.yaml").write_text(
        "agents:\n  a:\n    role: a\n    preferred_capability: general_reasoning\n",
        encoding="utf-8",
    )
    (tmp_path / "projects.yaml").write_text(
        "projects:\n  sunil:\n    display_name: SUNIL\n    repo: codely-isuru/SUNIL\n"
        "  nameless:\n    display_name: No repo\n",
        encoding="utf-8",
    )

    projects = load_registries(tmp_path).projects

    assert projects["sunil"].repo == "codely-isuru/SUNIL"
    assert projects["nameless"].repo is None
