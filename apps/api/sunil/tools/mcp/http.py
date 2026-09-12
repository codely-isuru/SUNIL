"""``mcp_http`` — MCP streamable HTTP (the n8n MCP server, TB5).

One POST per JSON-RPC message to the server's single MCP endpoint, with
``Accept: application/json, text/event-stream`` (a streamable-HTTP server may
answer either way, and a client that accepts only JSON gets a 406 from a
compliant one). The session id the server returns on ``initialize`` is carried
on every later request, as is the pinned protocol revision.

The auth header value comes from settings (C1 §5: "for ``mcp_http``, the auth
header value comes from the same settings mechanism") and is held as a
``SecretStr`` right up to the header dict, so it cannot be logged by accident;
no error message built here includes a request header.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import SecretStr

from sunil.core.tool_framework.base import (
    AdapterKind,
    ToolAdapterStartupError,
)
from sunil.tools.mcp.adapter import McpToolAdapter
from sunil.tools.mcp.config import McpOperationConfig
from sunil.tools.mcp.protocol import (
    MCP_PROTOCOL_VERSION,
    McpTransportError,
    notification_envelope,
    parse_result,
    request_envelope,
)

_LOGGER = logging.getLogger("sunil.tools.mcp.http")


class StreamableHttpTransport:
    """JSON-RPC over one HTTP endpoint, with SSE replies handled."""

    def __init__(
        self,
        *,
        base_url: str,
        auth_token: SecretStr,
        client: Any | None = None,
        logger: logging.Logger | None = None,
        timeout_s: float = 30.0,
    ) -> None:
        self._base_url = base_url
        self._auth_token = auth_token
        self._client = client
        self._owns_client = client is None
        self._logger = logger or _LOGGER
        self._timeout_s = timeout_s
        self._session_id: str | None = None
        self._next_id = 0

    async def open(self) -> None:
        if self._client is None:
            import httpx  # noqa: PLC0415 - lazy: only the HTTP lane needs it

            self._client = httpx.AsyncClient(
                timeout=self._timeout_s,
                # ADR-017's reasoning, one boundary over: a redirected base
                # would forward the bearer token to whatever host answered.
                follow_redirects=False,
            )

    async def close(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None
        self._session_id = None

    def _headers(self) -> dict[str, str]:
        headers = {
            "content-type": "application/json",
            "accept": "application/json, text/event-stream",
            "authorization": f"Bearer {self._auth_token.get_secret_value()}",
            "mcp-protocol-version": MCP_PROTOCOL_VERSION,
        }
        if self._session_id is not None:
            headers["mcp-session-id"] = self._session_id
        return headers

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self._next_id += 1
        request_id = self._next_id
        response = await self._post(request_envelope(request_id, method, params))
        if response.headers.get("mcp-session-id"):
            self._session_id = response.headers["mcp-session-id"]
        message = self._decode(response)
        return parse_result(message, expected_id=request_id)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._post(notification_envelope(method, params))

    # -- internals ---------------------------------------------------------- #
    async def _post(self, payload: dict[str, Any]):
        import httpx  # noqa: PLC0415 - lazy, as above

        if self._client is None:
            raise McpTransportError("MCP HTTP transport is not open")
        try:
            response = await self._client.post(
                self._base_url, content=json.dumps(payload), headers=self._headers()
            )
        except httpx.HTTPError as exc:
            # Could not reach it at all: connect refused, DNS, read timeout.
            # C1 §4's `transport_error` — the only kind policy may auto-retry.
            raise McpTransportError(f"could not reach the MCP server: {type(exc).__name__}") from exc
        if response.status_code >= 400:
            # Reached and refused. `upstream_error` via McpServerError-shaped
            # text would hide the status, so the status is named — never the
            # body, which is untrusted content, and never a header.
            from sunil.tools.mcp.protocol import McpServerError  # noqa: PLC0415

            raise McpServerError(
                f"MCP server returned HTTP {response.status_code}"
            )
        return response

    def _decode(self, response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        text = response.text
        if "text/event-stream" in content_type:
            payload = _last_sse_data(text)
            if payload is None:
                raise McpTransportError("SSE reply carried no data frame")
            text = payload
        try:
            message = json.loads(text)
        except json.JSONDecodeError as exc:
            raise McpTransportError(f"MCP server sent unparseable JSON: {exc}") from exc
        if not isinstance(message, dict):
            raise McpTransportError("MCP server sent a non-object JSON-RPC message")
        return message


def _last_sse_data(body: str) -> str | None:
    """The ``data:`` payload of the last SSE frame.

    A streamable-HTTP server may emit progress notifications before the reply,
    so the LAST data frame is the answer; frames are one-line JSON in MCP, and
    this deliberately does not implement multi-line ``data:`` concatenation it
    has never been sent — silently joining lines would be a guess about the
    protocol rather than a reading of it.
    """
    payload: str | None = None
    for line in body.splitlines():
        if line.startswith("data:"):
            payload = line[len("data:") :].strip()
    return payload


class McpHttpAdapter(McpToolAdapter):
    """C1 §2 adapter for an ``mcp_http`` server block in ``config/tools.yaml``."""

    def __init__(
        self,
        *,
        server_id: str,
        base_url: str,
        auth_token: SecretStr,
        operations: dict[str, McpOperationConfig],
        client: Any | None = None,
        logger: logging.Logger | None = None,
    ) -> None:
        if not base_url.startswith(("http://", "https://")):
            raise ToolAdapterStartupError(
                f"{server_id}: base_url {base_url!r} is not an HTTP(S) URL "
                "(the ADR-033 host validator is Settings-side; this is the adapter's floor)"
            )
        if not auth_token.get_secret_value():
            raise ToolAdapterStartupError(
                f"{server_id}: auth token is unset — refusing to start (C1 §5)"
            )
        super().__init__(
            server_id=server_id,
            kind=AdapterKind.MCP_HTTP,
            operations=operations,
            transport=StreamableHttpTransport(
                base_url=base_url,
                auth_token=auth_token,
                client=client,
                logger=logger,
            ),
            logger=logger,
        )
