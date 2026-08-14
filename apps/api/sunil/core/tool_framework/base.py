"""Tool framework primitives (`ARCHITECTURE_V1.md` §9.3, §10, §26.8).

`ToolOperation` and `ToolAdapter` are the shape every `sunil.tools.*`
package implements against; `ToolManager` (in `manager.py`, same package)
is the only caller that may hold a reference to one.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class ToolResult:
    """The normalised shape every adapter call collapses to
    (`ARCHITECTURE_V1.md` §9.3 step 7). An adapter exception never
    reaches the orchestrator as an exception — it is always this."""

    ok: bool
    data: dict | None
    error_kind: str | None
    error_message: str | None


@dataclass(frozen=True)
class ToolOperation:
    """One operation a `ToolAdapter` exposes.

    `params_model` is a Pydantic model with `extra="forbid"` (§26.8) —
    the authoritative parameter validation the Tool Manager runs at step
    3, distinct from `config/tools.yaml`'s `params` block, which is a
    cross-validated, human-readable inventory, not a second enforcement
    mechanism (that module's own docstring).
    """

    name: str
    params_model: type[BaseModel]
    read_only: bool
    timeout_s: float
    handler: Callable[[BaseModel], Awaitable[ToolResult]]


class ToolAdapter(Protocol):
    """What every `sunil.tools.*` adapter implements.

    Deliberately **not** `@runtime_checkable` — T19's security suite adds
    a tripwire test for exactly this shape of mistake on `ValidatedPlan`
    (a `@runtime_checkable` Protocol makes `isinstance` prove shape, not
    provenance), and nothing in this framework should repeat it. Nothing
    here does or should `isinstance()`-check against `ToolAdapter`; the
    Tool Manager is constructed with concrete adapter instances by the
    code that wires it (T10/T11b), not by duck-typing one at runtime.
    """

    name: str
    operations: dict[str, ToolOperation]
