"""`config/tools.yaml` → live adapters. The one place a real tool is constructed.

ADR-034 makes the config file the authority ("an MCP tool is callable IFF it
appears in `config/tools.yaml` with an explicit `operations:` entry … AND has a
permission row"), and `tools_config.py` already turns that file into validated
`ToolBlock`s. This module is the next step and the last one: blocks → adapters.

**A tool that cannot be built is absent, never half-present** (C1 §5, and
`docs/tasks/S-A-tools.md` §4's integration requirement: "a failed `start()` must
leave that tool out of the registry"). The reason is returned with the name so
the caller can log it — `api/wiring.py` does, as a WARNING. Two things follow:

* a missing `GITHUB_TOKEN` does not stop the assistant booting. It stops the
  GitHub tools existing, which is the honest consequence and the safe one: the
  chokepoint answers `unknown_operation` and the plan validator rejects the step
  before that;
* the failure is never silent. "The tool is not in the catalogue" and "the tool
  refused the call" look identical from a plan's point of view, hours from the
  cause, and the startup line is what tells them apart.

Secrets: every credential comes through `tools/mcp/credentials.py`, so
`config/tools.yaml` can only name variables on the C-3 grantable allowlist. No
value is read from the environment here — `Settings` is the single env seam.
"""

from __future__ import annotations

import logging
from typing import Any

from sunil.core.tool_framework.base import AdapterKind, ToolAdapterStartupError
from sunil.core.tool_framework.tools_config import ToolBlock, ToolsConfig
from sunil.tools.mcp.credentials import GRANTABLE_CREDENTIAL_NAMES

_LOGGER = logging.getLogger(__name__)


def build_adapters(
    config: ToolsConfig, *, settings: Any
) -> tuple[list[Any], list[tuple[str, str]]]:
    """Construct one adapter per `config/tools.yaml` block.

    Returns `(adapters, skipped)` where `skipped` is `[(server_id, reason), …]`.
    The reason never contains a credential value — a startup line is a place a
    secret must not reach (ADR-006).
    """
    adapters: list[Any] = []
    skipped: list[tuple[str, str]] = []
    for server_id, block in config.tools.items():
        try:
            adapters.append(_build_one(block, settings=settings))
        except ToolAdapterStartupError as exc:
            skipped.append((server_id, str(exc)))
        except Exception as exc:  # noqa: BLE001 — one bad tool must not take the app down
            skipped.append((server_id, f"{type(exc).__name__}: {exc}"))
    return adapters, skipped


def _build_one(block: ToolBlock, *, settings: Any) -> Any:
    if block.kind is AdapterKind.NATIVE:
        return _native(block, settings=settings)
    if block.kind is AdapterKind.MCP_STDIO:
        from sunil.tools.mcp.stdio import McpStdioAdapter  # noqa: PLC0415

        # Resolved eagerly so an ungrantable or unset credential is a WIRING-time
        # skip with a named reason, rather than a spawn that dies at first call.
        for name in block.credential_env:
            _require_credential(name, settings=settings)
        return McpStdioAdapter(
            server_id=block.server_id,
            command=list(block.command or ()),
            operations=block.operations,
            credential_env=block.credential_env,
            settings=settings,
        )
    if block.kind is AdapterKind.MCP_HTTP:
        from sunil.tools.mcp.http import McpHttpAdapter  # noqa: PLC0415

        return McpHttpAdapter(
            server_id=block.server_id,
            base_url=_settings_url(block.base_url_env, settings=settings),
            auth_token=_require_credential(block.auth_token_env, settings=settings),
            operations=block.operations,
        )
    raise ToolAdapterStartupError(f"{block.server_id}: unsupported kind {block.kind!r}")


def _native(block: ToolBlock, *, settings: Any) -> Any:
    """The native adapters, by name. Native tools are CODE, not configuration:
    each one is a module with its own parameters and its own upstream, so there
    is no generic constructor to dispatch to — and a `config/tools.yaml` entry
    naming a native tool SUNIL does not implement is a config error, not a tool.
    """
    if block.server_id != "github":
        raise ToolAdapterStartupError(
            f"{block.server_id}: no native adapter of that name is implemented"
        )
    from sunil.tools.github.adapter import build_github_adapter  # noqa: PLC0415

    token = getattr(settings, "github_token", None)
    if token is None or not token.get_secret_value():
        raise ToolAdapterStartupError(
            "github: GITHUB_TOKEN is unset — the native GitHub tool reads a real "
            "API on the owner's behalf and cannot be half-configured"
        )
    projects = _project_repos(settings)
    if not projects:
        raise ToolAdapterStartupError(
            "github: no project in config/projects.yaml declares `repo: owner/name`, "
            "so every call would resolve to an unknown project. The repo mapping is "
            "config, never a plan parameter (M1 T-16)"
        )
    return build_github_adapter(settings=settings, projects=projects)


def _project_repos(settings: Any) -> dict[str, tuple[str, str]]:
    """`config/projects.yaml` → `{project_key: (owner, repo)}`.

    Read here rather than taken from the plan: the operation's only parameter is
    `project_key`, precisely so a plan cannot choose which repository SUNIL
    touches (M1's T-16 rule, ported with the adapter).
    """
    from pathlib import Path  # noqa: PLC0415

    from sunil.core.registry.loader import load_registries  # noqa: PLC0415

    registries = load_registries(Path(settings.sunil_config_dir))
    repos: dict[str, tuple[str, str]] = {}
    for key, project in registries.projects.items():
        repo = getattr(project, "repo", None)
        if repo and "/" in repo:
            owner, _, name = repo.partition("/")
            repos[key] = (owner, name)
    return repos


def _require_credential(name: str | None, *, settings: Any):
    """One door for every tool credential — `tools/mcp/credentials.py`, so the
    C-3 grantable allowlist applies to the HTTP lane's `auth_token_env` exactly
    as it does to a stdio child's `credential_env`."""
    from pydantic import SecretStr  # noqa: PLC0415

    from sunil.tools.mcp.credentials import _settings_value  # noqa: PLC0415

    if not name:
        raise ToolAdapterStartupError("a credential variable name is required")
    if name not in GRANTABLE_CREDENTIAL_NAMES:
        raise ToolAdapterStartupError(
            f"{name!r} is not grantable to a tool (THREAT_MODEL §9 condition C-3)"
        )
    return SecretStr(_settings_value(settings, name))


def _settings_url(name: str | None, *, settings: Any) -> str:
    """A `*_base_url_env` entry names a `Settings` FIELD, never a literal URL —
    so the ADR-033 loopback-or-named-host validator on `Settings` has already
    seen the value by the time an adapter gets it."""
    if not name:
        raise ToolAdapterStartupError("base_url_env is required for an mcp_http tool")
    value = getattr(settings, name.lower(), None)
    if not isinstance(value, str) or not value:
        raise ToolAdapterStartupError(
            f"base_url_env names {name!r}, but settings.{name.lower()} is unset"
        )
    return value
