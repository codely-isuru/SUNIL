"""The n8n MCP server's MOUNT — `config/tools.yaml` + `config/permissions.yaml`.

These read the repository's real config files, not fixtures. ADR-034's rule is
"callable IFF it appears in `config/tools.yaml` with an explicit `operations:`
entry ... AND has a permission row", and both halves live in files a reviewer
edits by hand — so the thing worth pinning is the *repository's* mount, not a
loader's behaviour on a synthetic block (which `test_tools_config.py` already
covers).

Decisions are read through `permissions.engine.decide`, the production decision
function, rather than off the raw grant string: a test that asserts on the YAML
value would stay green if the engine ever stopped consulting it.
"""

from __future__ import annotations

from pathlib import Path

from sunil.core.permissions.engine import decide
from sunil.core.permissions.registry import load_permissions
from sunil.core.tool_framework.base import AdapterKind, PermissionDecision
from sunil.core.tool_framework.tools_config import (
    cross_validate_permissions,
    load_tools_config,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
TOOLS_YAML = REPO_ROOT / "config" / "tools.yaml"
PERMISSIONS_YAML = REPO_ROOT / "config" / "permissions.yaml"

#: The n8n MCP server's `config/tools.yaml` key. One MCP server is one tool
#: (ADR-034), so this string is also the permission-matrix tool name.
N8N_TOOL = "n8n_mcp"


def _tools():
    return load_tools_config(TOOLS_YAML)


def test_the_n8n_server_is_mounted_over_http_by_settings_field_name() -> None:
    """`base_url_env`/`auth_token_env` are Settings FIELD names, never literals.

    That indirection is what puts the URL through ADR-033's loopback-or-named-
    host validator and keeps the token a `SecretStr`; a literal URL in this file
    would bypass both, and a literal token would be a committed secret.
    """
    block = _tools().tools[N8N_TOOL]

    assert block.kind is AdapterKind.MCP_HTTP
    assert block.base_url_env == "SUNIL_N8N_MCP_BASE_URL"
    assert block.auth_token_env == "SUNIL_N8N_MCP_AUTH_TOKEN"
    assert block.command is None  # nothing is spawned on this lane


def test_post_update_is_a_configured_operation_with_sunil_owned_metadata() -> None:
    """The governed action the Stream E MCP Server Trigger workflow exposes.

    `read_only` and `timeout_s` are SUNIL's values, read from config — the
    server's `readOnlyHint` never reaches this dataclass (ADR-034 decision 3).
    """
    operation = _tools().tools[N8N_TOOL].operations["post_update"]

    assert operation.read_only is False
    assert operation.timeout_s > 0
    assert operation.params_model.model_config.get("extra") == "forbid"
    assert set(operation.params_model.model_fields) == {"project_key", "summary"}


def test_every_write_the_n8n_server_exposes_parks_for_the_owner() -> None:
    """A `read_only: false` n8n operation may never be granted a bare `allow`.

    Generic on purpose: the next operation added to this server is the one
    nobody re-reads the threat model for, and this fails on it by default.
    """
    permissions = load_permissions(PERMISSIONS_YAML)
    block = _tools().tools[N8N_TOOL]

    writes = {name for name, op in block.operations.items() if not op.read_only}
    assert writes, "the n8n server exposes no write — this test would pass vacuously"

    for agent_id in permissions.agent_ids():
        for operation in sorted(writes):
            result = decide(
                permissions, agent_id=agent_id, tool=N8N_TOOL, operation=operation
            )
            assert result.decision is not PermissionDecision.ALLOW, (
                f"{agent_id} holds ALLOW on the WRITE {N8N_TOOL}.{operation}; a "
                "third-party write must park for the owner (C1 §2.2)"
            )


def test_post_update_is_granted_to_the_project_manager_as_ask_user() -> None:
    result = decide(
        load_permissions(PERMISSIONS_YAML),
        agent_id="project_manager",
        tool=N8N_TOOL,
        operation="post_update",
    )

    assert result.decision is PermissionDecision.ASK_USER
    assert result.source == f"config:project_manager.{N8N_TOOL}.post_update"


def test_an_n8n_operation_nobody_configured_is_denied_structurally() -> None:
    """The half of ADR-034 that config cannot weaken: a tool the live server
    advertises but this repository never declared is not callable."""
    result = decide(
        load_permissions(PERMISSIONS_YAML),
        agent_id="project_manager",
        tool=N8N_TOOL,
        operation="delete_everything",
    )

    assert result.decision is PermissionDecision.DENY
    assert result.source == "default-deny"


def test_the_repository_mount_cross_validates() -> None:
    """Startup's own check, run in CI: no grant may name a tool or operation
    `config/tools.yaml` does not declare."""
    cross_validate_permissions(_tools(), load_permissions(PERMISSIONS_YAML))
