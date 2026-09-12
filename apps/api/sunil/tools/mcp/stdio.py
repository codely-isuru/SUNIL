"""``mcp_stdio`` — an MCP server spawned as a child process, JSON-RPC on pipes.

Trust boundary TB4 (ARCHITECTURE_V2 §4): the child is spawned with a **minimal
environment** — only the variables named in that server's ``credential_env:``
(C1 §5), never the parent's. The credential resolution happens in
:func:`sunil.tools.mcp.credentials.build_child_env`, BEFORE the spawn, so a
missing or unset credential raises ``ToolAdapterStartupError`` at wiring time
and no half-started child is left behind.

Framing is MCP's stdio transport: one JSON-RPC message per line on stdin /
stdout, UTF-8. The child's stderr is drained to the log — an MCP server's
diagnostics are useful and its silence is not, but they are never parsed and
never reach a model.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

from sunil.core.tool_framework.base import AdapterKind
from sunil.tools.mcp.adapter import McpToolAdapter
from sunil.tools.mcp.config import McpOperationConfig
from sunil.tools.mcp.credentials import build_child_env
from sunil.tools.mcp.protocol import (
    McpTransportError,
    notification_envelope,
    parse_result,
    request_envelope,
)

_LOGGER = logging.getLogger("sunil.tools.mcp.stdio")

#: A guard on a silent child, independent of the operation's own ``timeout_s``
#: (which the manager enforces at step 5). Without it a server that accepts a
#: request and never answers would hold the handshake open forever at startup,
#: where no operation timeout applies.
_READ_TIMEOUT_S = 30.0


class SubprocessStdioTransport:
    """One child process, one request at a time.

    Serialised by a lock: a single pair of pipes carries every call, and MCP
    permits interleaving by id, but matching replies out of order buys nothing
    here (the manager's steps are sequential per turn) and costs a whole
    correlation layer that could mis-attribute one write's outcome to another.
    """

    def __init__(
        self,
        *,
        command: list[str],
        env: dict[str, str],
        logger: logging.Logger | None = None,
        read_timeout_s: float = _READ_TIMEOUT_S,
    ) -> None:
        self._command = list(command)
        self._env = dict(env)
        self._logger = logger or _LOGGER
        self._read_timeout_s = read_timeout_s
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._next_id = 0
        self._stderr_task: asyncio.Task | None = None

    async def open(self) -> None:
        try:
            self._process = await asyncio.create_subprocess_exec(
                *self._command,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self._env,
            )
        except OSError as exc:
            raise McpTransportError(f"could not spawn {self._command[0]!r}: {exc}") from exc
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def close(self) -> None:
        process, self._process = self._process, None
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._stderr_task
            self._stderr_task = None
        if process is None or process.returncode is not None:
            return
        with contextlib.suppress(ProcessLookupError):
            process.terminate()
        with contextlib.suppress(TimeoutError, ProcessLookupError):
            await asyncio.wait_for(process.wait(), timeout=5.0)

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        async with self._lock:
            self._next_id += 1
            request_id = self._next_id
            await self._write(request_envelope(request_id, method, params))
            message = await self._read()
        return parse_result(message, expected_id=request_id)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        async with self._lock:
            await self._write(notification_envelope(method, params))

    # -- internals ---------------------------------------------------------- #
    def _live_process(self) -> asyncio.subprocess.Process:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None:
            raise McpTransportError("MCP stdio transport is not open")
        if process.returncode is not None:
            raise McpTransportError(
                f"MCP server exited with code {process.returncode} before the call completed"
            )
        return process

    async def _write(self, payload: dict[str, Any]) -> None:
        process = self._live_process()
        assert process.stdin is not None
        try:
            process.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await process.stdin.drain()
        except (BrokenPipeError, ConnectionResetError, OSError) as exc:
            raise McpTransportError(f"MCP server pipe closed while writing: {exc}") from exc

    async def _read(self) -> dict[str, Any]:
        process = self._live_process()
        assert process.stdout is not None
        try:
            line = await asyncio.wait_for(
                process.stdout.readline(), timeout=self._read_timeout_s
            )
        except TimeoutError as exc:
            raise McpTransportError(
                f"MCP server did not answer within {self._read_timeout_s}s"
            ) from exc
        if not line:
            raise McpTransportError(
                "MCP server closed its stdout (the child died mid-call)"
            )
        try:
            message = json.loads(line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise McpTransportError(f"MCP server sent unparseable JSON: {exc}") from exc
        if not isinstance(message, dict):
            raise McpTransportError("MCP server sent a non-object JSON-RPC message")
        return message

    async def _drain_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:  # pragma: no cover - defensive
            return
        while True:
            line = await process.stderr.readline()
            if not line:
                return
            # Logged, never parsed, never shown to a model.
            self._logger.debug(
                "mcp stdio child stderr: %s", line.decode("utf-8", "replace").rstrip()
            )


class McpStdioAdapter(McpToolAdapter):
    """C1 §2 adapter for an ``mcp_stdio`` server block in ``config/tools.yaml``."""

    def __init__(
        self,
        *,
        server_id: str,
        command: list[str],
        operations: dict[str, McpOperationConfig],
        credential_env: list[str] | tuple[str, ...] = (),
        settings: Any = None,
        logger: logging.Logger | None = None,
        transport: Any = None,
    ) -> None:
        # The credential lookup is deferred to `start()` (via this factory
        # closure) only in the sense that the ENV is built there: it still
        # happens before the spawn, and its failure is a startup failure.
        self._command = list(command)
        self._credential_env = tuple(credential_env)
        self._settings = settings
        super().__init__(
            server_id=server_id,
            kind=AdapterKind.MCP_STDIO,
            operations=operations,
            transport=transport or _LazyStdioTransport(self, logger=logger),
            logger=logger,
        )


class _LazyStdioTransport:
    """Builds the child env at ``open()`` time, then delegates.

    Why not build the env in ``McpStdioAdapter.__init__``: construction happens
    while the registry is being assembled, and C1 §2's rule is about STARTING —
    "``start()`` failures raise ``ToolAdapterStartupError`` at wiring time". So
    the resolution sits on the ``start()`` path, where its failure is the
    adapter being absent from the registry rather than an exception from a
    constructor that a caller might be tempted to catch.
    """

    def __init__(self, adapter: McpStdioAdapter, *, logger: logging.Logger | None) -> None:
        self._adapter = adapter
        self._logger = logger
        self._delegate: SubprocessStdioTransport | None = None

    async def open(self) -> None:
        env = build_child_env(
            self._adapter._credential_env,  # noqa: SLF001 - same-module collaborator
            self._adapter._settings,  # noqa: SLF001
        )
        self._delegate = SubprocessStdioTransport(
            command=self._adapter._command,  # noqa: SLF001
            env=env,
            logger=self._logger,
        )
        await self._delegate.open()

    async def close(self) -> None:
        if self._delegate is not None:
            await self._delegate.close()
            self._delegate = None

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._delegate is None:
            raise McpTransportError("MCP stdio transport is not open")
        return await self._delegate.request(method, params)

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        if self._delegate is None:
            raise McpTransportError("MCP stdio transport is not open")
        await self._delegate.notify(method, params)
