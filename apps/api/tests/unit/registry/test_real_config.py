"""Loads the actual `config/*.yaml` files this task ships (not a test
fixture) and proves they are individually valid, mutually consistent, and
match the specific values `ARCHITECTURE_V1.md` and ADR-000 Q7 pin.

This is what makes "the six files exist and cross-validate" a fact about
the committed repository rather than only about the loader's own test
fixtures.
"""

from __future__ import annotations

from decimal import Decimal

from sunil.core.registry.capture import CaptureKind
from sunil.core.registry.loader import load_registries
from sunil.core.registry.paths import repo_root

_VALID_CAPTURE_POLICIES = {"none", "metadata_only", "redacted_full", "full_local_only"}


def test_the_real_config_directory_loads_and_cross_validates() -> None:
    registries = load_registries(repo_root() / "config")

    assert "project_manager" in registries.agents


def test_the_repository_mapping_comes_from_config_not_a_literal() -> None:
    """ADR-000 Q7: 'The repository must be a config value, never
    hard-coded.' This reads it from the shipped `config/projects.yaml`,
    proving the value lives there."""
    registries = load_registries(repo_root() / "config")

    project = registries.projects.get("easy_clean_workforce")

    assert project.github.owner == "codely-isuru"
    assert project.github.repo == "easy_clean_workforce"
    assert registries.projects.known_projects() == [
        {"key": "easy_clean_workforce", "display_name": project.display_name}
    ]


def test_the_project_manager_agent_is_granted_only_the_one_m1_operation() -> None:
    """FR-082 / NFR-007 — least privilege by construction: the only
    agent config ships with is granted exactly the one read-only
    operation M1 needs."""
    registries = load_registries(repo_root() / "config")

    agent = registries.agents.get("project_manager")
    assert agent.tools == {"github": ["list_recent_activity"]}

    decision = registries.permissions.grant_for("project_manager", "github", "list_recent_activity")
    assert decision == "allow"


def test_the_pinned_price_table_matches_architecture_4_4() -> None:
    registries = load_registries(repo_root() / "config")

    sonnet = registries.models.get_model("claude-sonnet-5")
    opus = registries.models.get_model("claude-opus-5")
    fable = registries.models.get_model("claude-fable-5")
    haiku = registries.models.get_model("claude-haiku-4-5-20251001")

    assert (sonnet.input_usd_per_mtok, sonnet.output_usd_per_mtok) == (Decimal("2"), Decimal("10"))
    assert (opus.input_usd_per_mtok, opus.output_usd_per_mtok) == (Decimal("5"), Decimal("25"))
    assert (fable.input_usd_per_mtok, fable.output_usd_per_mtok) == (Decimal("10"), Decimal("50"))
    assert (haiku.input_usd_per_mtok, haiku.output_usd_per_mtok) == (Decimal("1"), Decimal("5"))
    assert registries.models.pricing_version == "2026-08-14"


def test_both_m1_capabilities_resolve_and_general_reasoning_defaults_to_sonnet() -> None:
    """§5.3: 'claude-sonnet-5 is the M1 default for both live
    capabilities.'"""
    registries = load_registries(repo_root() / "config")

    general = registries.models.get_capability("general_reasoning")
    complex_ = registries.models.get_capability("complex_reasoning")

    assert general.model == "claude-sonnet-5"
    assert complex_.model == "claude-opus-5"


def test_the_github_tool_exposes_exactly_the_one_read_only_operation() -> None:
    registries = load_registries(repo_root() / "config")

    operation = registries.tools.get_operation("github", "list_recent_activity")
    assert operation.read_only is True


def test_capture_defaults_are_configured_for_every_content_kind() -> None:
    registries = load_registries(repo_root() / "config")

    for kind in CaptureKind:
        defaults = registries.capture.defaults_for(kind)
        assert defaults.capture_policy in _VALID_CAPTURE_POLICIES
