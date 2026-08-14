"""ET-4 — docs/REQUIREMENTS_V1.md §7:
"Exactly one ToolCall record exists for the request, `tool` = the configured M1 tool,
`permission_decision` = `ALLOW`."

Coverage map: made passable by T7 + T8.
"""

from __future__ import annotations

from tests.exit._db import tool_calls_for_request
from tests.exit._scenarios import run_completed_turn


def test_et4_exactly_one_allowed_github_tool_call(
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

    calls = tool_calls_for_request(db_path, request_id)
    assert len(calls) == 1, (
        f"expected exactly one tool_calls row for this request, got {len(calls)}: {calls}"
    )
    (call,) = calls
    assert call["tool"] == "github", f"expected tool=github, got {call['tool']!r}"
    assert call["operation"] == "list_recent_activity", (
        f"expected operation=list_recent_activity, got {call['operation']!r}"
    )
    assert call["permission_decision"] == "allow", (
        f"expected permission_decision=allow, got {call['permission_decision']!r}"
    )
    assert call["status"] == "ok", (
        f"expected a successful tool call, got status={call['status']!r}"
    )
    assert call["agent_id"] == "project_manager"
    assert call["task_id"], (
        "tool_calls row must be linked to the Task (task_id non-null)"
    )
