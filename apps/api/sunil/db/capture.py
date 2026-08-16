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

**The vocabulary lives in `sunil.capture`** (ADR-014 Amendment 1), a
top-level leaf this module imports rather than redefines — see that
module's docstring for why (a cross-lane type mismatch between this file
and `core/registry/capture.py`, T3, was the defect Amendment 1 fixes).
This module does not define `CaptureKind`, `CapturePolicy`, `Sensitivity`,
`RetentionClass`, `ContentSource`, `CaptureRule` or `CaptureDecision`
itself; it only imports and uses them.

**On defaults and `config/capture.yaml` (T3):** the architecture (§13.2)
has the registry loaders supply per-content-kind defaults, converted to
`CaptureRule` (T3's `core/registry/capture.py` is the only place a raw
YAML string becomes one of these enums — this module never does that
conversion). This module ships the exact M1 defaults from
`ARCHITECTURE_V1.md` §13.2 as a built-in fallback table and accepts an
`overrides: Mapping[CaptureKind, CaptureRule]` parameter with exactly the
shape `core/registry/capture.py` produces, so wiring the real registry in
is a call-site change, not a contract change.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sunil.capture import (
    CaptureDecision,
    CaptureKind,
    CapturePolicy,
    CaptureRule,
    ContentSource,
    RetentionClass,
    Sensitivity,
)

__all__ = [
    "CaptureDecision",
    "CaptureKind",
    "CapturePolicy",
    "CaptureRule",
    "ContentSource",
    "RetentionClass",
    "Sensitivity",
    "apply_capture_to_content",
    "resolve_capture",
]

# `ARCHITECTURE_V1.md` §13.2's M1 defaults table, verbatim — and matching
# `config/capture.yaml`'s own committed defaults (T3) value for value. M1
# ships exactly one project, so there is no per-project override table
# yet — the `overrides` parameter below exists for the moment a second
# project needs a different rule.
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
    CaptureKind.TOOL_CALL: CaptureRule(
        CapturePolicy.REDACTED_FULL, Sensitivity.INTERNAL, RetentionClass.STANDARD
    ),
    CaptureKind.MEMORY: CaptureRule(
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
    overrides: Mapping[CaptureKind, CaptureRule] | None = None,
) -> CaptureDecision:
    """Classify a piece of content at capture time.

    `project_key` and `agent_id` are accepted now so a future per-project
    override (`config/capture.yaml`, T3) is an additive change to this
    function's body, not to its callers' call sites. `overrides` lets a
    caller that *has* loaded `config/capture.yaml` (via
    `core/registry/capture.py`) supply project-specific rules without this
    module depending on T3's registry loader directly.
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


def apply_capture_to_content(decision: CaptureDecision, content: Any) -> Any:
    """The writer-side enforcement half of ADR-014.

    Returns `None` (so the column is written `NULL`) when the resolved
    policy is `none` or `metadata_only` — both are enforced in M1. Any
    other policy passes `content` through unchanged; redaction of secrets
    (§8.3, T4) is a separate step the persistence layer applies regardless
    of capture policy.

    **`content` is deliberately untyped beyond `Any`.** Four of the five
    capture tables store their content in a JSON column, not text —
    `plans.raw_json`, `llm_calls.request_messages`/`response_json`,
    `tool_calls.parameters`/`result` — only `messages.content` and
    `memories.content` are plain `str`. This function never inspects
    `content`'s shape, only the resolved `decision`, so one code path is
    correct for both already; a narrower `str | None` annotation here
    previously caused a caller to conclude it *couldn't* be used for a
    dict/list column and hand-roll the same nulling branch itself,
    stringly-typed, outside this module — which is exactly the drift a
    shared helper exists to prevent. Call this for every capture-table
    write, whatever the column's shape.
    """
    if decision.capture_policy in (CapturePolicy.NONE, CapturePolicy.METADATA_ONLY):
        return None
    return content
