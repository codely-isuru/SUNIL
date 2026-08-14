"""ET-5 — docs/REQUIREMENTS_V1.md §7:
"The tool's raw result was used as an input to the agent's analysis LLM call
(verifiable via the LLM input/output log), and the final chat response reflects that
analysis rather than raw JSON."

Coverage map: made passable by T6 + T10 (ADR-015 makes the answer *be* that analysis).

Distinct from ET-1 (which checks the response is coherent and traceable): this test's
job is specifically the *log* claim ("verifiable via the LLM input/output log") and the
"not raw JSON" claim, checked as its own, narrower assertion.
"""

from __future__ import annotations

import json

from tests.exit._db import llm_calls_for_request, tool_calls_for_request
from tests.exit._scenarios import DEFAULT_ANALYSIS_TEXT, run_completed_turn


def test_et5_analysis_call_is_fed_tool_result_and_response_is_prose(
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

    # 1. "Verifiable via the LLM input/output log": the persisted analysis-purpose
    # llm_calls row's own input must contain the tool's data.
    analysis_calls = llm_calls_for_request(db_path, request_id, purpose="analysis")
    assert len(analysis_calls) >= 1, (
        "expected at least one llm_calls row with purpose=analysis"
    )
    prompt_text = "\n".join(c.get("request_messages") or "" for c in analysis_calls)
    assert "CSV export" in prompt_text, (
        "the tool's projected data must appear in the analysis call's input"
    )

    # And the log's own OUTPUT is what the user received (ADR-015: no third call).
    output_text = "\n".join((c.get("response_text") or "") for c in analysis_calls)
    assert (
        DEFAULT_ANALYSIS_TEXT in output_text
        or output_text.strip() == DEFAULT_ANALYSIS_TEXT.strip()
    )

    # 2. "Reflects that analysis rather than raw JSON": the assistant message is prose,
    # not the tool's raw result serialised.
    message_content = body["message"]["content"]
    assert message_content == DEFAULT_ANALYSIS_TEXT

    tool_calls = tool_calls_for_request(db_path, request_id)
    assert len(tool_calls) == 1
    raw_result_json = tool_calls[0]["result"]
    assert message_content != raw_result_json, (
        "final message must not literally be the tool's raw result"
    )
    try:
        json.loads(message_content)
        raise AssertionError(
            "final assistant message parses as JSON -- it should be prose, not a data dump"
        )
    except (json.JSONDecodeError, TypeError):
        pass  # expected: prose is not valid JSON
