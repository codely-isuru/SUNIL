"""Unit tests for `sunil.db.capture` — the ADR-014 training-data capture
resolver (T2). No database is needed: `resolve_capture()` and
`apply_capture_to_content()` are pure functions.

`CaptureKind`/`CapturePolicy`/etc. are imported from `sunil.db.capture`
(which itself imports them from the canonical top-level `sunil.capture`,
per ADR-014 Amendment 1) rather than from `sunil.capture` directly, so
this suite also proves the re-export keeps working for any caller that
imports the vocabulary from the persistence module by habit.
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
    """§13.2's table, verbatim, for every content kind except memory
    (which differs only in retention_class)."""
    for kind in (
        CaptureKind.MESSAGE,
        CaptureKind.PLAN,
        CaptureKind.LLM_CALL,
        CaptureKind.TOOL_CALL,
    ):
        decision = resolve_capture(kind=kind)
        assert decision.capture_policy is CapturePolicy.REDACTED_FULL
        assert decision.sensitivity is Sensitivity.INTERNAL
        assert decision.retention_class is RetentionClass.STANDARD
        assert decision.training_eligible is True


def test_memory_default_is_transient_not_standard() -> None:
    decision = resolve_capture(kind=CaptureKind.MEMORY)

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


def test_capture_kind_is_the_canonical_table_keyed_five_values() -> None:
    """ADR-014 Amendment 1: exactly the five values named there, one per
    capture table — not this module's earlier `tool_call_result` /
    `memory_short_term` split."""
    assert {member.value for member in CaptureKind} == {
        "message",
        "plan",
        "llm_call",
        "tool_call",
        "memory",
    }


def test_content_source_expresses_the_sub_case_the_old_second_kind_did() -> None:
    """Amendment 1: "T2's instinct was right and is preserved by the
    parameter that already existed for it" — `source`, not a sixth
    `CaptureKind`. `resolve_capture()` still accepts it (M1's own
    defaults do not vary by source yet, so the outcome is identical
    either way, but the call must not raise)."""
    from sunil.capture import ContentSource

    external = resolve_capture(
        kind=CaptureKind.TOOL_CALL, source=ContentSource.EXTERNAL_TOOL_RESULT
    )
    generated = resolve_capture(kind=CaptureKind.TOOL_CALL, source=ContentSource.SUNIL_GENERATED)

    assert external.capture_policy is CapturePolicy.REDACTED_FULL
    assert generated.capture_policy is CapturePolicy.REDACTED_FULL


def test_capture_rule_accepted_from_overrides_is_the_canonical_top_level_type() -> None:
    """The type that crosses the registry/persistence boundary is
    `sunil.capture.CaptureRule` — proven by importing it from there
    directly (not via `sunil.db.capture`'s re-export) and using it as an
    override, exactly the shape `core/registry/capture.py` (T3) will
    produce."""
    from sunil.capture import CaptureRule as TopLevelCaptureRule

    override = {
        CaptureKind.LLM_CALL: TopLevelCaptureRule(
            CapturePolicy.NONE, Sensitivity.RESTRICTED, RetentionClass.TRANSIENT
        )
    }

    decision = resolve_capture(kind=CaptureKind.LLM_CALL, overrides=override)

    assert decision.capture_policy is CapturePolicy.NONE
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


def test_apply_capture_to_content_passes_through_a_json_dict_unchanged() -> None:
    """Four of the five capture tables store content in a JSON column, not
    text (`plans.raw_json`, `llm_calls.request_messages`/`response_json`,
    `tool_calls.parameters`/`result`) — this must work for a dict/list
    payload exactly as it does for a plain string, with no separate code
    path, so a caller never has to hand-roll the nulling branch itself."""
    decision = CaptureDecision(
        capture_policy=CapturePolicy.REDACTED_FULL,
        sensitivity=Sensitivity.INTERNAL,
        retention_class=RetentionClass.STANDARD,
        training_eligible=True,
    )
    payload = {"role": "user", "content": "check on the project", "steps": [1, 2, 3]}

    assert apply_capture_to_content(decision, payload) == payload
    assert apply_capture_to_content(decision, payload) is payload


def test_apply_capture_to_content_nulls_a_json_dict_under_none_and_metadata_only() -> None:
    payload = {"parameters": {"owner": "codely-isuru", "repo": "easy_clean_workforce"}}

    for policy in (CapturePolicy.NONE, CapturePolicy.METADATA_ONLY):
        decision = CaptureDecision(
            capture_policy=policy,
            sensitivity=Sensitivity.INTERNAL,
            retention_class=RetentionClass.STANDARD,
            training_eligible=False,
        )
        assert apply_capture_to_content(decision, payload) is None


def test_apply_capture_to_content_passes_through_a_list_payload_unchanged() -> None:
    decision = CaptureDecision(
        capture_policy=CapturePolicy.REDACTED_FULL,
        sensitivity=Sensitivity.INTERNAL,
        retention_class=RetentionClass.STANDARD,
        training_eligible=True,
    )
    payload = [{"commit": "abc123", "title": "fix: something"}]

    assert apply_capture_to_content(decision, payload) == payload


def test_sunil_capture_imports_nothing_from_sunil() -> None:
    """ADR-014 Amendment 1: `sunil.capture` is a top-level leaf module,
    same status as `sunil.redaction` — vocabulary is domain language, not
    a persistence or registry detail, so it must not depend on either."""
    import ast
    from pathlib import Path

    import sunil.capture as capture_module

    source = Path(capture_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)

    offenders = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("sunil"):
            offenders.append(node.module)
        if isinstance(node, ast.Import):
            offenders.extend(alias.name for alias in node.names if alias.name.startswith("sunil"))

    assert not offenders, f"sunil.capture imports from sunil: {offenders}"
