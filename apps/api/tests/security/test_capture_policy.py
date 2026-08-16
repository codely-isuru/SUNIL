"""ADR-014 / T-22 — the training-data capture policy.

The point of ADR-014 is that redaction answers "does this row contain a
credential?" and nothing answers "should this row ever become training data?".
The policy is claimed to be *enforced* for `none` and `metadata_only`, and
*recorded only* for `full_local_only` (DC-15). These tests hold that line in
both directions: they prove the enforced half works, and they prove nobody has
quietly started treating the unenforced half as working.

RED until T2 (columns + writer) and T3 (config/capture.yaml).
"""

from __future__ import annotations

from conftest import require

CONTENT = "a business-confidential sentence that contains no credential at all"


def test_capture_policy_none_stores_no_content() -> None:
    """ADR-014 section 1: `none` — "the row exists for audit/linkage only".
    Content columns written NULL."""
    capture = require("sunil.db.capture", "T2 (data layer, db/capture.py)")

    row = capture.apply_capture_policy(
        table="messages", policy="none", payload={"content": CONTENT, "id": "m1"}
    )
    assert row["content"] is None, f"policy `none` retained content: {row}"
    assert row["id"] == "m1", "linkage columns must survive — the row still exists for audit"


def test_capture_policy_metadata_only_stores_no_content() -> None:
    """ADR-014 section 1: `metadata_only` — "retain shape, not substance"."""
    capture = require("sunil.db.capture", "T2")

    row = capture.apply_capture_policy(
        table="llm_calls",
        policy="metadata_only",
        payload={
            "request_messages": [{"role": "user", "content": CONTENT}],
            "response_text": CONTENT,
            "input_tokens": 120,
            "cost_micro_usd": 4200,
        },
    )
    assert row["request_messages"] is None
    assert row["response_text"] is None
    assert row["input_tokens"] == 120, "metadata (shape) must be retained"
    assert row["cost_micro_usd"] == 4200


def test_audit_events_are_never_suppressed_by_capture_policy() -> None:
    """ADR-014 section 2, stated as a security property rather than a schema
    note: "A capture policy that could suppress audit rows would be a control
    capable of disabling a control, and ET-6 grades that table completeness."

    Two halves: audit_events must carry none of the four columns, and applying
    the most restrictive policy to it must not remove the row.
    """
    capture = require("sunil.db.capture", "T2")
    models = require("sunil.db.models", "T2")

    columns = {c.name for c in models.AuditEvent.__table__.columns}
    forbidden = {"capture_policy", "sensitivity", "retention_class", "training_eligible"}
    assert not (columns & forbidden), (
        f"audit_events carries capture columns {columns & forbidden} — a capture policy could "
        "then disable the audit trail that ET-6 is graded on"
    )

    row = capture.apply_capture_policy(
        table="audit_events", policy="none", payload={"stage": "tool_requested", "seq": 8}
    )
    assert row["stage"] == "tool_requested", "a capture policy suppressed an audit row"
    assert row["seq"] == 8


def test_the_four_capture_columns_exist_on_exactly_the_five_capture_tables() -> None:
    """ADR-014 section 2 — on messages, plans, llm_calls, tool_calls, memories,
    and nowhere else."""
    models = require("sunil.db.models", "T2")

    expected = {"capture_policy", "sensitivity", "retention_class", "training_eligible"}
    for name in ("Message", "Plan", "LLMCall", "ToolCall", "Memory"):
        table = getattr(models, name).__table__
        missing = expected - {c.name for c in table.columns}
        assert not missing, f"{table.name} is missing capture columns: {sorted(missing)}"


def test_training_eligibility_is_derived_never_hand_set() -> None:
    """ADR-014 section 3: "A human can tighten the inputs; nobody hand-flips
    the output." A settable boolean is a policy that can be talked out of."""
    capture = require("sunil.db.capture", "T2")

    eligible = capture.resolve_capture(kind="message", project_key="easy_clean_workforce")
    assert eligible.training_eligible == (
        eligible.capture_policy in {"redacted_full", "full_local_only"}
        and eligible.sensitivity in {"public", "internal"}
    )

    restricted = capture.resolve_capture(
        kind="message", project_key="easy_clean_workforce", sensitivity="restricted"
    )
    assert restricted.training_eligible is False


def test_full_local_only_is_recorded_and_not_claimed_as_enforced() -> None:
    """DC-15 and debt D-13. THREAT_MODEL section 10: "`full_local_only` is a
    recorded intention until V3". If someone later builds an export path, this
    test is where the omission surfaces — it asserts the *documented* state, so
    it fails the moment reality and the register disagree in either direction.
    """
    capture = require("sunil.db.capture", "T2")

    assert not hasattr(capture, "enforce_local_only"), (
        "an enforcement path for full_local_only exists in code while THREAT_MODEL DC-15 and "
        "ADR-014 both say it is recorded, not enforced — update the register or remove the code"
    )
    row = capture.apply_capture_policy(
        table="messages", policy="full_local_only", payload={"content": CONTENT, "id": "m2"}
    )
    assert row["content"] == CONTENT, "full_local_only is documented as retaining full content"
