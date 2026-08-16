"""The canonical training-data capture vocabulary (ADR-014 Amendment 1,
`ARCHITECTURE_V1.md` A-18).

**One leaf module, importing nothing from `sunil`,** so both
`core/registry/capture.py` (config loading, BE-2) and `db/capture.py`
(persistence, BE-1) depend on it without either pulling in the other's
dependency tree — vocabulary is domain language, not a persistence detail
and not a registry-loading detail. Neither `core/` nor `db/` may define a
second copy of any name in this file.

**Why this module exists at all.** T2 (`sunil/db/capture.py`) and T3
(`sunil/core/registry/capture.py`) each independently defined this
vocabulary, because ADR-014 named the *columns* and the *resolver
signature* but never said who owned the *types*. Two of five
`CaptureKind` values diverged (`tool_call` vs `tool_call_result`,
`memory` vs `memory_short_term`) and the container types were
incompatible (a Pydantic model of plain strings vs a `NamedTuple` of
StrEnums), so T3's registry output did not fit the `overrides` parameter
it was built to flow into. The ruling (Amendment 1): one module, one
vocabulary, `CaptureKind` is table-keyed because the four capture columns
live *on the row* — a kind finer than a row cannot be honoured.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class CaptureKind(StrEnum):
    """One member per capture-column-bearing table (§7.3.1) — table-keyed,
    not content-shape-keyed. `audit_events` deliberately has no member
    here and never will: a capture policy must never be able to suppress
    an audit row."""

    MESSAGE = "message"
    PLAN = "plan"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    MEMORY = "memory"


class CapturePolicy(StrEnum):
    """The four ADR-014 policy values."""

    NONE = "none"
    METADATA_ONLY = "metadata_only"
    REDACTED_FULL = "redacted_full"
    FULL_LOCAL_ONLY = "full_local_only"


class Sensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


class RetentionClass(StrEnum):
    TRANSIENT = "transient"
    STANDARD = "standard"
    LONG = "long"
    PERMANENT = "permanent"


class ContentSource(StrEnum):
    """Where one row's content originated — the parameter that preserves
    T2's original instinct (external tool results deserve a different
    default from SUNIL-generated content) *without* a second `CaptureKind`
    (Amendment 1): `kind=TOOL_CALL, source=EXTERNAL_TOOL_RESULT` for a
    GitHub result vs `source=SUNIL_GENERATED` for the parameters SUNIL
    itself constructed for that same row. Where one row draws on more
    than one source, the row takes the **most restrictive** applicable
    policy — there is one `capture_policy` column per row, not one per
    source."""

    OWNER = "owner"
    SUNIL_GENERATED = "sunil_generated"
    EXTERNAL_TOOL_RESULT = "external_tool_result"
    SYSTEM = "system"


@dataclass(frozen=True)
class CaptureRule:
    """**The type that crosses the module boundary** (Amendment 1 point
    3): `core/registry/capture.py` returns `dict[CaptureKind, CaptureRule]`
    (or, for an override, `Mapping[CaptureKind, CaptureRule]`); `db/
    capture.py`'s `resolve_capture()` accepts exactly that. No plain
    string ever crosses this boundary — an unknown YAML value is rejected
    at load time, in the one place untyped input enters
    (`core/registry/capture.py`), never carried forward as a string for a
    later function to reinterpret."""

    capture_policy: CapturePolicy
    sensitivity: Sensitivity
    retention_class: RetentionClass


@dataclass(frozen=True)
class CaptureDecision:
    """What `resolve_capture()` returns — the four ADR-014 columns,
    resolved once at capture time. `training_eligible` is **derived,
    never hand-set**:
    `training_eligible = capture_policy in {REDACTED_FULL, FULL_LOCAL_ONLY}
    and sensitivity in {PUBLIC, INTERNAL}`. `FULL_LOCAL_ONLY` may still be
    training-eligible — it constrains *where* training may happen, not
    *whether*.
    """

    capture_policy: CapturePolicy
    sensitivity: Sensitivity
    retention_class: RetentionClass
    training_eligible: bool
