"""The MCP handshake, replayed from a recording of the live n8n 2.38.5 server.

`fixtures/n8n_2_38_5_mcp.json` is a verbatim capture — status line, content
type, session header and body — of four exchanges against
`infra/n8n/workflows/sunil-mcp-server.json` running on `n8nio/n8n:2.38.5`
(see `docs/tasks/S2-E-n8n.md` §4 for the capture and the auth evidence).

Replaying it through `httpx.MockTransport` runs the PRODUCTION request path —
`McpHttpAdapter` → `StreamableHttpTransport` → the real SSE decoder and the real
ADR-034 drift check — with no container, so CI proves the shape of the server it
will actually meet rather than the shape a hand-written double agrees to.

The one thing a recording cannot prove is that the live endpoint still answers
that way; that is what the startup drift check is for, and it is exercised
against the live server whenever the stack is up.
"""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from sunil.core.tool_framework.base import ToolAdapterStartupError, ToolErrorKind
from sunil.core.tool_framework.tools_config import load_tools_config
from sunil.tools.mcp.http import McpHttpAdapter
from sunil.tools.mcp.protocol import MCP_PROTOCOL_VERSION

REPO_ROOT = Path(__file__).resolve().parents[5]
FIXTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "n8n_2_38_5_mcp.json").read_text(
        encoding="utf-8"
    )
)
BASE_URL = "http://127.0.0.1:5680/mcp/sunil"
TOKEN = SecretStr("recorded-token-not-a-real-secret")


def _reply(recorded: dict) -> httpx.Response:
    headers = {"content-type": recorded["content_type"]}
    if recorded.get("mcp_session_id"):
        headers["mcp-session-id"] = recorded["mcp_session_id"]
    return httpx.Response(recorded["status"], headers=headers, content=recorded["body"])


class _RecordedServer:
    """Answers each JSON-RPC method with the matching recorded reply.

    Also keeps every request it was sent, so the auth header and the session id
    can be asserted on the wire rather than inferred.
    """

    def __init__(self, *, unauthenticated: bool = False) -> None:
        self.requests: list[httpx.Request] = []
        self._unauthenticated = unauthenticated

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self._unauthenticated:
            return _reply(FIXTURE["unauthenticated_initialize"])
        method = json.loads(request.content.decode())["method"]
        return _reply(
            {
                "initialize": FIXTURE["initialize"],
                "notifications/initialized": {
                    "status": 202,
                    "content_type": "text/plain",
                    "mcp_session_id": None,
                    "body": "Accepted",
                },
                "tools/list": FIXTURE["tools_list"],
                "tools/call": FIXTURE["tools_call_post_update"],
            }[method]
        )

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handler))


def _adapter(server: _RecordedServer) -> McpHttpAdapter:
    """The adapter built from the REPOSITORY's own operations — so this test
    fails if `config/tools.yaml` declares an n8n operation the recorded server
    does not advertise (which is exactly what the live drift check would do)."""
    block = load_tools_config(REPO_ROOT / "config" / "tools.yaml").tools["n8n_mcp"]
    return McpHttpAdapter(
        server_id="n8n_mcp",
        base_url=BASE_URL,
        auth_token=TOKEN,
        operations=block.operations,
        client=server.client(),
    )


async def test_the_configured_operations_all_exist_on_the_recorded_server() -> None:
    """ADR-034's drift check, against the shape n8n 2.38.5 really returned.

    A `config/tools.yaml` operation with no tool behind it does not merely fail
    at call time — it takes the WHOLE n8n tool out of the registry, because
    `start()` refuses. That is the fail-closed behaviour, and this is the test
    that stops the config drifting into it unnoticed.
    """
    server = _RecordedServer()
    adapter = _adapter(server)

    await adapter.start()  # raises ToolAdapterStartupError on drift

    await adapter.stop()


async def test_the_recorded_initialize_pins_the_protocol_revision_sunil_speaks() -> None:
    recorded = json.loads(FIXTURE["initialize"]["body"].split("data:", 1)[1].strip())

    assert recorded["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert recorded["result"]["serverInfo"]["name"] == "MCP_Server_Trigger"


async def test_every_request_carries_the_bearer_and_the_session_id() -> None:
    """The token is a header on EVERY request, not just the handshake — n8n
    re-checks it per request (the session id alone is refused; see
    `docs/tasks/S2-E-n8n.md` §4, direction D)."""
    server = _RecordedServer()
    adapter = _adapter(server)

    await adapter.start()
    await adapter.stop()

    assert len(server.requests) >= 3
    for request in server.requests:
        assert request.headers["authorization"] == f"Bearer {TOKEN.get_secret_value()}"
    session_id = FIXTURE["initialize"]["mcp_session_id"]
    assert server.requests[-1].headers["mcp-session-id"] == session_id


async def test_post_update_returns_the_structured_payload_the_workflow_emits() -> None:
    server = _RecordedServer()
    adapter = _adapter(server)
    await adapter.start()

    operation = adapter.operations["post_update"]
    result = await operation.handler(
        operation.params_model(project_key="sunil", summary="Recorded for the CI fixture.")
    )

    assert result.ok is True
    assert result.error_kind is None
    assert result.meta.server_id == "n8n_mcp"
    # The workflow's own JSON, carried through MCP's text content block.
    echoed = json.loads(result.data["content"][0]["text"])
    assert echoed["ok"] is True
    assert echoed["project_key"] == "sunil"
    assert echoed["recorded_by"] == "n8n:sunil-mcp-server"

    await adapter.stop()


async def test_the_recorded_403_takes_the_tool_out_of_the_registry() -> None:
    """A wrong or missing token is a STARTUP failure, never a half-mounted tool.

    This is the client side of the enforcement proof: n8n answers 403 (recorded
    verbatim), and SUNIL's answer to that is to refuse to start the adapter — so
    a misconfigured token surfaces as "the n8n tool is absent" at boot, not as a
    plan that fails at 3am.
    """
    adapter = _adapter(_RecordedServer(unauthenticated=True))

    with pytest.raises(ToolAdapterStartupError) as caught:
        await adapter.start()

    assert "403" in str(caught.value)
    assert TOKEN.get_secret_value() not in str(caught.value)


async def test_a_call_before_start_is_a_transport_error_not_an_unauthenticated_call() -> None:
    """Belt and braces on the same edge: an unstarted adapter must not put the
    bearer on the wire at all."""
    server = _RecordedServer()
    adapter = _adapter(server)

    operation = adapter.operations["post_update"]
    result = await operation.handler(
        operation.params_model(project_key="sunil", summary="before start")
    )

    assert result.ok is False
    assert result.error_kind == ToolErrorKind.TRANSPORT_ERROR.value
    assert server.requests == []
