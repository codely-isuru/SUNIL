"""Training-data capture policy — classify at capture time (ADR-014).

`resolve_capture()` is the one pure function the persistence layer calls to
decide, for a piece of content about to be written, what to store, how
sensitive it is, how long to keep it, and whether it may ever train a
model. It is never called by an agent — classification is a deterministic,
auditable decision, same as the permission engine's `decide()`.

Secret redaction (`sunil.redaction`, T4) answers "does this row contain a
credential?". This module answers a different question: "should this
row's *content* ever become training data?" Both are real controls; they
are not each other.

**What M1 actually enforces, stated per ADR-014's own table:** `none` and
`metadata_only` are enforced here — `apply_capture_to_content()` genuinely
nulls the content column. `redacted_full` (the M1 default) is today's
behaviour. `full_local_only` is *recorded, not enforced* — M1 has one
machine and no export path, so there is nothing yet to restrict; V2/V3's
export and training pipelines own the actual enforcement.

**On defaults and `config/capture.yaml` (T3, not yet built):** the
architecture (§13.2) has the registry loaders supply per-content-kind
defaults with a per-project override from `config/capture.yaml`. T2 has no
dependency on T3 (`docs/M1_BUILD_PLAN.md` §1.1's dependency table), so this
module ships the exact M1 defaults from `ARCHITECTURE_V1.md` §13.2 as a
built-in fallback table and accepts an optional `overrides` mapping with
the same shape `config/capture.yaml` will produce. Once T3's loader exists,
the persistence layer can pass its loaded config straight through this
same parameter with no change to this function's contract.
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
    """What kind of content is being captured — one member per capture
    table's content column (§13.2's "Content" rows)."""

    MESSAGE = "message"
    PLAN = "plan"
    LLM_CALL = "llm_call"
    TOOL_CALL_RESULT = "tool_call_result"
    MEMORY_SHORT_TERM = "memory_short_term"


class ContentSource(StrEnum):
    """Where the content originated. Part of `resolve_capture()`'s
    signature for forward compatibility (a later policy may vary by
    source); M1's own defaults (§13.2) do not vary by source, only by
    `kind`, so this parameter is accepted and recorded but does not change
    the M1 outcome — stated here so that is not mistaken for an oversight.
    """

    OWNER = "owner"
    AGENT = "agent"
    TOOL_EXTERNAL = "tool_external"
    SYSTEM = "system"


@dataclass(frozen=True)
class CaptureDecision:
    """The four ADR-014 columns, resolved once at capture time."""

    capture_policy: CapturePolicy
    sensitivity: Sensitivity
    retention_class: RetentionClass
    training_eligible: bool


class CaptureRule(NamedTuple):
    capture_policy: CapturePolicy
    sensitivity: Sensitivity
    retention_class: RetentionClass


# `ARCHITECTURE_V1.md` §13.2's M1 defaults table, verbatim. M1 ships
# exactly one project, so there is no per-project override table yet — the
# `overrides` parameter below exists for the moment `config/capture.yaml`
# lands (T3) and a second project needs a different rule.
_M1_DEFAULTS: dict[CaptureKind, CaptureRule] = {
    CaptureKind.MESSAGE: CaptureRule(
        CapturePolicy.REDACTED_FULL, Sensitivity.INTERNAL, RetentionClass.STANDARD
    ),
    CaptureKind.PLAN: CaptureRule(
        CapturePolicy.REDACTED_FULL, Sensitivity.INTERNAL, RetentionClass.STANDARD
    ),
    CaptureKind.LLM_CALL: CaptureRule(
        CapturePolicy.REDACTED_FULL, Sensitivity.INTERNAL, RetentionClass.STANDARD
    ),
    CaptureKind.TOOL_CALL_RESULT: CaptureRule(
        CapturePolicy.REDACTED_FULL, Sensitivity.INTERNAL, RetentionClass.STANDARD
    ),
    CaptureKind.MEMORY_SHORT_TERM: CaptureRule(
        CapturePolicy.REDACTED_FULL, Sensitivity.INTERNAL, RetentionClass.TRANSIENT
    ),
}


def _derive_training_eligible(policy: CapturePolicy, sensitivity: Sensitivity) -> bool:
    """`training_eligible` is derived, never hand-set (ADR-014 §3):
    `capture_policy in {redacted_full, full_local_only} and sensitivity in
    {public, internal}`. `full_local_only` constrains *where* training may
    happen, not *whether* — so it can still be eligible.
    """
    return policy in (
        CapturePolicy.REDACTED_FULL,
        CapturePolicy.FULL_LOCAL_ONLY,
    ) and sensitivity in (Sensitivity.PUBLIC, Sensitivity.INTERNAL)


def resolve_capture(
    *,
    kind: CaptureKind,
    project_key: str | None = None,
    agent_id: str | None = None,
    source: ContentSource = ContentSource.SYSTEM,
    overrides: dict[CaptureKind, CaptureRule] | None = None,
) -> CaptureDecision:
    """Classify a piece of content at capture time.

    `project_key` and `agent_id` are accepted now so a future per-project
    override (`config/capture.yaml`, T3) is an additive change to this
    function's body, not to its callers' call sites. `overrides` lets a
    caller that *has* loaded `config/capture.yaml` supply project-specific
    rules without this module depending on T3's registry loader.
    """
    del project_key, agent_id, source  # unused in M1's uniform defaults; see module docstring

    rule = (overrides or {}).get(kind) or _M1_DEFAULTS[kind]
    training_eligible = _derive_training_eligible(rule.capture_policy, rule.sensitivity)

    return CaptureDecision(
        capture_policy=rule.capture_policy,
        sensitivity=rule.sensitivity,
        retention_class=rule.retention_class,
        training_eligible=training_eligible,
    )


def apply_capture_to_content(decision: CaptureDecision, content: str | None) -> str | None:
    """The writer-side enforcement half of ADR-014.

    Returns `None` (so the column is written `NULL`) when the resolved
    policy is `none` or `metadata_only` — both are enforced in M1. Any
    other policy passes `content` through unchanged; redaction of secrets
    (§8.3, T4) is a separate step the persistence layer applies regardless
    of capture policy.
    """
    if decision.capture_policy in (CapturePolicy.NONE, CapturePolicy.METADATA_ONLY):
        return None
    return content
