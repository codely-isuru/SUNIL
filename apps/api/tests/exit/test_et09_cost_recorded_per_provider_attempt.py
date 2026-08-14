"""ET-9 — docs/REQUIREMENTS_V1.md §7, clarified by the brief:
"A cost/usage record (NFR-030) exists for every LLM call made during the request, with
non-zero token counts." Clarified: "every LLM call" reads as "every **provider
attempt**" (A-2) -- never a hard-coded count, because a single retry breaks it
(docs/M1_BUILD_PLAN.md §0.2 rule 8, ARCHITECTURE_V1.md §1.1/ADR-015).

Coverage map: made passable by T2 + T6.

Two tests:
  * the happy path asserts shape/relationships only (`purpose` set, `>= 1` per purpose,
    non-zero tokens, `usage` sums the rows) -- no magic numbers.
  * a SEPARATE, scripted-retry scenario legitimately asserts an exact count, because
    the test itself dictates the retry script (1 forced transient failure + 1 success
    for `plan`) -- proving the harness would actually catch a hard-coded "exactly N"
    regression, which is the whole point of the interpretation rule.
"""

from __future__ import annotations

from tests.exit._client import app_client, login, post_chat, run_migrations, seed_owner
from tests.exit._contract import M1_LLM_PURPOSES, NEVER_WRITTEN_IN_M1_PURPOSE
from tests.exit._db import llm_calls_for_request
from tests.exit._mock_upstreams import anthropic_success, anthropic_transient_error
from tests.exit._plans import valid_plan_json
from tests.exit._scenarios import run_completed_turn
from tests.exit.conftest import script_clean_github_activity


def test_et9_cost_recorded_for_every_provider_attempt_no_magic_numbers(
    db_path, database_url, qa_config_dir, monkeypatch, mock_server, request_id
):
    resp = run_completed_turn(
        db_path=db_path,
        database_url=database_url,
        config_dir=qa_config_dir,
        monkeypatch=monkeypatch,
        mock_server=mock_server,
        request_id=request_id,
    )
    assert resp.status_code == 200, (
        f"unexpected status {resp.status_code}: {resp.text[:500]}"
    )
    body = resp.json()
    assert body["outcome"] == "ok", (
        f"expected outcome=ok, got {body.get('outcome')}: {body.get('failure')}"
    )

    all_calls = llm_calls_for_request(db_path, request_id)
    # Never "== 3" or any other fixed total -- shape and relationships only.
    assert len(all_calls) >= 2, (
        f"expected at least 2 provider attempts (>=1 plan, >=1 analysis), got {len(all_calls)}"
    )

    purposes_seen = {c["purpose"] for c in all_calls}
    assert purposes_seen <= set(M1_LLM_PURPOSES), (
        f"M1 must write purpose in {M1_LLM_PURPOSES} only, saw: {purposes_seen}"
    )
    assert NEVER_WRITTEN_IN_M1_PURPOSE not in purposes_seen, (
        f"ADR-015: M1 never writes purpose={NEVER_WRITTEN_IN_M1_PURPOSE!r} (final_response is deterministic, not an LLM call)"
    )
    for required in ("plan", "analysis"):
        matching = [c for c in all_calls if c["purpose"] == required]
        assert len(matching) >= 1, (
            f"expected at least one llm_calls row with purpose={required!r}"
        )

    for call in all_calls:
        assert (call["input_tokens"] or 0) > 0, (
            f"expected non-zero input_tokens, got row: {call}"
        )
        assert (call["output_tokens"] or 0) > 0, (
            f"expected non-zero output_tokens, got row: {call}"
        )
        assert call["cost_micro_usd"] is not None, (
            f"expected a non-null cost_micro_usd, got row: {call}"
        )
        assert call["provider"], "provider must be recorded"
        assert call["model"], "model must be recorded"

    # usage sums ALL provider attempts in the turn (§6: "usage sums all provider
    # attempts... including failed ones that consumed input tokens").
    usage = body["usage"]
    assert usage["input_tokens"] == sum(c["input_tokens"] for c in all_calls)
    assert usage["output_tokens"] == sum(c["output_tokens"] for c in all_calls)


def test_et9_a_scripted_retry_produces_exactly_the_rows_the_script_dictates(
    db_path, database_url, qa_config_dir, monkeypatch, mock_server, request_id
):
    """This scenario is fully test-controlled (1 forced transient failure then 1
    success for `plan`, 1 success for `analysis`), so an exact count IS the right
    assertion here -- proving this harness would fail loudly if a real retry ever broke
    a hard-coded "exactly 3" elsewhere (A-2's whole point)."""
    run_migrations(database_url, monkeypatch=monkeypatch)
    seed_owner(db_path)
    script_clean_github_activity(mock_server)
    mock_server.script("POST", "/v1/messages", anthropic_transient_error(status=500))
    mock_server.script(
        "POST", "/v1/messages", anthropic_success(text=valid_plan_json())
    )
    mock_server.script(
        "POST",
        "/v1/messages",
        anthropic_success(text="Quiet week on EasyClean Workforce."),
    )

    with app_client(
        database_url=database_url,
        config_dir=qa_config_dir,
        monkeypatch=monkeypatch,
        anthropic_base_url=mock_server.base_url,
        github_api_base_url=mock_server.base_url,
    ) as client:
        login(client)
        resp = post_chat(
            client, message="Check on EasyClean Workforce", request_id=request_id
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"] == "ok", (
        f"expected recovery to succeed, got {body.get('outcome')}: {body.get('failure')}"
    )

    plan_calls = llm_calls_for_request(db_path, request_id, purpose="plan")
    analysis_calls = llm_calls_for_request(db_path, request_id, purpose="analysis")
    assert len(plan_calls) == 2, (
        f"this exact scenario scripts 1 failure + 1 success for plan: got {len(plan_calls)}"
    )
    assert len(analysis_calls) == 1, (
        f"this exact scenario scripts 1 success for analysis: got {len(analysis_calls)}"
    )

    failed_attempt = [c for c in plan_calls if (c["error_kind"] is not None)]
    succeeded_attempt = [c for c in plan_calls if c["error_kind"] is None]
    assert len(failed_attempt) == 1 and len(succeeded_attempt) == 1, (
        f"expected exactly one failed + one successful plan attempt, got error_kinds: {[c['error_kind'] for c in plan_calls]}"
    )
