"""ADR-014 / T-22 — the training-data capture policy.

Redaction answers "does this row contain a credential?". This answers a
different question: "should this row's content ever become training data?".
`none` and `metadata_only` are claimed **enforced**; `full_local_only` is
**recorded, not enforced** (DC-15). These tests hold that line in both
directions.

Rebased onto the integrated tree (T8 `cd92706` + T1 `5c08668` + T4 `c660bec`
+ T3 `1d97bb5`). The API this file originally assumed —
`apply_capture_policy(table=, policy=, payload=)` — never existed; T2 built
`resolve_capture()` + `apply_capture_to_content()`, and ADR-014 Amendment 1
moved the vocabulary to the leaf module `sunil.capture`. Where that was a
naming difference the tests now call what exists. Where it exposed a real gap
the test stays red and says why, because ADR-014's claim is what the code has
to meet.
"""

from __future__ import annotations

import ast

from security_helpers import REPO_ROOT, SUNIL_PKG, require

CONTENT = "a business-confidential sentence that contains no credential at all"


def _capture():
    return require("sunil.db.capture", "T2 (data layer, db/capture.py)")


def _vocab():
    return require("sunil.capture", "T3/T2 (ADR-014 Amendment 1 canonical vocabulary)")


def _decision(policy, sensitivity=None, *, eligible=False):
    v = _vocab()
    return v.CaptureDecision(
        capture_policy=policy,
        sensitivity=sensitivity or v.Sensitivity.INTERNAL,
        retention_class=v.RetentionClass.STANDARD,
        training_eligible=eligible,
    )


# ---------------------------------------------------------------------------
# The enforced half. Green.
# ---------------------------------------------------------------------------


def test_capture_policy_none_stores_no_content() -> None:
    """ADR-014: `none` — the row exists for audit/linkage only, content NULL."""
    capture, v = _capture(), _vocab()
    assert capture.apply_capture_to_content(_decision(v.CapturePolicy.NONE), CONTENT) is None


def test_capture_policy_metadata_only_stores_no_content() -> None:
    """ADR-014: `metadata_only` — retain shape, not substance."""
    capture, v = _capture(), _vocab()
    assert (
        capture.apply_capture_to_content(_decision(v.CapturePolicy.METADATA_ONLY), CONTENT) is None
    )


def test_redacted_full_retains_content_so_the_policies_actually_discriminate() -> None:
    """A function that nulled everything would pass both tests above and
    silently destroy the M1 default. Assert the discrimination, not just the
    suppression."""
    capture, v = _capture(), _vocab()
    assert capture.apply_capture_to_content(_decision(v.CapturePolicy.REDACTED_FULL), CONTENT) == (
        CONTENT
    )


def test_training_eligibility_is_derived_never_hand_set() -> None:
    """ADR-014 section 3, over the whole 4x4 policy/sensitivity space rather
    than one example: a human tightens the inputs, nobody hand-flips the
    output."""
    capture, v = _capture(), _vocab()
    for policy in v.CapturePolicy:
        for sensitivity in v.Sensitivity:
            rule = v.CaptureRule(policy, sensitivity, v.RetentionClass.STANDARD)
            got = capture.resolve_capture(
                kind=v.CaptureKind.MESSAGE, overrides={v.CaptureKind.MESSAGE: rule}
            ).training_eligible
            expected = policy in (
                v.CapturePolicy.REDACTED_FULL,
                v.CapturePolicy.FULL_LOCAL_ONLY,
            ) and sensitivity in (v.Sensitivity.PUBLIC, v.Sensitivity.INTERNAL)
            assert got is expected, f"{policy}/{sensitivity} -> {got}, ADR-014 derives {expected}"


def test_confidential_and_restricted_content_is_never_training_eligible() -> None:
    """The case ADR-014 exists for: a client's confidential material must not
    silently become fine-tuning corpus."""
    capture, v = _capture(), _vocab()
    for sensitivity in (v.Sensitivity.CONFIDENTIAL, v.Sensitivity.RESTRICTED):
        rule = v.CaptureRule(v.CapturePolicy.REDACTED_FULL, sensitivity, v.RetentionClass.STANDARD)
        decision = capture.resolve_capture(
            kind=v.CaptureKind.MESSAGE, overrides={v.CaptureKind.MESSAGE: rule}
        )
        assert decision.training_eligible is False


def test_audit_events_carries_no_capture_columns() -> None:
    """ADR-014 section 2 as a security property: a capture policy that could
    suppress audit rows would be a control capable of disabling a control, and
    ET-6 grades that table's completeness."""
    models = require("sunil.db.models", "T2")
    columns = {c.name for c in models.AuditEvent.__table__.columns}
    forbidden = {"capture_policy", "sensitivity", "retention_class", "training_eligible"}
    assert not (columns & forbidden), f"audit_events carries capture columns {columns & forbidden}"


def test_the_four_capture_columns_exist_on_the_five_capture_tables() -> None:
    models = require("sunil.db.models", "T2")
    expected = {"capture_policy", "sensitivity", "retention_class", "training_eligible"}
    for name in ("Message", "Plan", "LLMCall", "ToolCall", "Memory"):
        table = getattr(models, name).__table__
        missing = expected - {c.name for c in table.columns}
        assert not missing, f"{table.name} is missing capture columns: {sorted(missing)}"


def test_capture_columns_have_no_default_so_classification_cannot_be_skipped() -> None:
    """What makes "every record is classified at insert time" a mechanism
    rather than a hope: NOT NULL with no default, so an unclassified insert
    fails loudly instead of defaulting to something nobody decided."""
    models = require("sunil.db.models", "T2")
    for name in ("Message", "Plan", "LLMCall", "ToolCall", "Memory"):
        table = getattr(models, name).__table__
        for column_name in (
            "capture_policy",
            "sensitivity",
            "retention_class",
            "training_eligible",
        ):
            column = table.columns[column_name]
            assert not column.nullable, f"{table.name}.{column_name} is nullable"
            assert column.default is None and column.server_default is None, (
                f"{table.name}.{column_name} has a default — an omitted classification would "
                "silently become that default instead of failing"
            )


def test_full_local_only_is_recorded_and_not_claimed_as_enforced() -> None:
    """DC-15 / debt D-13. Asserts the *documented* state, so it fails the
    moment reality and the deferred-control register disagree either way."""
    capture, v = _capture(), _vocab()
    assert not hasattr(capture, "enforce_local_only"), (
        "an enforcement path for full_local_only exists while THREAT_MODEL DC-15 and ADR-014 "
        "both say it is recorded, not enforced — update the register or remove the code"
    )
    assert (
        capture.apply_capture_to_content(
            _decision(v.CapturePolicy.FULL_LOCAL_ONLY, eligible=True), CONTENT
        )
        == CONTENT
    )


# ---------------------------------------------------------------------------
# FINDINGS — kept red deliberately. These are not test bugs: what exists is
# narrower than what ADR-014 and M1_BUILD_PLAN T2 claim, and the first
# consumer has already had to work around it.
# ---------------------------------------------------------------------------

# The content column on each capture table, and its Python type. Four of the
# five are JSON, not text — which is the whole point of the test below.
CAPTURE_CONTENT_COLUMNS = {
    "Message": ("content", str),
    "Plan": ("plan_json", dict),
    "LLMCall": ("request_messages", list),
    "ToolCall": ("result", dict),
    "Memory": ("content", str),
}


def test_one_writer_path_can_null_content_on_every_capture_table() -> None:
    """FINDING, kept red. `M1_BUILD_PLAN.md` T2: db/capture.py holds "the
    resolver **and the writer behaviour that nulls content** under none /
    metadata_only". ADR-014: "Every record on the capture path is classified at
    insert time by **one resolver function**".

    `apply_capture_to_content(decision, content: str | None) -> str | None` can
    only serve a text column. Four of the five capture tables store their
    content in JSON columns, so the single writer path does not reach them —
    and T8, the first consumer, already hand-rolled its own copy rather than
    misuse the helper (`core/tool_framework/manager.py`, "typed for a single
    str column ... so the nulling is applied to the whole dict here").

    Two implementations of one control is the failure mode ADR-014's "one
    resolver function" exists to prevent, and each future writer (T11a
    messages, T6 llm_calls) faces the same mismatch. The fix is to widen the
    helper to any JSON-serialisable content, not to duplicate the branch.
    """
    capture, v = _capture(), _vocab()
    decision = _decision(v.CapturePolicy.NONE)

    unsupported = []
    for model_name, (column, py_type) in CAPTURE_CONTENT_COLUMNS.items():
        sample = {"k": "v"} if py_type is dict else ([{"k": "v"}] if py_type is list else CONTENT)
        try:
            result = capture.apply_capture_to_content(decision, sample)
        except Exception as exc:  # noqa: BLE001 - any failure is the finding
            unsupported.append(f"{model_name}.{column} ({py_type.__name__}): raised {exc!r}")
            continue
        if result is not None:
            unsupported.append(
                f"{model_name}.{column} ({py_type.__name__}): returned {result!r}, not None"
            )
    assert not unsupported, (
        "the single ADR-014 writer path cannot null these capture columns:\n  "
        + "\n  ".join(unsupported)
    )


def test_no_module_reimplements_the_capture_nulling_branch() -> None:
    """FINDING, kept red. The corollary of the test above: if the one writer
    path does not fit, callers re-implement it. This catches the copy by its
    shape — a membership test against the two enforced policy values that is
    not inside db/capture.py itself.

    T8's `manager.py` compares `decision.capture_policy.value in ("none",
    "metadata_only")` — stringly typed, so renaming a policy value would break
    it silently rather than at import.
    """
    offenders: list[str] = []
    for path in sorted(SUNIL_PKG.rglob("*.py")):
        if "__pycache__" in path.parts or path.name == "capture.py":
            continue
        text = path.read_text(encoding="utf-8")
        if '"none"' in text and '"metadata_only"' in text:
            rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
            line = text[: text.index('"metadata_only"')].count("\n") + 1
            offenders.append(f"{rel}:{line} re-implements the capture nulling branch")
    assert not offenders, (
        "the ADR-014 nulling decision is implemented outside db/capture.py:\n  "
        + "\n  ".join(offenders)
    )


def test_every_capture_call_site_uses_a_vocabulary_member_that_exists() -> None:
    """FINDING, kept red. ADR-014 Amendment 1 made `CaptureKind` table-keyed
    (`message plan llm_call tool_call memory`) and renamed `ContentSource`'s
    tool value to `external_tool_result`. Any call site still naming a removed
    member raises `AttributeError` at runtime, not at import — so it is invisible
    until the code path executes.

    T8's `_record()` is the *only* place a `tool_calls` row is written, so this
    is not cosmetic: it is ET-4's row and the tool-call audit trail.
    """
    v = _vocab()
    live = {
        "CaptureKind": {m.name for m in v.CaptureKind},
        "ContentSource": {m.name for m in v.ContentSource},
        "CapturePolicy": {m.name for m in v.CapturePolicy},
        "Sensitivity": {m.name for m in v.Sensitivity},
        "RetentionClass": {m.name for m in v.RetentionClass},
    }
    offenders: list[str] = []
    for path in sorted(SUNIL_PKG.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id in live
                and node.attr not in live[node.value.id]
                and not node.attr.startswith("_")
            ):
                rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
                offenders.append(
                    f"{rel}:{node.lineno} uses {node.value.id}.{node.attr}, which no longer exists "
                    f"(live members: {sorted(live[node.value.id])})"
                )
    assert not offenders, "dead capture-vocabulary members are still referenced:\n  " + "\n  ".join(
        offenders
    )
