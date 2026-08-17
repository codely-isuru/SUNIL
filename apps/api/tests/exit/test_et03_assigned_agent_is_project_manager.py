"""ET-3 — docs/REQUIREMENTS_V1.md §7:
"The Task's `assigned_agent` is the Project Manager Agent."

Coverage map: made passable by T10 + T11b. Checked twice on purpose: once from the
frozen §6 HTTP contract's `task.assigned_agent` field (what the frontend actually
sees), and once from the `tasks` table directly (what an auditor reconstructing the
trace from the DB alone would see) — they must agree.
"""

from __future__ import annotations

from tests.exit._db import task_for_request
from tests.exit._scenarios import run_completed_turn


def test_et3_assigned_agent_is_project_manager(
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

    assert body["task"] is not None, "expected a `task` object in the chat response"
    assert body["task"]["assigned_agent"] == "project_manager", (
        f"response task.assigned_agent should be project_manager, got {body['task']['assigned_agent']!r}"
    )

    task_row = task_for_request(db_path, request_id)
    assert task_row is not None
    assert task_row["assigned_agent"] == "project_manager", (
        f"tasks.assigned_agent should be project_manager, got {task_row['assigned_agent']!r}"
    )
    assert task_row["id"] == body["task"]["id"], (
        "the response's task.id must match the persisted tasks row"
    )
