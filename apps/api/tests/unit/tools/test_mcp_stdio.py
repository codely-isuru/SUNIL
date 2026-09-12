"""Unit tests — the MCP stdio adapter, against a REAL child process.

Everything here spawns ``tests/unit/tools/fixtures/mcp_stub_server.py`` with the
production adapter's own spawn path, because the properties under test are the
ones a mocked transport cannot show: a real handshake over real pipes, the
minimal child environment of C1 §5, ``tools/list`` drift failing STARTUP rather
than first call (ADR-034 decision 2), and a dead child mapping to
``transport_error`` rather than an exception escaping the adapter.

No network, no npx, no MCP SDK: the stub is plain stdlib Python, so these tests
run in CI in well under a second.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from pydantic import BaseModel, SecretStr

from sunil.core.tool_framework.base import (
    AdapterKind,
    ToolAdapter,
    ToolAdapterStartupError,
    ToolErrorKind,
)
from sunil.tools.mcp.config import McpOperationConfig
from sunil.tools.mcp.protocol import MCP_PROTOCOL_VERSION
from sunil.tools.mcp.stdio import McpStdioAdapter

STUB = Path(__file__).with_name("fixtures") / "mcp_stub_server.py"


class _Settings(BaseModel):
    github_token: SecretStr = SecretStr("stub-child-token")


class EchoParams(BaseModel, extra="forbid"):
    text: str


class NoParams(BaseModel, extra="forbid"):
    pass


def _operations(*names: str) -> dict[str, McpOperationConfig]:
    table = {
        "echo": McpOperationConfig(
            name="echo", params_model=EchoParams, read_only=True, timeout_s=10.0
        ),
        "env_dump": McpOperationConfig(
            name="env_dump", params_model=NoParams, read_only=True, timeout_s=10.0
        ),
        "big": McpOperationConfig(
            name="big", params_model=NoParams, read_only=True, timeout_s=10.0
        ),
        "sneaky": McpOperationConfig(
            name="sneaky", params_model=NoParams, read_only=True, timeout_s=10.0
        ),
    }
    return {name: table[name] for name in names}


def _adapter(*stub_args: str, operations=None, **kwargs) -> McpStdioAdapter:
    return McpStdioAdapter(
        server_id="github_mcp",
        command=[sys.executable, str(STUB), *stub_args],
        credential_env=["GITHUB_TOKEN"],
        settings=_Settings(),
        operations=operations if operations is not None else _operations("echo", "env_dump"),
        **kwargs,
    )


async def test_identity_is_the_config_key_and_the_kind_is_mcp_stdio() -> None:
    """ADR-034 mapping — the SERVER is the permission-matrix tool, so
    ``name`` is its config key and ``server_id`` is the same value (that is what
    lands on the audit row)."""
    adapter = _adapter()

    assert adapter.name == "github_mcp"
    assert adapter.server_id == "github_mcp"
    assert adapter.kind is AdapterKind.MCP_STDIO
    witness: ToolAdapter = adapter  # structural conformance to C1 §2
    assert set(witness.operations) == {"echo", "env_dump"}


async def test_operations_come_from_sunil_config_not_from_the_server() -> None:
    """ADR-034 decision 2 — the stub advertises four tools; only the two this
    adapter is configured with exist to SUNIL, and their ``read_only``/
    ``timeout_s`` are SUNIL's values even though the stub's ``echo`` claims
    ``readOnlyHint: false``."""
    adapter = _adapter()
    await adapter.start()
    try:
        assert set(adapter.operations) == {"echo", "env_dump"}
        assert adapter.operations["echo"].read_only is True
        assert adapter.operations["echo"].timeout_s == 10.0
    finally:
        await adapter.stop()


async def test_a_real_handshake_then_a_real_tool_call_returns_the_payload() -> None:
    adapter = _adapter()
    await adapter.start()
    try:
        result = await adapter.operations["echo"].handler(EchoParams(text="hello"))
    finally:
        await adapter.stop()

    assert result.ok is True
    assert result.data == {"echo": "hello"}
    assert result.meta.adapter_kind is AdapterKind.MCP_STDIO
    assert result.meta.server_id == "github_mcp"


async def test_the_child_env_holds_the_named_credential_and_no_sunil_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C1 §5's second named test (``docs/tasks/P0-fakes.md``): a spawned child's
    env contains exactly the named variables (plus the documented bootstrap
    names) and nothing else. Asserted from INSIDE the child, which is the only
    place the answer is authoritative."""
    monkeypatch.setenv("SUNIL_SERVICE_TOKEN", "must-not-travel")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "must-not-travel-either")

    adapter = _adapter()
    await adapter.start()
    try:
        result = await adapter.operations["env_dump"].handler(NoParams())
    finally:
        await adapter.stop()

    names = {name.upper() for name in result.data["env_names"]}
    assert "GITHUB_TOKEN" in names
    assert "SUNIL_SERVICE_TOKEN" not in names
    assert "ANTHROPIC_API_KEY" not in names
    from sunil.tools.mcp.credentials import BOOTSTRAP_ENV_NAMES

    # Upper-cased on both sides: Windows' os.environ upper-cases its keys, so a
    # case-sensitive comparison would compare spellings, not contents.
    assert names <= {"GITHUB_TOKEN", *(name.upper() for name in BOOTSTRAP_ENV_NAMES)}


async def test_startup_fails_when_a_configured_operation_is_absent_upstream() -> None:
    """ADR-034 decision 2's drift check: "a configured operation missing from
    the live server fails startup for that adapter". Version drift becomes
    visible at startup, not at first call in production."""
    adapter = _adapter("--omit", "env_dump")

    with pytest.raises(ToolAdapterStartupError, match="env_dump"):
        await adapter.start()

    await adapter.stop()


async def test_an_advertised_but_unconfigured_tool_is_logged_and_ignored(
    caplog: pytest.LogCaptureFixture,
) -> None:
    adapter = _adapter("--extra-tool", "repos_delete")

    with caplog.at_level(logging.INFO, logger="sunil.tools.mcp.adapter"):
        await adapter.start()
    try:
        assert "repos_delete" not in adapter.operations
        assert any("repos_delete" in record.getMessage() for record in caplog.records)
        # ADR-034 decision 3 — annotations are recorded for the human who
        # maintains config, and nothing else reads them.
        assert any("readOnlyHint" in record.getMessage() for record in caplog.records)
    finally:
        await adapter.stop()


async def test_startup_fails_on_a_protocol_revision_the_adapter_does_not_pin() -> None:
    adapter = _adapter("--protocol-version", "1999-01-01")

    with pytest.raises(ToolAdapterStartupError, match=MCP_PROTOCOL_VERSION):
        await adapter.start()

    await adapter.stop()


async def test_startup_fails_when_a_named_credential_is_missing_from_settings() -> None:
    """C1 §5 — at WIRING time, never a KeyError at call time. The failure must
    happen before anything is spawned: a tool that cannot start is absent from
    the registry, never half-present."""
    adapter = McpStdioAdapter(
        server_id="github_mcp",
        command=[sys.executable, str(STUB)],
        credential_env=["NO_SUCH_TOKEN"],
        settings=_Settings(),
        operations=_operations("echo"),
    )

    with pytest.raises(ToolAdapterStartupError, match="NO_SUCH_TOKEN"):
        await adapter.start()


async def test_a_server_error_result_maps_to_upstream_error() -> None:
    """C1 §4 — "MCP error result" → ``upstream_error`` (executed and failed),
    which policy does NOT auto-retry."""
    adapter = _adapter("--fail-tool", "echo")
    await adapter.start()
    try:
        result = await adapter.operations["echo"].handler(EchoParams(text="hi"))
    finally:
        await adapter.stop()

    assert result.ok is False
    assert result.error_kind == ToolErrorKind.UPSTREAM_ERROR
    assert result.data is None


async def test_a_jsonrpc_error_object_maps_to_upstream_error() -> None:
    adapter = _adapter("--rpc-error", "echo")
    await adapter.start()
    try:
        result = await adapter.operations["echo"].handler(EchoParams(text="hi"))
    finally:
        await adapter.stop()

    assert result.error_kind == ToolErrorKind.UPSTREAM_ERROR


async def test_a_dead_child_maps_to_transport_error_not_an_exception() -> None:
    """C1 §4 — "a dead stdio child ... maps to ``transport_error``" (retryable by
    policy). C1 §2: an adapter exception never reaches the orchestrator as an
    exception."""
    adapter = _adapter("--die-on", "echo")
    await adapter.start()
    try:
        result = await adapter.operations["echo"].handler(EchoParams(text="hi"))
    finally:
        await adapter.stop()

    assert result.ok is False
    assert result.error_kind == ToolErrorKind.TRANSPORT_ERROR


async def test_calling_before_start_is_a_transport_error_not_a_crash() -> None:
    adapter = _adapter()

    result = await adapter.operations["echo"].handler(EchoParams(text="hi"))

    assert result.error_kind == ToolErrorKind.TRANSPORT_ERROR


async def test_stop_is_idempotent_and_safe_before_start() -> None:
    adapter = _adapter()

    await adapter.stop()
    await adapter.start()
    await adapter.stop()
    await adapter.stop()
