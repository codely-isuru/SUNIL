"""Unit tests — the MCP streamable-HTTP adapter (TB5: the n8n MCP server).

Driven through ``httpx.MockTransport``, so the production request path runs for
real (headers, session id, SSE framing, status mapping) with no network and no
n8n container — the ADR-017 test-seam pattern M1 used for the GitHub tool.

The properties pinned here are the ones that differ from stdio: the auth header
comes from settings and never from a tool argument, the MCP session id returned
by ``initialize`` is carried on every later request, a streamable
``text/event-stream`` reply is parsed, and an HTTP failure maps onto C1 §4's
closed set (reached-and-failed → ``upstream_error``; could-not-reach →
``transport_error``, the only one policy may auto-retry).
"""

from __future__ import annotations

import json

import httpx
import pytest
from pydantic import BaseModel, SecretStr

from sunil.core.tool_framework.base import (
    AdapterKind,
    ToolAdapter,
    ToolAdapterStartupError,
    ToolErrorKind,
)
from sunil.tools.mcp.config import McpOperationConfig
from sunil.tools.mcp.http import McpHttpAdapter
from sunil.tools.mcp.protocol import MCP_PROTOCOL_VERSION

BASE_URL = "http://localhost:5680/mcp"
SESSION_ID = "sess-42"


class RunWorkflowParams(BaseModel, extra="forbid"):
    workflow: str


OPERATIONS = {
    "run_workflow": McpOperationConfig(
        name="run_workflow",
        params_model=RunWorkflowParams,
        read_only=False,
        timeout_s=30.0,
    )
}


class _Server:
    """A scripted MCP-over-HTTP server. Records every request it received."""

    def __init__(
        self,
        *,
        tools: list[str] | None = None,
        sse: bool = False,
        status: int | None = None,
        connect_error: bool = False,
        protocol_version: str = MCP_PROTOCOL_VERSION,
    ) -> None:
        self.requests: list[httpx.Request] = []
        self._tools = ["run_workflow"] if tools is None else tools
        self._sse = sse
        self._status = status
        self._connect_error = connect_error
        self._protocol_version = protocol_version

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        body = json.loads(request.content)
        method = body.get("method")
        if method == "notifications/initialized":
            return httpx.Response(202)
        if self._connect_error:
            raise httpx.ConnectError("connection refused", request=request)
        if self._status is not None and method == "tools/call":
            return httpx.Response(self._status, text="upstream exploded")

        if method == "initialize":
            result = {
                "protocolVersion": self._protocol_version,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "n8n", "version": "1.0"},
            }
            return self._reply(body["id"], result, headers={"Mcp-Session-Id": SESSION_ID})
        if method == "tools/list":
            result = {
                "tools": [
                    {"name": name, "inputSchema": {"type": "object"}} for name in self._tools
                ]
            }
            return self._reply(body["id"], result)
        if method == "tools/call":
            result = {"structuredContent": {"ran": body["params"]["arguments"]["workflow"]}}
            return self._reply(body["id"], result)
        return httpx.Response(400, text=f"unexpected method {method!r}")

    def _reply(self, request_id, result, headers=None) -> httpx.Response:
        payload = {"jsonrpc": "2.0", "id": request_id, "result": result}
        if self._sse:
            return httpx.Response(
                200,
                headers={"content-type": "text/event-stream", **(headers or {})},
                text=f"event: message\ndata: {json.dumps(payload)}\n\n",
            )
        return httpx.Response(200, json=payload, headers=headers or {})


def _adapter(server: _Server, **kwargs) -> McpHttpAdapter:
    client = httpx.AsyncClient(transport=httpx.MockTransport(server))
    return McpHttpAdapter(
        server_id="n8n_mcp",
        base_url=kwargs.pop("base_url", BASE_URL),
        auth_token=kwargs.pop("auth_token", SecretStr("n8n-secret-token")),
        operations=OPERATIONS,
        client=client,
        **kwargs,
    )


async def test_identity_and_kind() -> None:
    adapter = _adapter(_Server())

    assert (adapter.name, adapter.server_id) == ("n8n_mcp", "n8n_mcp")
    assert adapter.kind is AdapterKind.MCP_HTTP
    witness: ToolAdapter = adapter
    assert set(witness.operations) == {"run_workflow"}


async def test_handshake_then_call_returns_the_structured_payload() -> None:
    server = _Server()
    adapter = _adapter(server)
    await adapter.start()
    try:
        result = await adapter.operations["run_workflow"].handler(
            RunWorkflowParams(workflow="deploy")
        )
    finally:
        await adapter.stop()

    assert result.ok is True
    assert result.data == {"ran": "deploy"}
    assert result.meta.adapter_kind is AdapterKind.MCP_HTTP
    assert result.meta.server_id == "n8n_mcp"


async def test_every_request_carries_the_auth_header_and_the_pinned_revision() -> None:
    server = _Server()
    adapter = _adapter(server)
    await adapter.start()
    try:
        await adapter.operations["run_workflow"].handler(RunWorkflowParams(workflow="x"))
    finally:
        await adapter.stop()

    assert server.requests
    for request in server.requests:
        assert request.headers["authorization"] == "Bearer n8n-secret-token"
        assert "application/json" in request.headers["accept"]
        assert "text/event-stream" in request.headers["accept"]
    # The session id from `initialize` travels on every LATER request — without
    # it a streamable-HTTP server answers 400 and every call after the handshake
    # fails for a reason that looks like a protocol bug.
    assert "mcp-session-id" not in server.requests[0].headers
    assert server.requests[-1].headers["mcp-session-id"] == SESSION_ID
    assert server.requests[-1].headers["mcp-protocol-version"] == MCP_PROTOCOL_VERSION


async def test_a_server_sent_events_reply_is_parsed() -> None:
    adapter = _adapter(_Server(sse=True))
    await adapter.start()
    try:
        result = await adapter.operations["run_workflow"].handler(
            RunWorkflowParams(workflow="sse")
        )
    finally:
        await adapter.stop()

    assert result.data == {"ran": "sse"}


@pytest.mark.parametrize("status", [500, 502, 401, 404])
async def test_an_http_failure_maps_to_upstream_error_and_never_leaks_the_token(
    status: int,
) -> None:
    """C1 §4 — "HTTP 5xx" is ``upstream_error`` (reached and failed, not
    auto-retried). A 4xx is the same class: the server WAS reached, and marking
    a 401 retryable would have SUNIL hammer a misconfigured endpoint."""
    adapter = _adapter(_Server(status=status))
    await adapter.start()
    try:
        result = await adapter.operations["run_workflow"].handler(
            RunWorkflowParams(workflow="x")
        )
    finally:
        await adapter.stop()

    assert result.ok is False
    assert result.error_kind == ToolErrorKind.UPSTREAM_ERROR
    assert "n8n-secret-token" not in (result.error_message or "")


async def test_an_unreachable_server_maps_to_transport_error() -> None:
    server = _Server()
    adapter = _adapter(server)
    await adapter.start()
    server._connect_error = True  # noqa: SLF001 - scripted double
    try:
        result = await adapter.operations["run_workflow"].handler(
            RunWorkflowParams(workflow="x")
        )
    finally:
        await adapter.stop()

    assert result.error_kind == ToolErrorKind.TRANSPORT_ERROR


async def test_startup_drift_check_applies_over_http_too() -> None:
    adapter = _adapter(_Server(tools=["something_else"]))

    with pytest.raises(ToolAdapterStartupError, match="run_workflow"):
        await adapter.start()

    await adapter.stop()


async def test_startup_fails_on_a_protocol_revision_mismatch() -> None:
    adapter = _adapter(_Server(protocol_version="2024-11-05"))

    with pytest.raises(ToolAdapterStartupError, match=MCP_PROTOCOL_VERSION):
        await adapter.start()

    await adapter.stop()


async def test_an_unreachable_server_fails_startup_rather_than_half_starting() -> None:
    adapter = _adapter(_Server(connect_error=True))

    with pytest.raises(ToolAdapterStartupError):
        await adapter.start()


@pytest.mark.parametrize("base_url", ["ftp://localhost/mcp", "localhost:5680/mcp", ""])
async def test_a_non_http_base_url_is_refused_at_construction(base_url: str) -> None:
    """The ADR-033 host validator lives on ``Settings`` (spine lane); this is the
    adapter's own floor, so a misconfigured block cannot produce an adapter that
    would try to speak MCP over something that is not HTTP."""
    with pytest.raises(ToolAdapterStartupError, match="base_url"):
        _adapter(_Server(), base_url=base_url)


async def test_a_missing_auth_token_is_refused_at_construction() -> None:
    with pytest.raises(ToolAdapterStartupError, match="auth token"):
        _adapter(_Server(), auth_token=SecretStr(""))
