"""The one canonical training-data capture vocabulary (ADR-014 Amendment 1).

A top-level leaf module, beside `redaction.py`, **importing nothing from
`sunil`** — this is domain language, not a persistence or registry detail,
and neither `core/` nor `db/` may define a second copy of it.

**Why this file exists.** `sunil.db.capture` (T2) and
`sunil.core.registry.capture` (T3) each originally defined this vocabulary
independently, because ADR-014 named the four capture-table columns and
the resolver's signature but never said *who owns the types*. Two of five
`CaptureKind` values diverged (`tool_call_result`/`memory_short_term` vs.
`tool_call`/`memory`) and the container types were incompatible (a
`NamedTuple` of `StrEnum`s vs. a Pydantic model of plain strings), so
`resolve_capture(overrides=...)` could never actually accept what the
registry loader produced — the seam and the thing meant to flow through it
never fit. Amendment 1's ruling: one module owns the vocabulary, everyone
else imports it.

**`CaptureKind` is table-keyed, not content-keyed**:
`message · plan · llm_call · tool_call · memory` — one value per capture
table (§7.3.1), because the four capture columns live *on the row*. A kind
finer than a row cannot be honoured: `tool_call`'s `parameters` and
`result` cannot carry different policies, because there is one
`capture_policy` column for the whole `tool_calls` row. Where a genuinely
different default is needed for a sub-case (external tool output vs.
SUNIL-generated content, say), that is what `ContentSource` is for —
`resolve_capture(kind=CaptureKind.TOOL_CALL, source=ContentSource.EXTERNAL_TOOL_RESULT)`
— not a sixth `CaptureKind`. Where one row draws on more than one source,
the row takes the **most restrictive** applicable policy.

**`CaptureRule` is the type that crosses the boundary.**
`core/registry/capture.py` (T3) is the *only* place raw YAML strings are
converted to these enums — it refuses to boot on an unrecognised value,
like every other registry — and returns `dict[CaptureKind, CaptureRule]`.
`sunil.db.capture.resolve_capture()` (T2) accepts exactly that shape. No
plain string crosses this boundary in either direction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import NamedTuple


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


class CaptureKind(StrEnum):
    """One member per capture table (§7.3.1) — table-keyed, not
    content-keyed. See the module docstring for why a finer vocabulary
    (e.g. a separate kind for tool *results* vs. tool *parameters*) cannot
    be honoured: there is one `capture_policy` column per row.
    """

    MESSAGE = "message"
    PLAN = "plan"
    LLM_CALL = "llm_call"
    TOOL_CALL = "tool_call"
    MEMORY = "memory"


class ContentSource(StrEnum):
    """Where the content originated.

    This is where a sub-case that genuinely warrants a different default
    is expressed — `kind=TOOL_CALL, source=EXTERNAL_TOOL_RESULT` for a
    GitHub API response vs. `source=SUNIL_GENERATED` for parameters SUNIL
    itself constructed — rather than by adding a sixth `CaptureKind`.
    Accepted by `resolve_capture()`'s signature for forward compatibility;
    M1's own defaults (§13.2) do not yet vary by source, only by `kind`,
    so this parameter is recorded but does not change the M1 outcome —
    stated here so that is not mistaken for an oversight.
    """

    OWNER = "owner"
    AGENT = "agent"
    SUNIL_GENERATED = "sunil_generated"
    EXTERNAL_TOOL_RESULT = "external_tool_result"
    SYSTEM = "system"


class CaptureRule(NamedTuple):
    """The type that crosses the registry/persistence boundary — what
    `core/registry/capture.py` (T3) produces and
    `sunil.db.capture.resolve_capture()` (T2) accepts, per kind."""

    capture_policy: CapturePolicy
    sensitivity: Sensitivity
    retention_class: RetentionClass


@dataclass(frozen=True)
class CaptureDecision:
    """The four ADR-014 columns, resolved once at capture time."""

    capture_policy: CapturePolicy
    sensitivity: Sensitivity
    retention_class: RetentionClass
    training_eligible: bool
