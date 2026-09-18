"""ADR-034 Amendment 1 — `server_tool:` bindings, and what they must NOT let in.

R16 part 3's naming law: SUNIL's operation names are the governed vocabulary —
permission rows, approval cards, audit history, ADR-030 §4's own text — and they
never track a vendor. The binding is the seam that absorbs a vendor rename, and
this module is where it is pinned:

* default binding = the operation name (so nothing existing moves);
* the drift check verifies the BINDINGS, not the operation names;
* `tools/call` is sent with the bound name;
* `fixed_arguments:` are adapter-supplied constants a plan cannot reach, and a
  fixed argument that could OVERWRITE a params field is refused by the loader —
  because the `args_hash` an approval binds to is computed over the params model,
  so "the owner approved closing issue 42" must not be rewritable from config.

The corrected `issues_close` binding this exists for (capture 2026-09-16,
`docs/tasks/S3-github.md` §0): `update_issue` does not exist on the official
server; `issue_write(method=update, state=closed)` is the live verb.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from sunil.core.tool_framework.base import AdapterKind, ToolAdapterStartupError
from sunil.core.tool_framework.tools_config import ToolsConfigError, load_tools_config
from sunil.tools.mcp.adapter import McpToolAdapter
from sunil.tools.mcp.params import IssuesCloseParams
from sunil.tools.mcp.protocol import MCP_PROTOCOL_VERSION

BOUND_BLOCK = """\
version: 1
tools:
  github_mcp:
    kind: mcp_stdio
    display_name: GitHub MCP
    command: [docker, run, "-i", "--rm", ghcr.io/github/github-mcp-server@sha256:abc]
    version: v1.12.2
    credential_env: [GITHUB_TOKEN]
    operations:
      issues_close:
        read_only: false
        timeout_s: 30
        server_tool: issue_write
        fixed_arguments: {method: update, state: closed}
        params_ref: sunil.tools.mcp.params:IssuesCloseParams
      issues_list:
        read_only: true
        timeout_s: 30
        params_ref: sunil.tools.mcp.params:IssuesListParams
"""


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "tools.yaml"
    path.write_text(text, encoding="utf-8")
    return path


class _RecordingTransport:
    """Answers the handshake, then records every `tools/call` it is sent."""

    def __init__(self, advertised: list[str], *, result: Any = None) -> None:
        self._advertised = advertised
        self._result = result if result is not None else {"content": []}
        self.calls: list[dict[str, Any]] = []

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def notify(self, method: str, params: dict[str, Any]) -> None: ...

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return {"protocolVersion": MCP_PROTOCOL_VERSION}
        if method == "tools/list":
            return {"tools": [{"name": name} for name in self._advertised]}
        if method == "tools/call":
            self.calls.append(params)
            return self._result
        raise AssertionError(f"unexpected method {method!r}")


def _adapter(block_operations, transport) -> McpToolAdapter:
    return McpToolAdapter(
        server_id="github_mcp",
        kind=AdapterKind.MCP_STDIO,
        operations=block_operations,
        transport=transport,
    )


def test_an_operation_with_no_server_tool_binds_to_its_own_name(tmp_path) -> None:
    """The default keeps every pre-Amendment row meaning what it meant —
    `n8n_mcp.post_update` is not edited by this change."""
    config = load_tools_config(_write(tmp_path, BOUND_BLOCK))

    operation = config.tools["github_mcp"].operations["issues_list"]
    assert operation.server_tools == ("issues_list",)
    assert operation.fixed_arguments == {}


def test_a_scalar_server_tool_is_the_one_bound_verb(tmp_path) -> None:
    config = load_tools_config(_write(tmp_path, BOUND_BLOCK))

    operation = config.tools["github_mcp"].operations["issues_close"]
    assert operation.name == "issues_close"
    assert operation.server_tools == ("issue_write",)
    assert operation.fixed_arguments == {"method": "update", "state": "closed"}


async def test_the_drift_check_verifies_the_binding_not_the_operation_name() -> None:
    """The point of the whole amendment: a server that advertises `issue_write`
    and has never heard of `issues_close` must satisfy the drift check."""
    config = load_tools_config(
        _write(Path(__import__("tempfile").mkdtemp()), BOUND_BLOCK)
    )
    operations = config.tools["github_mcp"].operations
    transport = _RecordingTransport(["issue_write", "issues_list", "get_me"])

    await _adapter(operations, transport).start()  # must not raise


async def test_an_unadvertised_BINDING_refuses_start_and_names_the_server_verb() -> None:
    """R16's whole-tool consequence, now measured against the bound name: the
    operation is configured, but nothing serves what it is bound to."""
    config = load_tools_config(
        _write(Path(__import__("tempfile").mkdtemp()), BOUND_BLOCK)
    )
    operations = config.tools["github_mcp"].operations
    # `issues_close` advertised (the SUNIL name!) but `issue_write` absent.
    transport = _RecordingTransport(["issues_close", "issues_list"])

    with pytest.raises(ToolAdapterStartupError) as caught:
        await _adapter(operations, transport).start()

    assert "issue_write" in str(caught.value)


async def test_the_call_goes_out_under_the_bound_name_with_the_fixed_arguments() -> None:
    config = load_tools_config(
        _write(Path(__import__("tempfile").mkdtemp()), BOUND_BLOCK)
    )
    operations = config.tools["github_mcp"].operations
    transport = _RecordingTransport(["issue_write", "issues_list"])
    adapter = _adapter(operations, transport)
    await adapter.start()

    result = await adapter.operations["issues_close"].handler(
        IssuesCloseParams(owner="codely-isuru", repo="SUNIL", issue_number=42)
    )

    assert result.ok is True
    assert transport.calls == [
        {
            "name": "issue_write",
            "arguments": {
                "owner": "codely-isuru",
                "repo": "SUNIL",
                "issue_number": 42,
                "method": "update",
                "state": "closed",
            },
        }
    ]


def test_a_fixed_argument_that_could_overwrite_a_params_field_is_refused(tmp_path) -> None:
    """The `args_hash` is computed over the params model. A fixed argument named
    `issue_number` would let a config edit rewrite what the owner approved, with
    the approval card still reading "close issue 42"."""
    bad = BOUND_BLOCK.replace(
        "fixed_arguments: {method: update, state: closed}",
        "fixed_arguments: {method: update, issue_number: 1}",
    )

    with pytest.raises(ToolsConfigError) as caught:
        load_tools_config(_write(tmp_path, bad))

    assert "issue_number" in str(caught.value)


def test_an_empty_server_tool_binding_is_refused(tmp_path) -> None:
    """`server_tool: []` would bind an operation to nothing at all, which the
    drift check would then pass vacuously — the exact shape R16 forbids."""
    bad = BOUND_BLOCK.replace("server_tool: issue_write", "server_tool: []")

    with pytest.raises(ToolsConfigError):
        load_tools_config(_write(tmp_path, bad))
