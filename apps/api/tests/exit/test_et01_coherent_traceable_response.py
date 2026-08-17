"""ET-1 — docs/REQUIREMENTS_V1.md §7:
"Given the chat UI, When the owner sends 'Check project <configured project>', Then
SUNIL returns a coherent natural-language status response within the NFR-060 latency
target, and that response's content is traceable to real data returned by the M1 tool
(not fabricated)."

Coverage map (docs/M1_BUILD_PLAN.md §7): made passable by T8 + T10 + T11b + T16.

Two tests:
  * `test_et1_fixture_response_traces_to_tool_result` — no live credentials needed;
    drives the whole stack through the local mock upstream server (see
    `tests/exit/_mock_upstreams.py`), wired via a fresh `Settings` instance per
    ADR-017/018. Proves the WIRING: the tool result actually reaches the analysis
    call, and the analysis call's own output becomes the user-facing message
    (ADR-015), by scripting exactly what the "model" says and checking it comes back
    unchanged, while the tool data that was *available* to it is verified present in
    the persisted `llm_calls` prompt.
  * `test_et1_live_end_to_end_real_data` — `@pytest.mark.live`. This is the only way to
    honestly test the "not fabricated" / "real data" clause against the real GitHub API
    and the real Claude API. BLOCKED until Day 3 (ANTHROPIC_API_KEY + GITHUB_TOKEN).
"""

from __future__ import annotations

import time

import pytest

from tests.exit._client import (
    app_client,
    build_live_settings,
    build_settings,
    login,
    post_chat,
    run_migrations,
    seed_owner_directly,
)
from tests.exit._db import llm_calls_for_request
from tests.exit._mock_upstreams import openai_success
from tests.exit._plans import valid_plan_json
from tests.exit.conftest import script_clean_github_activity


def test_et1_fixture_response_traces_to_tool_result(
    db_path, database_url, qa_config_dir, monkeypatch, mock_server, request_id
):
    run_migrations(database_url, monkeypatch=monkeypatch)
    seed_owner_directly(db_path)
    script_clean_github_activity(mock_server)

    analysis_text = (
        "EasyClean Workforce has had steady activity: three recent commits including a "
        "CSV export feature, two open pull requests (one adding CSV export, one fixing "
        "a scheduler timezone bug), and one open issue about invoice rounding. Nothing "
        "looks urgent, but the rounding issue is worth a look."
    )
    mock_server.script("POST", "/v1/chat/completions", openai_success(text=valid_plan_json()))
    mock_server.script("POST", "/v1/chat/completions", openai_success(text=analysis_text))

    settings = build_settings(
        database_url=database_url,
        config_dir=qa_config_dir,
        anthropic_base_url=mock_server.base_url,
        github_api_base_url=mock_server.base_url,
        # T24: general_reasoning now resolves to openai; /v1 is not optional --
        # see _scenarios.py's run_completed_turn() comment for why.
        openai_base_url=f"{mock_server.base_url}/v1",
    )
    with app_client(settings=settings) as client:
        login(client)
        resp = post_chat(client, message="Check on EasyClean Workforce", request_id=request_id)

    assert resp.status_code == 200, f"unexpected status {resp.status_code}: {resp.text[:500]}"
    body = resp.json()
    assert body["outcome"] == "ok", (
        f"expected outcome=ok, got {body.get('outcome')}: {body.get('failure')}"
    )
    assert body["request_id"] == request_id

    # The final chat message IS the analysis, unchanged (ADR-015) -- not a re-summarised
    # or re-generated paraphrase, and not raw tool JSON (that is also ET-5's concern).
    message = body["message"]
    assert message is not None and message["role"] == "assistant"
    assert message["content"] == analysis_text, (
        "the assistant message should be the agent's analysis verbatim (ADR-015), "
        f"got: {message['content']!r}"
    )
    assert not message["content"].strip().startswith("{"), (
        "final response looks like raw JSON, not prose"
    )

    # "Traceable to real data returned by the M1 tool, not fabricated": the analysis
    # call's own prompt must have actually contained the tool's projected data.
    analysis_calls = llm_calls_for_request(db_path, request_id, purpose="analysis")
    assert len(analysis_calls) >= 1, "expected at least one llm_calls row with purpose=analysis"
    combined_prompt = "\n".join(c.get("request_messages") or "" for c in analysis_calls)
    for expected_fragment in ("CSV export", "invoice rounding", "timezone"):
        assert expected_fragment in combined_prompt, (
            f"expected the GitHub fixture data ({expected_fragment!r}) to appear in the "
            f"analysis call's persisted prompt -- got: {combined_prompt[:800]!r}"
        )


@pytest.mark.live
def test_et1_live_end_to_end_real_data(
    db_path, database_url, qa_config_dir, monkeypatch, live_env, request_id
):
    from tests.conftest import require_live_credentials

    creds = require_live_credentials(live_env)
    run_migrations(database_url, monkeypatch=monkeypatch)
    seed_owner_directly(db_path)

    settings = build_live_settings(
        database_url=database_url,
        config_dir=qa_config_dir,
        anthropic_api_key=creds["ANTHROPIC_API_KEY"],
        github_token=creds["GITHUB_TOKEN"],
        openai_api_key=creds["OPENAI_API_KEY"],
    )
    with app_client(settings=settings) as client:
        login(client)
        started = time.monotonic()
        resp = post_chat(client, message="Check on EasyClean Workforce", request_id=request_id)
        elapsed_s = time.monotonic() - started

    assert resp.status_code == 200, f"unexpected status {resp.status_code}: {resp.text[:500]}"
    body = resp.json()
    assert body["outcome"] == "ok", (
        f"expected outcome=ok, got {body.get('outcome')}: {body.get('failure')}"
    )
    message = body["message"]
    assert message and message["content"].strip(), "expected a non-empty natural-language answer"
    assert not message["content"].strip().startswith("{"), (
        "final response looks like raw JSON, not prose"
    )

    # NFR-060 is a p95 target that a single run cannot prove or disprove (D-12); report
    # honestly (docs/ARCHITECTURE_V1.md §5.2) rather than assert a percentile from n=1.
    print(f"ET-1 live turn latency: {elapsed_s:.2f}s (NFR-060 target: <=30s p95, indicative only)")
    assert elapsed_s < 60, (
        f"turn took {elapsed_s:.1f}s -- more than 2x the target, "
        "investigate before trusting NFR-060"
    )
