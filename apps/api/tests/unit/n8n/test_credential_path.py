"""The n8n mount's TOKEN comes through the C-3 door, like every other one.

`auth_token_env:` on an `mcp_http` block looks like a different mechanism from
`credential_env:` on a stdio block, and the whole value of Security wave-1's
condition C-3 depends on it not being one: `core/tool_framework/wiring.py`
resolves both through `tools/mcp/credentials._settings_value`, so the frozen
`GRANTABLE_CREDENTIAL_NAMES` allowlist bounds what `config/tools.yaml` can ask
for on either lane.

`tests/unit/tools/test_mcp_credentials.py` pins the allowlist itself. What is
pinned HERE is the n8n block's journey through it: the repository's own config,
built by the production builder, against a `Settings` double.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from sunil.core.tool_framework.base import AdapterKind
from sunil.core.tool_framework.tools_config import load_tools_config
from sunil.core.tool_framework.wiring import build_adapters
from sunil.tools.mcp.credentials import GRANTABLE_CREDENTIAL_NAMES

REPO_ROOT = Path(__file__).resolve().parents[5]
TOOLS_YAML = REPO_ROOT / "config" / "tools.yaml"
MCP_TOKEN = "n8n-mcp-token-not-a-real-secret"
SERVICE_TOKEN = "service-token-not-a-real-secret"
SESSION_SECRET = "session-secret-not-a-real-secret"


def _settings(**overrides):
    """A `Settings` double carrying SUNIL's own secrets alongside the tool's.

    The point of the test is that the other three are REACHABLE by attribute and
    still refused — an allowlist that only works because the field is absent is
    not an allowlist.
    """
    values = {
        "sunil_n8n_mcp_base_url": "http://localhost:5680/mcp/sunil",
        "sunil_n8n_mcp_auth_token": SecretStr(MCP_TOKEN),
        "sunil_service_token": SecretStr(SERVICE_TOKEN),
        "session_secret": SecretStr(SESSION_SECRET),
        "database_url": "postgresql+psycopg://sunil:pw@127.0.0.1:5433/sunil",
        "github_token": None,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _n8n_block():
    return load_tools_config(TOOLS_YAML).tools["n8n_mcp"]


def _config_with(block):
    from sunil.core.tool_framework.tools_config import ToolsConfig

    return ToolsConfig(tools={"n8n_mcp": block})


def test_the_n8n_token_is_on_the_grantable_allowlist_by_name() -> None:
    assert _n8n_block().auth_token_env in GRANTABLE_CREDENTIAL_NAMES


def test_the_mount_builds_and_holds_the_token_as_a_secret() -> None:
    adapters, skipped = build_adapters(_config_with(_n8n_block()), settings=_settings())

    assert skipped == []
    assert len(adapters) == 1
    adapter = adapters[0]
    assert adapter.name == "n8n_mcp"
    assert adapter.kind is AdapterKind.MCP_HTTP
    # It survived the journey as a SecretStr — `repr` of the built adapter must
    # not be a way to read the token out of a crash dump or a log line.
    assert MCP_TOKEN not in repr(adapter.__dict__)


@pytest.mark.parametrize(
    "ungrantable",
    ["SUNIL_SERVICE_TOKEN", "SESSION_SECRET", "DATABASE_URL"],
    ids=["service-token", "session-secret", "database-url"],
)
def test_the_mount_cannot_be_pointed_at_one_of_sunils_own_secrets(ungrantable) -> None:
    """The escalation C-3 closed, exercised on the HTTP lane.

    `auth_token_env: SUNIL_SERVICE_TOKEN` in `config/tools.yaml` would hand the
    ADR-035 machine credential to n8n — which already holds a copy of it as a
    workflow credential, and would then be able to mint turns as SUNIL from
    anywhere the token reaches. ADR-016 makes `config/*.yaml` deployment-free
    and mounted, so that is a one-line edit with no code review on its path.

    The refusal must be a SKIP with a named reason, never a half-built adapter:
    the tool is absent, the app still boots, and the startup line says why.
    """
    from dataclasses import replace

    block = replace(_n8n_block(), auth_token_env=ungrantable)

    adapters, skipped = build_adapters(_config_with(block), settings=_settings())

    assert adapters == []
    assert len(skipped) == 1
    server_id, reason = skipped[0]
    assert server_id == "n8n_mcp"
    assert ungrantable in reason
    # The reason is a startup log line; it may name the VARIABLE and must never
    # carry the VALUE (ADR-006).
    for secret in (SERVICE_TOKEN, SESSION_SECRET, MCP_TOKEN):
        assert secret not in reason


def test_an_unset_token_takes_the_tool_out_rather_than_starting_it_open() -> None:
    """"A tool that cannot be built is absent, never half-present" (C1 §5).

    The failure mode this forbids is the tempting one: build the adapter with an
    empty bearer and let the call fail later. n8n answers 403 to an empty
    bearer, so that would surface as an `upstream_error` on a plan at runtime
    instead of a named line at boot.
    """
    adapters, skipped = build_adapters(
        _config_with(_n8n_block()), settings=_settings(sunil_n8n_mcp_auth_token=None)
    )

    assert adapters == []
    assert skipped[0][0] == "n8n_mcp"
    assert "unset" in skipped[0][1]
