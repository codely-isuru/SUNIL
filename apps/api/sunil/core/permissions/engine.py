"""The permission engine (T7): a pure, structurally default-deny decision
function over `config/permissions.yaml`.

`ARCHITECTURE_V1.md` §9.2, FR-120/121, ADR-000 Q4, **ET-4**. `decide()` is
called at exactly one point on the execution path — `ToolManager.execute()`
step 4 (T8, §9.3) — and its result is written verbatim onto the
`tool_calls` row (`permission_decision`, `permission_reason`) so ET-4's
"decision `ALLOW`, recorded" is a fact read back from the database, never
an inference from the absence of an error.

Nothing here trusts the caller. `decide()` takes a `PermissionRegistry`
(T3) rather than reading a module-level global, so this stays a pure
function: no import-time file I/O, and `test_empty_permission_config_
denies_everything` below constructs the emptiest possible registry
directly, with no YAML file involved at all.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from sunil.core.registry.permissions import PermissionRegistry


class Decision(StrEnum):
    """Three-valued outcome (§9.2). `ASK_USER` is a legal value from day
    one even though M1 grants no operation that resolves to it — M1 has
    no write/destructive operation (FR-121) — so M5 adds a queue and a UI
    against an existing concept, not a new enum member."""

    ALLOW = "allow"
    DENY = "deny"
    ASK_USER = "ask_user"


@dataclass(frozen=True)
class PermissionResult:
    """What `decide()` returns. `source` is either the exact grant path
    that produced the decision (`"config:<agent>.<tool>.<operation>"`) or
    the literal string `"default-deny"` — never blank, never inferred by
    a caller, always traceable back to *why*."""

    decision: Decision
    reason: str
    source: str


_DEFAULT_DENY_REASON = "no explicit grant"
_DEFAULT_DENY_SOURCE = "default-deny"

# The registry `decide()` falls back to when no explicit one is supplied.
# Empty by construction, so an omitted registry denies everything for
# exactly the same reason a genuinely empty `permissions.yaml` would —
# never a silent allow. This is what lets `decide(agent_id=..., tool=...,
# operation=...)` (no registry at all) be a legal call, added for T19's
# security suite (`test_empty_permission_config_denies_everything`),
# without weakening or changing the behaviour of every existing call that
# passes a registry positionally.
_EMPTY_REGISTRY = PermissionRegistry({})


def decide(
    registry: PermissionRegistry | None = None,
    *,
    agent_id: str,
    tool: str,
    operation: str,
) -> PermissionResult:
    """The single decision point (§9.2, §33.5 — "never model judgement").

    Structural default-deny: the branch below that returns `Decision.DENY`
    on a missing grant is the function's own control flow, not a config
    value that a future edit could accidentally weaken. There is no
    reachable path through this function that returns `ALLOW` or
    `ASK_USER` for an agent/tool/operation triple that is not an explicit,
    correctly-spelled entry in `config/permissions.yaml` — an unknown
    agent, an unknown tool, an unknown operation and a known-but-ungranted
    operation all fall through to exactly the same `None` branch below.

    `registry` defaults to an empty (structurally default-deny) one — see
    `_EMPTY_REGISTRY` — so calling this with no registry at all is legal
    and still denies everything, rather than raising or guessing.
    """
    active_registry = registry if registry is not None else _EMPTY_REGISTRY
    grant = active_registry.grant_for(agent_id, tool, operation)
    if grant is None:
        return PermissionResult(
            decision=Decision.DENY,
            reason=_DEFAULT_DENY_REASON,
            source=_DEFAULT_DENY_SOURCE,
        )
    return PermissionResult(
        decision=Decision(grant),
        reason="explicit grant",
        source=f"config:{agent_id}.{tool}.{operation}",
    )


def decide_with(
    config: dict[str, dict[str, dict[str, str]]],
    *,
    agent_id: str,
    tool: str,
    operation: str,
) -> PermissionResult:
    """Convenience wrapper for a caller holding a raw grants mapping —
    the same shape `permissions.yaml` parses to — rather than a
    constructed `PermissionRegistry`. Added for T19's security suite,
    which asserts default-deny against a literal `{}` without importing
    the registry type; delegates to `decide()` so there is exactly one
    decision function, not two implementations to keep in sync.
    """
    return decide(PermissionRegistry(config), agent_id=agent_id, tool=tool, operation=operation)
