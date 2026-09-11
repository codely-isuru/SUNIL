"""MCP wire protocol — the pinned revision, the JSON-RPC shapes, the errors.

ADR-034 records that server versions are pinned in config and that drift is
caught at startup; :data:`MCP_PROTOCOL_VERSION` is the client half of that
promise. The adapter announces exactly this revision in ``initialize`` and
refuses to start against a server that answers with a different one — a
negotiated-down protocol would change what ``tools/call`` results look like
under a chokepoint whose untrusted-results posture is written against ONE shape.

Only the four methods SUNIL uses are modelled (``initialize``,
``notifications/initialized``, ``tools/list``, ``tools/call``). MCP's prompts,
resources, sampling and elicitation surfaces are deliberately absent: a server
cannot ask SUNIL for anything, because there is no code here that would answer.
"""

from __future__ import annotations

from typing import Any

#: The MCP revision this client speaks, pinned (ADR-034).
MCP_PROTOCOL_VERSION = "2025-06-18"

#: Announced in ``initialize``. Tools only — see the module docstring.
CLIENT_INFO = {"name": "sunil", "version": "2.0.0"}
CLIENT_CAPABILITIES: dict[str, Any] = {}


class McpTransportError(Exception):
    """Could not reach / keep the server: child died, pipe closed, connect
    refused, malformed framing. Maps to C1 §4 ``transport_error`` (retryable by
    policy)."""


class McpServerError(Exception):
    """The server was reached and answered with a failure — a JSON-RPC error
    object or a ``tools/call`` result with ``isError: true``. Maps to C1 §4
    ``upstream_error`` (NOT auto-retried)."""


def initialize_params() -> dict[str, Any]:
    return {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": CLIENT_CAPABILITIES,
        "clientInfo": CLIENT_INFO,
    }


def request_envelope(request_id: int, method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": params}


def notification_envelope(method: str, params: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "method": method, "params": params}


def parse_result(message: dict[str, Any], *, expected_id: int) -> dict[str, Any]:
    """Return the ``result`` object, or raise.

    A reply whose ``id`` does not match is a framing failure, not a server
    failure: the adapter would otherwise attribute one call's answer to another,
    which on a write operation means reporting someone else's outcome.
    """
    if message.get("id") != expected_id:
        raise McpTransportError(
            f"JSON-RPC id mismatch: expected {expected_id}, received {message.get('id')!r}"
        )
    if "error" in message:
        error = message["error"] or {}
        raise McpServerError(
            f"server error {error.get('code', 'unknown')}: {error.get('message', '')}"
        )
    result = message.get("result")
    if not isinstance(result, dict):
        raise McpTransportError("JSON-RPC reply carried no result object")
    return result


def tool_call_payload(result: dict[str, Any]) -> dict[str, Any]:
    """Normalise a ``tools/call`` result into ``ToolResult.data``.

    ``isError: true`` is the MCP-level failure channel and raises
    :class:`McpServerError` (C1 §4 maps it to ``upstream_error``).
    ``structuredContent`` is preferred when present — it is the typed shape —
    and the content blocks are passed through otherwise, untouched and
    unparsed: they are untrusted data (C1 §3) and this layer must not interpret
    them, only carry them to the chokepoint's sanitiser.
    """
    if result.get("isError") is True:
        blocks = result.get("content") or []
        detail = "; ".join(
            block.get("text", "") for block in blocks if isinstance(block, dict)
        )
        raise McpServerError(detail or "tool reported an error result")
    structured = result.get("structuredContent")
    if isinstance(structured, dict):
        return structured
    return {"content": result.get("content", [])}


def listed_tool_names(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """``tools/list`` → ``{name: tool object}``. Informative only (ADR-034
    decision 2): the return value feeds the startup drift check and the log, and
    nothing else."""
    tools = result.get("tools")
    if not isinstance(tools, list):
        raise McpTransportError("tools/list carried no tools array")
    listed: dict[str, dict[str, Any]] = {}
    for tool in tools:
        if isinstance(tool, dict) and isinstance(tool.get("name"), str):
            listed[tool["name"]] = tool
    return listed
