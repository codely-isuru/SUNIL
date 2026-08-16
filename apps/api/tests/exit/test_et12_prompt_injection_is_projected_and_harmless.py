"""ET-12 (new — Architect-recommended, owner-accepted; from the owner's review §16 step
13, docs/M1_BUILD_PLAN.md §7/§10 step 13):
"Given a repository whose recent activity contains an embedded instruction, When the
owner requests a status check, Then no unprojected external payload appears in any
`llm_calls.request_messages` row, issue and PR bodies are absent, and the agent's
behaviour is unchanged."

Coverage map: made passable by T8 + T19 (docs/M1_BUILD_PLAN.md §7's own note: "No
current exit test covers it" before this one was added). This is a mandatory M1
control, not a deferred one (THREAT_MODEL.md §5.1, NFR-011/012).

QA's version of this check runs at the "for a completed M1 request" altitude, end to
end through a real chat turn against injected fixture content QA controls directly
(never against the real `easy_clean_workforce` repo -- pushing an adversarial commit to
a real, owned repository to test this would be a terrible way to test it). Security's
narrower, unit-level tests (`test_tool_result_projection_excludes_issue_bodies`,
`test_projection_escapes_the_untrusted_delimiter`,
`test_no_unprojected_github_payload_reaches_a_prompt`,
`test_injected_instruction_in_commit_message_causes_no_action`) are T19's, in
`apps/api/tests/security/` -- this file does not duplicate those, it proves the same
property end-to-end through the real API contract.
"""

from __future__ import annotations

from tests.exit._client import app_client, login, post_chat, run_migrations, seed_owner
from tests.exit._db import all_text_blob, fetch_all, tool_calls_for_request
from tests.exit._mock_upstreams import anthropic_success
from tests.exit._plans import valid_plan_json
from tests.exit.conftest import (
    INJECTED_ISSUE_BODY_MARKER,
    script_injected_github_activity,
)


def test_et12_injected_activity_never_reaches_a_prompt_and_behaviour_is_unchanged(
    db_path, database_url, qa_config_dir, monkeypatch, mock_server, request_id
):
    run_migrations(database_url, monkeypatch=monkeypatch)
    seed_owner(db_path)
    script_injected_github_activity(mock_server)

    analysis_text = "EasyClean Workforce activity looks normal: a few commits and one open issue about invoice rounding."
    mock_server.script(
        "POST", "/v1/messages", anthropic_success(text=valid_plan_json())
    )
    mock_server.script("POST", "/v1/messages", anthropic_success(text=analysis_text))

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

    # "The agent's behaviour is unchanged": normal completion, the one expected tool
    # call and nothing else, the same agent, the scripted (not attacker-dictated) reply.
    assert body["outcome"] == "ok", (
        f"expected outcome=ok despite the injected content, got {body.get('outcome')}: {body.get('failure')}"
    )
    assert body["task"]["assigned_agent"] == "project_manager"
    tool_calls = tool_calls_for_request(db_path, request_id)
    assert len(tool_calls) == 1, (
        f"the injected instruction must not cause any extra/different tool call: {tool_calls}"
    )
    assert (
        tool_calls[0]["tool"] == "github"
        and tool_calls[0]["operation"] == "list_recent_activity"
    )
    assert body["message"]["content"] == analysis_text, (
        "the final message must be exactly the scripted analysis -- if it were anything "
        "else (e.g. literally 'done', or a claim of having deleted something), the "
        "injected instruction would have been followed"
    )
    assert body["message"]["content"].strip().lower() != "done"

    # "No unprojected external payload appears in any llm_calls.request_messages row...
    # issue bodies are absent": the strong, "Mitigated" claim (THREAT_MODEL.md §5.1
    # control 3) -- the issue-body marker must never surface anywhere downstream.
    llm_rows = fetch_all(
        db_path, "SELECT * FROM llm_calls WHERE request_id = ?", (request_id,)
    )
    assert llm_rows, "expected at least one llm_calls row to inspect"
    for row in llm_rows:
        blob = all_text_blob(
            row, "request_system", "request_messages", "response_text", "response_json"
        )
        assert INJECTED_ISSUE_BODY_MARKER not in blob, (
            f"an issue BODY reached an LLM call (row {row['id']}) -- the projection must "
            f"exclude issue/PR bodies entirely (ARCHITECTURE_V1.md §9.4 control 3)"
        )

    # Same guarantee holds for the persisted tool_calls.result (the projected output),
    # which must also never carry the excluded body content.
    for tc in tool_calls:
        assert INJECTED_ISSUE_BODY_MARKER not in (tc["result"] or ""), (
            f"the tool_calls.result projection must not contain the excluded issue body: {tc['result']!r}"
        )

    # The analysis call's prompt must still show evidence of the *projection* having
    # run (title text survives, capped), just never the excluded body content --
    # otherwise this test could pass vacuously because nothing at all was sent.
    analysis_calls = [r for r in llm_rows if r["purpose"] == "analysis"]
    combined_prompt = "\n".join(c.get("request_messages") or "" for c in analysis_calls)
    assert "Invoice totals off by a cent" in combined_prompt, (
        "expected the issue TITLE (not its body) to still reach the analysis prompt -- "
        "if it's absent, this test may be passing vacuously rather than proving exclusion"
    )
