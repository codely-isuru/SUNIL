"""The permission engine: a pure, structurally default-deny decision function
over ``config/permissions.yaml``.

Sources: C1 §2.2 (the ``PermissionResult`` shape and the hook signature —
"default-deny is structural in the engine, not config"), ADR-034 (an MCP
**server** is a matrix **tool**, an MCP **tool** is an **operation**, so this
engine is reused byte-for-byte for MCP and native alike), and the M1 reference
``main:apps/api/sunil/core/permissions/engine.py``, whose docstring reasoning is
kept because the property it defends is unchanged.

``decide()`` is called at exactly one point on the execution path — the Tool
Manager's step 3 (C1 §2.1) — and its ``decision``/``reason`` are written
verbatim onto the ``tool_calls`` attempt row, so "decision ALLOW, recorded" is a
fact read back from the database, never inferred from the absence of an error.

Nothing here trusts the caller and nothing here reads a file: ``decide()`` takes
a ``PermissionRegistry`` rather than a module-level global, so the
default-deny proof (``test_empty_registry_denies_everything``) can be made
against the emptiest possible registry with no YAML on disk at all.
"""

from __future__ import annotations

from sunil.core.permissions.registry import PermissionRegistry
from sunil.core.tool_framework.base import (
    PermissionDecision,
    PermissionHook,
    PermissionResult,
)

#: C1 §2.2's own example strings, so the engine and C1 §6.1's fake read
#: identically on an audit row.
_GRANTED_REASON = "granted"
_DEFAULT_DENY_REASON = "no grant for this triple (default deny)"
_DEFAULT_DENY_SOURCE = "default-deny"

# The registry `decide()` falls back to when no explicit one is supplied. Empty
# by construction, so an omitted registry denies everything for exactly the same
# reason a genuinely empty `permissions.yaml` would — never a silent allow.
_EMPTY_REGISTRY = PermissionRegistry({})


def decide(
    registry: PermissionRegistry | None = None,
    *,
    agent_id: str,
    tool: str,
    operation: str,
) -> PermissionResult:
    """The single decision point (§33.5 — "never model judgement").

    Structural default-deny: the branch below that returns ``DENY`` on a missing
    grant is this function's own control flow, not a config value a future edit
    could weaken. There is no reachable path that returns ``ALLOW`` or
    ``ASK_USER`` for a triple that is not an explicit, correctly-spelled entry in
    ``config/permissions.yaml`` — an unknown agent, an unknown tool, an unknown
    operation and a known-but-ungranted operation all fall through to the same
    ``None`` branch.
    """
    active = registry if registry is not None else _EMPTY_REGISTRY
    grant = active.grant_for(agent_id, tool, operation)
    if grant is None:
        return PermissionResult(
            decision=PermissionDecision.DENY,
            reason=_DEFAULT_DENY_REASON,
            source=_DEFAULT_DENY_SOURCE,
        )
    return PermissionResult(
        decision=PermissionDecision(grant),
        reason=_GRANTED_REASON,
        source=f"config:{agent_id}.{tool}.{operation}",
    )


class PermissionEngineHook:
    """The production ``PermissionHook`` (C1 §2.2) — a thin, keyword-only
    callable over :func:`decide` and one registry.

    Deliberately NOT inheriting ``PermissionHook``: an explicitly inherited
    ``Protocol`` hands the subclass ``...`` bodies as real callables that return
    ``None``, so a misspelled ``__call__`` would answer ``None`` — a vacuous
    "allow-shaped" result — instead of raising (the fakes-build F2 lesson).
    Structural conformance plus the witness at the foot of this module says the
    same thing without the trapdoor.
    """

    def __init__(self, registry: PermissionRegistry) -> None:
        self._registry = registry

    def __call__(self, *, agent_id: str, tool: str, operation: str) -> PermissionResult:
        return decide(self._registry, agent_id=agent_id, tool=tool, operation=operation)


#: Static conformance witness — a type checker reads this as "PermissionEngineHook
#: must satisfy C1 §2.2's PermissionHook".
_check: PermissionHook = PermissionEngineHook(_EMPTY_REGISTRY)
