"""Unit tests — the ``config/tools.yaml`` loader and the startup cross-check.

ADR-034's consequence list fixes the file's shape ("``config/tools.yaml`` grows
a per-server block: ``{server_id: {kind, command|base_url, version_pin,
credential_env, operations: {name: {read_only, timeout_s, params_ref}}}}``") and
its authority ("an MCP tool is callable IFF it appears in ``config/tools.yaml``
... AND has a permission row"). This loader is the only thing that reads it, so
every fail-closed rule is pinned here — including the one that matters most in
practice: a permission grant naming a tool or operation no configured adapter
exposes must fail STARTUP, not resolve to a confusing default-deny at 3am.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sunil.core.permissions.registry import PermissionRegistry, load_permissions
from sunil.core.tool_framework.base import AdapterKind
from sunil.core.tool_framework.tools_config import (
    ToolsConfigError,
    cross_validate_permissions,
    load_tools_config,
)

REPO_ROOT = Path(__file__).resolve().parents[6]
GOOD_BLOCK = """\
version: 1
tools:
  github_mcp:
    kind: mcp_stdio
    display_name: GitHub MCP
    command: [npx, -y, "@modelcontextprotocol/server-github@0.6.2"]
    version: 0.6.2
    credential_env: [GITHUB_TOKEN]
    operations:
      issues_close:
        read_only: false
        timeout_s: 30
        params_ref: sunil.tools.mcp.params:IssuesCloseParams
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "tools.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_loads_a_stdio_server_block_with_sunil_owned_operation_metadata(tmp_path) -> None:
    config = load_tools_config(_write(tmp_path, GOOD_BLOCK))

    block = config.tools["github_mcp"]
    assert block.kind is AdapterKind.MCP_STDIO
    assert block.command == ["npx", "-y", "@modelcontextprotocol/server-github@0.6.2"]
    assert block.version == "0.6.2"
    assert block.credential_env == ("GITHUB_TOKEN",)
    operation = block.operations["issues_close"]
    assert (operation.read_only, operation.timeout_s) == (False, 30.0)
    assert operation.params_model.model_config["extra"] == "forbid"


@pytest.mark.parametrize(
    "text,message",
    [
        ("version: 2\ntools: {}\n", "expected version: 1"),
        ("version: 1\ntools: []\n", "'tools' must be a mapping"),
        ("version: 1\ntools:\n  x:\n    kind: telepathy\n", "unknown kind"),
        (
            GOOD_BLOCK.replace(
                '    command: [npx, -y, "@modelcontextprotocol/server-github@0.6.2"]\n', ""
            ),
            "requires a non-empty command",
        ),
        (
            GOOD_BLOCK.replace("    version: 0.6.2\n", ""),
            "requires a pinned version",
        ),
        (
            GOOD_BLOCK.replace("kind: mcp_stdio", "kind: mcp_http"),
            "requires base_url_env",
        ),
        (
            "version: 1\ntools:\n  x:\n    kind: native\n",
            "must declare operations",
        ),
        (
            GOOD_BLOCK.replace("sunil.tools.mcp.params:IssuesCloseParams", "nope"),
            "params_ref",
        ),
        (
            GOOD_BLOCK.replace(
                "sunil.tools.mcp.params:IssuesCloseParams",
                "sunil.tools.mcp.params:NOT_A_MODEL",
            ),
            "params_ref",
        ),
        (GOOD_BLOCK.replace("timeout_s: 30", "timeout_s: 0"), "timeout_s"),
        (GOOD_BLOCK.replace("read_only: false", "read_only: sometimes"), "read_only"),
    ],
)
def test_refuses_a_malformed_block(tmp_path, text, message) -> None:
    with pytest.raises(ToolsConfigError, match=message):
        load_tools_config(_write(tmp_path, text))


def test_a_params_model_that_forgets_extra_forbid_is_refused(tmp_path) -> None:
    """C1 §2 — every ``params_model`` uses ``extra="forbid"``. A model that
    accepts unknown keys would let a plan smuggle arguments past the validation
    the ``args_hash`` is computed over, so the loader refuses it rather than the
    first call discovering it."""
    text = GOOD_BLOCK.replace(
        "sunil.tools.mcp.params:IssuesCloseParams",
        "tests.unit.core.tool_framework.test_tools_config:OpenModel",
    )

    with pytest.raises(ToolsConfigError, match='extra="forbid"'):
        load_tools_config(_write(tmp_path, text))


def test_missing_file_is_an_error(tmp_path) -> None:
    with pytest.raises(ToolsConfigError, match="not found"):
        load_tools_config(tmp_path / "absent.yaml")


def test_cross_validation_rejects_a_grant_for_an_unconfigured_operation(tmp_path) -> None:
    config = load_tools_config(_write(tmp_path, GOOD_BLOCK))
    registry = PermissionRegistry(
        {"project_manager": {"github_mcp": {"repos_delete": "allow"}}}
    )

    with pytest.raises(ToolsConfigError, match="repos_delete"):
        cross_validate_permissions(config, registry)


def test_cross_validation_rejects_a_grant_for_an_unknown_tool(tmp_path) -> None:
    config = load_tools_config(_write(tmp_path, GOOD_BLOCK))
    registry = PermissionRegistry({"project_manager": {"gmail_mcp": {"send": "allow"}}})

    with pytest.raises(ToolsConfigError, match="gmail_mcp"):
        cross_validate_permissions(config, registry)


def test_cross_validation_passes_for_the_shipped_pair() -> None:
    """The two files as committed agree with each other — the check the spine's
    startup will run, run here so a config PR cannot land red."""
    config = load_tools_config(REPO_ROOT / "config" / "tools.yaml")
    registry = load_permissions(REPO_ROOT / "config" / "permissions.yaml")

    cross_validate_permissions(config, registry)


def test_the_shipped_config_declares_all_three_adapter_kinds() -> None:
    config = load_tools_config(REPO_ROOT / "config" / "tools.yaml")

    assert config.tools["github"].kind is AdapterKind.NATIVE
    assert config.tools["github_mcp"].kind is AdapterKind.MCP_STDIO
    assert config.tools["n8n_mcp"].kind is AdapterKind.MCP_HTTP
    # C1 §5 — pinned identity: a stdio server pins a version, an HTTP one names
    # the settings field its base URL comes from (never a literal URL in config,
    # which would bypass the ADR-033 validator).
    assert config.tools["github_mcp"].version
    assert config.tools["n8n_mcp"].base_url_env == "SUNIL_N8N_MCP_BASE_URL"
    assert config.tools["n8n_mcp"].auth_token_env == "SUNIL_N8N_MCP_AUTH_TOKEN"
    # No secret VALUES in config — only env-variable names (C1 §5).
    assert config.tools["github_mcp"].credential_env == ("GITHUB_TOKEN",)


def test_the_shipped_config_names_no_secret_values() -> None:
    text = (REPO_ROOT / "config" / "tools.yaml").read_text(encoding="utf-8")

    for marker in ("ghp_", "sk-", "Bearer ", "password:"):
        assert marker not in text


class OpenModel(__import__("pydantic").BaseModel):
    """Intentionally missing ``extra="forbid"`` — the loader must refuse it."""

    anything: str = "x"
