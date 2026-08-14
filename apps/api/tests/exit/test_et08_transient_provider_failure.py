"""ET-8 — docs/REQUIREMENTS_V1.md §7:
"A fault-injected transient provider failure either recovers via retry (NFR-070) or
fails cleanly with a user-visible error and a `failed` audit terminal state (NFR-071)
-- no silent failure, no crash."

Coverage map: made passable by T6 + T11b.

Three scenarios, matching docs/M1_BUILD_PLAN.md T18's own list ("transient-then-success
... a transient-forever mode for the turn-deadline path"):
  1. recovers via retry
  2. exhausts all 3 attempts (ADR-000 Q6) and fails cleanly as `provider_error`
  3. the §5.3 turn deadline is breached and *also* maps to `provider_error` (no new
     failure kind) -- ASSUMPTION flagged inline: forcing this deterministically means
     overriding `SUNIL_TURN_DEADLINE_S` to ~0 via env var and trusting Settings is read
     fresh per `create_app()` call (see `_client.py`'s module docstring, assumption 1).
     If that assumption is wrong this scenario will need rework once T1/T6 exist; it
     does not affect scenarios 1-2.

500 is used as the transient status throughout (verified: real anthropic SDK 0.122.0
raises `InternalServerError` for it, which ARCHITECTURE_V1.md §4.3 maps to
`ProviderTransientError` -- see `_mock_upstreams.py`'s module docstring for the
verification transcript).
"""

from __future__ import annotations

from tests.exit._client import app_client, login, post_chat, run_migrations, seed_owner
from tests.exit._db import (
    audit_stages_for_request,
    count_for_request,
    llm_calls_for_request,
    task_for_request,
)
from tests.exit._mock_upstreams import anthropic_success, anthropic_transient_error
from tests.exit._plans import valid_plan_json
from tests.exit.conftest import script_clean_github_activity


def test_et8_recovers_via_retry_and_completes_the_turn(
    db_path, database_url, qa_config_dir, monkeypatch, mock_server, request_id
):
    run_migrations(database_url, monkeypatch=monkeypatch)
    seed_owner(db_path)
    script_clean_github_activity(mock_server)
    # attempt 1 (plan): transient failure; attempt 2 (plan): success; then analysis.
    mock_server.script("POST", "/v1/messages", anthropic_transient_error(status=500))
    mock_server.script(
        "POST", "/v1/messages", anthropic_success(text=valid_plan_json())
    )
    mock_server.script(
        "POST",
        "/v1/messages",
        anthropic_success(text="All quiet on EasyClean Workforce."),
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

    assert resp.status_code == 200, (
        f"unexpected status {resp.status_code}: {resp.text[:500]}"
    )
    body = resp.json()
    assert body["outcome"] == "ok", (
        f"expected the turn to recover and succeed, got {body.get('outcome')}: {body.get('failure')}"
    )

    plan_calls = llm_calls_for_request(db_path, request_id, purpose="plan")
    assert len(plan_calls) >= 2, (
        f"expected at least 2 provider attempts for `plan` (1 failed + 1 succeeded), got {len(plan_calls)}"
    )
    assert count_for_request(db_path, "tool_calls", request_id) == 1, (
        "the turn must still complete the one expected tool call"
    )


def test_et8_exhausted_retries_fail_cleanly_with_terminal_failed_state(
    db_path, database_url, qa_config_dir, monkeypatch, mock_server, request_id
):
    run_migrations(database_url, monkeypatch=monkeypatch)
    seed_owner(db_path)
    # Every attempt fails the same way (ScriptedHTTPServer holds a single scripted
    # response constant when only one is queued) -- exercises full exhaustion, not a
    # lucky recovery.
    mock_server.script("POST", "/v1/messages", anthropic_transient_error(status=500))

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

    assert resp.status_code == 200, (
        "a cleanly-failed turn is still HTTP 200 with a discriminated outcome (§6)"
    )
    body = resp.json()
    assert body["outcome"] == "failed", (
        f"expected outcome=failed, got {body.get('outcome')}"
    )
    assert body["failure"]["kind"] == "provider_error", (
        f"expected failure.kind=provider_error, got {body['failure']}"
    )

    # Bounded at exactly 3 attempts (ADR-000 Q6 / ARCHITECTURE_V1.md §4.5) -- this one
    # scenario legitimately hard-codes a count, because the test itself dictates "always
    # fail" and the number under test IS the retry bound, not an incidental detail
    # (contrast with ET-9, which never hard-codes a count for an uncontrolled path).
    plan_calls = llm_calls_for_request(db_path, request_id, purpose="plan")
    assert len(plan_calls) == 3, (
        f"expected exactly 3 provider attempts (the documented bound), got {len(plan_calls)}"
    )

    assert count_for_request(db_path, "tool_calls", request_id) == 0, (
        "no tool call should ever happen after total provider exhaustion"
    )

    task = task_for_request(db_path, request_id)
    assert task is not None and task["status"] == "failed", (
        f"expected a terminal `failed` task status, got {task}"
    )

    # "No silent failure": stage 12 must still fire even on this failure path.
    stages = [r["stage"] for r in audit_stages_for_request(db_path, request_id)]
    assert "final_response" in stages, (
        f"a failed turn must still emit the final_response stage, got: {stages}"
    )


def test_et8_turn_deadline_breach_also_maps_to_provider_error(
    db_path, database_url, qa_config_dir, monkeypatch, mock_server, request_id
):
    """ASSUMPTION (flagged in the T18 report): forcing the §5.3 deadline path
    deterministically requires `SUNIL_TURN_DEADLINE_S` to be re-read per `create_app()`
    call, which is not guaranteed by anything in the frozen contract. If wrong, this one
    test needs rework once T1/T6 land -- it is isolated to this function only.
    """
    run_migrations(database_url, monkeypatch=monkeypatch)
    seed_owner(db_path)
    mock_server.script("POST", "/v1/messages", anthropic_transient_error(status=500))

    with app_client(
        database_url=database_url,
        config_dir=qa_config_dir,
        monkeypatch=monkeypatch,
        anthropic_base_url=mock_server.base_url,
        github_api_base_url=mock_server.base_url,
        extra_env={"SUNIL_TURN_DEADLINE_S": "0"},
    ) as client:
        login(client)
        resp = post_chat(
            client, message="Check on EasyClean Workforce", request_id=request_id
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"] == "failed", (
        f"expected outcome=failed on deadline breach, got {body.get('outcome')}"
    )
    assert body["failure"]["kind"] == "provider_error", (
        f"the turn-deadline breach must map to provider_error, not a new failure kind "
        f"(ARCHITECTURE_V1.md §5.3/§11.3): got {body['failure']}"
    )
    stages = [r["stage"] for r in audit_stages_for_request(db_path, request_id)]
    assert "final_response" in stages, (
        f"a deadline-failed turn must still emit final_response, got: {stages}"
    )
    print(
        "ET-8 deadline scenario failure detail:", body["failure"]
    )  # informative only, not asserted on
