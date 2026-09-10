"""``FakeToolAdapter`` — C1 §6.3's fake specification, verbatim.

Source of truth: ``docs/contracts/C1-tool-adapter.md`` §6.3 (v1.0.0, FROZEN
2026-09-10). Importable by every stream's tests (§6.3).

The five operations are byte-exact to the spec table, including the two failure
lanes the manager must normalise: ``fail_upstream`` returns an error *result*,
``raise_unexpected`` *raises* — C1 §2 requires that an adapter exception never
reaches the orchestrator as an exception, so the manager converts it to
``error_kind="upstream_error"`` with the message ``"unhandled adapter
exception"`` (never the raw exception text).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from pydantic import BaseModel, Field

from sunil.core.tool_framework.base import (
    AdapterKind,
    ToolAdapter,
    ToolOperation,
    ToolResult,
    ToolResultMeta,
)


class EchoParams(BaseModel, extra="forbid"):
    text: str = Field(min_length=1, max_length=1000)


class WriteItemParams(BaseModel, extra="forbid"):
    key: str = Field(pattern=r"^[a-z0-9_]{1,64}$")
    value: str = Field(max_length=1000)


class NoParams(BaseModel, extra="forbid"):
    pass


class FakeToolAdapter(ToolAdapter):
    """C1 §6.3 — ``name="fake_tool"``, ``kind=AdapterKind.NATIVE``, in-memory
    ``dict`` store, ``start()``/``stop()`` set/clear ``self.started``."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self.name = "fake_tool"
        self.kind = AdapterKind.NATIVE
        self.clock = clock
        self.store: dict[str, str] = {}
        self.started = False
        self.operations: dict[str, ToolOperation] = {
            "echo": ToolOperation(
                name="echo",
                params_model=EchoParams,
                read_only=True,
                timeout_s=5.0,
                handler=self._echo,
            ),
            "write_item": ToolOperation(
                name="write_item",
                params_model=WriteItemParams,
                read_only=False,
                timeout_s=5.0,
                handler=self._write_item,
            ),
            "fail_upstream": ToolOperation(
                name="fail_upstream",
                params_model=NoParams,
                read_only=True,
                timeout_s=5.0,
                handler=self._fail_upstream,
            ),
            "raise_unexpected": ToolOperation(
                name="raise_unexpected",
                params_model=NoParams,
                read_only=True,
                timeout_s=5.0,
                handler=self._raise_unexpected,
            ),
            "sleep_forever": ToolOperation(
                name="sleep_forever",
                params_model=NoParams,
                read_only=True,
                timeout_s=0.05,
                handler=self._sleep_forever,
            ),
        }

    # -- lifecycle (C1 §2: NATIVE adapters are no-ops beyond the flag) ------ #
    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    # -- operations --------------------------------------------------------- #
    async def _echo(self, params: EchoParams) -> ToolResult:
        started = self.clock()
        return self._ok({"echo": params.text}, started)

    async def _write_item(self, params: WriteItemParams) -> ToolResult:
        started = self.clock()
        self.store[params.key] = params.value
        return self._ok({"written": params.key, "count": len(self.store)}, started)

    async def _fail_upstream(self, params: NoParams) -> ToolResult:
        started = self.clock()
        return ToolResult(
            ok=False,
            data=None,
            error_kind="upstream_error",
            error_message="fake upstream failure",
            meta=self._meta(started),
        )

    async def _raise_unexpected(self, params: NoParams) -> ToolResult:
        raise RuntimeError("fake crash")

    async def _sleep_forever(self, params: NoParams) -> ToolResult:
        started = self.clock()
        await asyncio.sleep(3600)
        return self._ok({"slept": True}, started)  # pragma: no cover - unreachable

    # -- internals ---------------------------------------------------------- #
    def _ok(self, data: dict, started: float) -> ToolResult:
        return ToolResult(
            ok=True,
            data=data,
            error_kind=None,
            error_message=None,
            meta=self._meta(started),
        )

    def _meta(self, started: float) -> ToolResultMeta:
        """C1 §6.3 — every result's meta is ``adapter_kind=NATIVE``,
        ``server_id=None``, ``duration_ms=<measured>``."""
        return ToolResultMeta(
            adapter_kind=AdapterKind.NATIVE,
            server_id=None,
            duration_ms=int((self.clock() - started) * 1000),
        )
