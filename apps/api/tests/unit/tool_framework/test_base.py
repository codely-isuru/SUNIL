"""`sunil.core.tool_framework.base` — the tool-framework primitives."""

from __future__ import annotations

import dataclasses
import typing

import pytest
from sunil.core.tool_framework.base import ToolAdapter, ToolOperation, ToolResult


def test_tool_adapter_is_not_runtime_checkable() -> None:
    """The Security Reviewer's sharpest catch on this codebase: a
    `@runtime_checkable` Protocol makes `isinstance` prove shape, not
    provenance. `ToolAdapter` is never `isinstance()`-checked against
    anywhere in this framework, and it must stay that way — this test is
    the tripwire."""
    assert not getattr(ToolAdapter, "_is_runtime_protocol", False)


def test_tool_adapter_is_a_protocol() -> None:
    assert issubclass(ToolAdapter, typing.Protocol)


def test_tool_result_is_frozen() -> None:
    result = ToolResult(ok=True, data={"a": 1}, error_kind=None, error_message=None)

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.ok = False  # type: ignore[misc]


def test_tool_operation_holds_its_handler() -> None:
    async def _handler(_: object) -> ToolResult:
        return ToolResult(ok=True, data=None, error_kind=None, error_message=None)

    op = ToolOperation(
        name="x",
        params_model=object,
        read_only=True,
        timeout_s=1.0,
        handler=_handler,  # type: ignore[arg-type]
    )

    assert op.name == "x"
    assert op.handler is _handler
