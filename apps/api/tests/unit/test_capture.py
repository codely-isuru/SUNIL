"""Unit tests for `sunil.db.capture` — the ADR-014 training-data capture
resolver (T2). No database is needed: `resolve_capture()` and
`apply_capture_to_content()` are pure functions.
"""

from __future__ import annotations

from sunil.db.capture import (
    CaptureDecision,
    CaptureKind,
    CapturePolicy,
    CaptureRule,
    RetentionClass,
    Sensitivity,
    apply_capture_to_content,
    resolve_capture,
)


def test_m1_defaults_match_architecture_v1_section_13_2() -> None:
    """§13.2's table, verbatim, for every content kind except short-term
    memory (which differs only in retention_class)."""
    for kind in (
        CaptureKind.MESSAGE,
        CaptureKind.PLAN,
        CaptureKind.LLM_CALL,
        CaptureKind.TOOL_CALL_RESULT,
    ):
        decision = resolve_capture(kind=kind)
        assert decision.capture_policy is CapturePolicy.REDACTED_FULL
        assert decision.sensitivity is Sensitivity.INTERNAL
        assert decision.retention_class is RetentionClass.STANDARD
        assert decision.training_eligible is True


def test_short_term_memory_default_is_transient_not_standard() -> None:
    decision = resolve_capture(kind=CaptureKind.MEMORY_SHORT_TERM)

    assert decision.capture_policy is CapturePolicy.REDACTED_FULL
    assert decision.retention_class is RetentionClass.TRANSIENT
    assert decision.training_eligible is True


def test_training_eligible_is_false_when_sensitivity_is_confidential() -> None:
    """ADR-014 §3: `training_eligible` is derived, never hand-set. A
    `redacted_full` policy is not sufficient on its own if the content is
    not `public`/`internal`."""
    override = {
        CaptureKind.MESSAGE: CaptureRule(
            CapturePolicy.REDACTED_FULL, Sensitivity.CONFIDENTIAL, RetentionClass.STANDARD
        )
    }

    decision = resolve_capture(kind=CaptureKind.MESSAGE, overrides=override)

    assert decision.capture_policy is CapturePolicy.REDACTED_FULL
    assert decision.sensitivity is Sensitivity.CONFIDENTIAL
    assert decision.training_eligible is False


def test_full_local_only_can_still_be_training_eligible() -> None:
    """ADR-014 §3: `full_local_only` constrains *where* training may
    happen, not *whether* — so with an eligible sensitivity it is still
    `training_eligible = True`."""
    override = {
        CaptureKind.MESSAGE: CaptureRule(
            CapturePolicy.FULL_LOCAL_ONLY, Sensitivity.INTERNAL, RetentionClass.STANDARD
        )
    }

    decision = resolve_capture(kind=CaptureKind.MESSAGE, overrides=override)

    assert decision.training_eligible is True


def test_overrides_take_precedence_over_the_builtin_m1_defaults() -> None:
    """Once config/capture.yaml (T3) is wired in, its loaded rules must
    win over this module's built-in fallback — proven here with a fake
    override standing in for that future config."""
    override = {
        CaptureKind.PLAN: CaptureRule(
            CapturePolicy.METADATA_ONLY, Sensitivity.CONFIDENTIAL, RetentionClass.LONG
        )
    }

    decision = resolve_capture(kind=CaptureKind.PLAN, overrides=override)

    assert decision.capture_policy is CapturePolicy.METADATA_ONLY
    assert decision.retention_class is RetentionClass.LONG
    assert decision.training_eligible is False


def test_apply_capture_to_content_nulls_under_none_and_metadata_only() -> None:
    for policy in (CapturePolicy.NONE, CapturePolicy.METADATA_ONLY):
        decision = CaptureDecision(
            capture_policy=policy,
            sensitivity=Sensitivity.INTERNAL,
            retention_class=RetentionClass.STANDARD,
            training_eligible=False,
        )
        assert apply_capture_to_content(decision, "some real content") is None


def test_apply_capture_to_content_passes_through_under_redacted_full() -> None:
    decision = CaptureDecision(
        capture_policy=CapturePolicy.REDACTED_FULL,
        sensitivity=Sensitivity.INTERNAL,
        retention_class=RetentionClass.STANDARD,
        training_eligible=True,
    )
    assert apply_capture_to_content(decision, "some real content") == "some real content"


def test_apply_capture_to_content_passes_through_under_full_local_only() -> None:
    decision = CaptureDecision(
        capture_policy=CapturePolicy.FULL_LOCAL_ONLY,
        sensitivity=Sensitivity.INTERNAL,
        retention_class=RetentionClass.STANDARD,
        training_eligible=True,
    )
    assert apply_capture_to_content(decision, "some real content") == "some real content"


def test_apply_capture_to_content_handles_none_content_gracefully() -> None:
    decision = CaptureDecision(
        capture_policy=CapturePolicy.REDACTED_FULL,
        sensitivity=Sensitivity.INTERNAL,
        retention_class=RetentionClass.STANDARD,
        training_eligible=True,
    )
    assert apply_capture_to_content(decision, None) is None
