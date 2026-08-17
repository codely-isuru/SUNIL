"""ET-7 — docs/REQUIREMENTS_V1.md §7:
"A fault-injected malformed/unvalidatable LLM plan output never results in a tool call
(zero ToolCall records created)."

Coverage map: made passable by T9. Also ARCHITECTURE_V1.md §6.3's
`test_malformed_llm_output_creates_zero_tool_calls`.

Two independent ways a plan can be rejected, both exercised: non-JSON text (what Layer
2 -- "the provider never guesses" -- exists for, simulating a hypothetical failure of
the real constrained-decoding guarantee), and syntactically-valid JSON that the
registry re-check (Layer 4) must still reject (an unregistered agent name). Bounded
retry is 3 plan attempts (ADR-000 Q6) -- the mock server returns the SAME malformed
response for every attempt (see `ScriptedHTTPServer`'s "hold constant if only one is
scripted" behaviour), so this exercises exhaustion, not a lucky first-attempt reject.
"""

from __future__ import annotations

from tests.exit._client import (
    app_client,
    build_settings,
    login,
    post_chat,
    run_migrations,
    seed_owner_directly,
)
from tests.exit._db import count_for_request, plans_for_request
from tests.exit._mock_upstreams import anthropic_success
from tests.exit._plans import malformed_plan_text, plan_with_unregistered_agent_json


def _run_turn_with_malformed_plan(
    db_path,
    database_url,
    qa_config_dir,
    monkeypatch,
    mock_server,
    request_id,
    plan_text,
):
    run_migrations(database_url, monkeypatch=monkeypatch)
    seed_owner_directly(db_path)
    mock_server.script("POST", "/v1/messages", anthropic_success(text=plan_text))

    settings = build_settings(
        database_url=database_url,
        config_dir=qa_config_dir,
        anthropic_base_url=mock_server.base_url,
        github_api_base_url=mock_server.base_url,
    )
    with app_client(settings=settings) as client:
        login(client)
        return post_chat(client, message="Check on EasyClean Workforce", request_id=request_id)


def test_et7_non_json_plan_output_yields_zero_tool_calls(
    db_path, database_url, qa_config_dir, monkeypatch, mock_server, request_id
):
    resp = _run_turn_with_malformed_plan(
        db_path,
        database_url,
        qa_config_dir,
        monkeypatch,
        mock_server,
        request_id,
        malformed_plan_text(),
    )
    assert resp.status_code == 200, (
        f"a rejected plan is still a valid HTTP transaction (§6): got {resp.status_code}"
    )
    body = resp.json()
    assert body["outcome"] == "failed", f"expected outcome=failed, got {body.get('outcome')}"
    assert body["failure"]["kind"] == "plan_rejected", (
        f"expected failure.kind=plan_rejected, got {body['failure']}"
    )

    assert count_for_request(db_path, "tool_calls", request_id) == 0, (
        "zero tool_calls rows must exist for a rejected plan"
    )

    plans = plans_for_request(db_path, request_id)
    assert plans, (
        "rejected plan attempts must still be persisted "
        "(ARCHITECTURE_V1.md §6.2 -- evidence, not a lost log line)"
    )
    assert all(p["validated"] in (0, False) for p in plans), (
        f"no plan attempt should be marked validated: {plans}"
    )


def test_et7_plan_naming_an_unregistered_agent_yields_zero_tool_calls(
    db_path, database_url, qa_config_dir, monkeypatch, mock_server, request_id
):
    resp = _run_turn_with_malformed_plan(
        db_path,
        database_url,
        qa_config_dir,
        monkeypatch,
        mock_server,
        request_id,
        plan_with_unregistered_agent_json(),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"] == "failed", f"expected outcome=failed, got {body.get('outcome')}"
    assert body["failure"]["kind"] == "plan_rejected", (
        f"expected failure.kind=plan_rejected, got {body['failure']}"
    )
    assert count_for_request(db_path, "tool_calls", request_id) == 0, (
        "a plan naming an agent absent from the registry must never reach a tool call (FR-061)"
    )
