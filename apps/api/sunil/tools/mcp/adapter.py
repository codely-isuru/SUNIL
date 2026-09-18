"""The MCP adapter body shared by both transports (stdio, streamable HTTP).

C1 §2's ``ToolAdapter`` for an MCP server: ``name`` is the server's
``config/tools.yaml`` key (ADR-034 — the server IS the permission-matrix tool),
``operations`` are SUNIL's configured operations (never the server's
``tools/list``), and ``start``/``stop`` own the connection.

``start()`` does three things, in order, and fails startup rather than first
call if any of them is wrong (ADR-034 decision 2, C1 §2: "a tool that cannot
start is absent from the registry, never half-present"):

1. connect/spawn (the transport's job, including C1 §5's minimal child env);
2. the ``initialize`` handshake on the PINNED protocol revision, plus
   ``notifications/initialized``;
3. the ``tools/list`` **drift check** — every configured operation must be
   advertised; an advertised-but-unconfigured tool is logged and ignored
   ("it does not exist to SUNIL"), and its annotations are logged for the human
   who maintains config and read by nothing.

Results are NOT sanitised here. The cap and the strip of C1 §3 are applied once,
by the chokepoint (``core/tool_framework/manager.py`` step 7), so two adapters
cannot disagree about what "untrusted" means.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Protocol

from pydantic import BaseModel

from sunil.core.tool_framework.base import (
    AdapterKind,
    ToolAdapterStartupError,
    ToolErrorKind,
    ToolOperation,
    ToolResult,
    ToolResultMeta,
)
from sunil.tools.mcp.compositions import (
    CompositionContext,
    CompositionError,
    resolve_composition,
)
from sunil.tools.mcp.config import McpOperationConfig
from sunil.tools.mcp.protocol import (
    MCP_PROTOCOL_VERSION,
    McpServerError,
    McpTransportError,
    initialize_params,
    listed_tool_names,
    tool_call_payload,
)

_LOGGER = logging.getLogger("sunil.tools.mcp.adapter")


class McpTransport(Protocol):
    """The seam between an MCP adapter and its wire.

    Two implementations: a spawned child on stdio pipes (``stdio.py``) and
    streamable HTTP (``http.py``). Both raise
    :class:`~sunil.tools.mcp.protocol.McpTransportError` for "could not reach"
    and :class:`~sunil.tools.mcp.protocol.McpServerError` for "reached and
    refused", which is what lets this module map to C1 §4's closed set once
    instead of per transport.
    """

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]: ...

    async def notify(self, method: str, params: dict[str, Any]) -> None: ...


class McpToolAdapter:
    """C1 §2 ``ToolAdapter`` over an :class:`McpTransport`.

    Not inheriting the ``ToolAdapter`` protocol on purpose (the fakes-build F2
    lesson): an inherited ``Protocol`` would hand this class ``...`` bodies that
    return ``None``, so a misspelled ``stop`` would answer ``None`` instead of
    raising. The witnesses live in the unit tests as annotated assignments.
    """

    def __init__(
        self,
        *,
        server_id: str,
        kind: AdapterKind,
        operations: dict[str, McpOperationConfig],
        transport: McpTransport,
        logger: logging.Logger | None = None,
        project_repos: dict[str, tuple[str, str]] | None = None,
    ) -> None:
        self.name = server_id
        self.server_id = server_id
        self.kind = kind
        self._transport = transport
        self._config = dict(operations)
        self._logger = logger or _LOGGER
        self._started = False
        # Every bound server tool this adapter may call — the drift check's
        # subject AND the composition executor's allowlist, built once from the
        # same source so they cannot disagree (ADR-034 Amendment 1).
        self._bound_server_tools = {
            server_tool
            for config in self._config.values()
            for server_tool in config.server_tools
        }
        self._context = CompositionContext(project_repos=project_repos)
        self.operations: dict[str, ToolOperation] = {
            name: ToolOperation(
                name=name,
                params_model=config.params_model,
                read_only=config.read_only,
                timeout_s=config.timeout_s,
                handler=self._handler_for(name),
            )
            for name, config in self._config.items()
        }

    # -- lifecycle ---------------------------------------------------------- #
    async def start(self) -> None:
        try:
            await self._transport.open()
            init = await self._transport.request("initialize", initialize_params())
            self._check_protocol_revision(init)
            await self._transport.notify("notifications/initialized", {})
            listed = listed_tool_names(await self._transport.request("tools/list", {}))
        except ToolAdapterStartupError:
            raise
        except (McpTransportError, McpServerError) as exc:
            raise ToolAdapterStartupError(
                f"{self.server_id}: MCP startup failed ({exc})"
            ) from exc
        self._drift_check(listed)
        self._started = True

    async def stop(self) -> None:
        self._started = False
        await self._transport.close()

    def _check_protocol_revision(self, init_result: dict[str, Any]) -> None:
        advertised = init_result.get("protocolVersion")
        if advertised != MCP_PROTOCOL_VERSION:
            raise ToolAdapterStartupError(
                f"{self.server_id}: server speaks MCP {advertised!r}, this client pins "
                f"{MCP_PROTOCOL_VERSION!r} — refusing to start (ADR-034: pinned versions, "
                "drift visible at startup)"
            )

    def _drift_check(self, listed: dict[str, dict[str, Any]]) -> None:
        # ADR-034 Amendment 1 (ruling R16 part 3): the check is against the
        # BINDINGS, not SUNIL's operation names. `issues_close` is served by
        # `issue_write`, and a composed operation is served by EVERY tool it
        # composes — all of them must be advertised or the whole tool leaves the
        # registry, because a composition that can start but not finish is the
        # one failure mode worse than not starting.
        bound: dict[str, str] = {
            server_tool: operation
            for operation, config in self._config.items()
            for server_tool in config.server_tools
        }
        missing = sorted(set(bound) - set(listed))
        if missing:
            detail = ", ".join(f"{name} (bound by {bound[name]})" for name in missing)
            raise ToolAdapterStartupError(
                f"{self.server_id}: configured operation(s) bind server tool(s) the live "
                f"server does not advertise: {detail} — refusing to start (ADR-034 drift "
                "check)"
            )
        for name in sorted(set(listed) - set(bound)):
            # "An advertised-but-unconfigured tool is logged and ignored (it does
            # not exist to SUNIL)." The annotations go in the log for the human
            # who maintains config, and are read by nothing else.
            self._logger.info(
                "%s advertises %r, which SUNIL config does not declare — ignored "
                "(ADR-034: new operations arrive by config PR). Server annotations, "
                "recorded for review only: %s",
                self.server_id,
                name,
                listed[name].get("annotations", {}),
            )

    # -- operations --------------------------------------------------------- #
    def _handler_for(self, operation: str):
        config = self._config[operation]
        composition = (
            resolve_composition(config.composition, config, server_id=self.server_id)
            if config.composition
            else None
        )

        async def handler(params: BaseModel) -> ToolResult:
            started = time.monotonic()
            if not self._started:
                return self._error(
                    ToolErrorKind.TRANSPORT_ERROR,
                    f"{self.server_id} is not started",
                    started,
                )
            try:
                if composition is not None:
                    payload = await composition.execute(
                        params, call=self.call_server_tool, context=self._context
                    )
                else:
                    payload = await self.call_server_tool(
                        config.server_tools[0],
                        {**params.model_dump(), **config.fixed_arguments},
                    )
            except McpServerError as exc:
                return self._error(ToolErrorKind.UPSTREAM_ERROR, str(exc), started)
            except McpTransportError as exc:
                return self._error(ToolErrorKind.TRANSPORT_ERROR, str(exc), started)
            except CompositionError as exc:
                return self._error(ToolErrorKind.UPSTREAM_ERROR, str(exc), started)
            return ToolResult(
                ok=True,
                data=payload,
                error_kind=None,
                error_message=None,
                meta=self._meta(started),
            )

        return handler

    async def call_server_tool(self, server_tool: str, arguments: dict[str, Any]) -> Any:
        """One `tools/call`, under the BOUND name. The composition executor's
        only way to reach the wire, so a composition cannot invent a tool the
        drift check never verified — `server_tool` is asserted against the
        bindings this adapter was constructed with."""
        if server_tool not in self._bound_server_tools:
            raise CompositionError(
                f"{self.server_id}: {server_tool!r} is not a bound server tool of this "
                "adapter (ADR-034 Amendment 1: a composition may only call tools the "
                "drift check verified)"
            )
        result = await self._transport.request(
            "tools/call", {"name": server_tool, "arguments": arguments}
        )
        return tool_call_payload(result)

    # -- internals ---------------------------------------------------------- #
    def _error(self, kind: ToolErrorKind, message: str, started: float) -> ToolResult:
        return ToolResult(
            ok=False,
            data=None,
            error_kind=kind.value,
            error_message=message,
            meta=self._meta(started),
        )

    def _meta(self, started: float) -> ToolResultMeta:
        return ToolResultMeta(
            adapter_kind=self.kind,
            server_id=self.server_id,
            duration_ms=int((time.monotonic() - started) * 1000),
        )
