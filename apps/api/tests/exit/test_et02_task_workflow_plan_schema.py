"""ET-2 — docs/REQUIREMENTS_V1.md §7:
"For that same request, a Task record and a Workflow record exist, linked by request
ID, with a plan JSON that validates against the defined schema."

Coverage map: made passable by T2 + T9 + T11a + T11b.

Structural schema conformance is checked directly here (required top-level keys,
`confidence` in [0,1], non-empty/uniquely-identified `steps`, per ADR-004 layer 3's own
Pydantic checks) as a DB-level corroboration. The *authoritative* proof that the plan
validated is behavioural: `outcome == "ok"` can only happen if the real
`validate_plan()` accepted it (FR-061/062) — a plan that failed validation never
reaches Task/Workflow creation at all, so this test also doubles as evidence that the
plan preceded the Task, not the reverse.
"""

from __future__ import annotations

import json

from tests.exit._db import plans_for_request, task_for_request, workflow_for_request
from tests.exit._scenarios import run_completed_turn


def test_et2_task_and_workflow_exist_with_schema_valid_plan(
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

    task = task_for_request(db_path, request_id)
    assert task is not None, "expected a `tasks` row linked to this request_id"
    assert task["objective"], "Task.objective must be populated from the validated plan"

    workflow = workflow_for_request(db_path, request_id)
    assert workflow is not None, "expected a `workflows` row linked to this request_id"
    assert workflow["status"] in ("completed", "in_progress"), (
        f"unexpected workflow status: {workflow['status']!r}"
    )

    plans = plans_for_request(db_path, request_id)
    assert len(plans) >= 1, "expected at least one `plans` row for this request"
    accepted = [p for p in plans if p["validated"] in (1, True)]
    assert accepted, (
        f"expected at least one plans row with validated=true, got: {plans}"
    )

    plan_json = json.loads(accepted[-1]["raw_json"])
    required_keys = {
        "intent",
        "confidence",
        "privacy_level",
        "objective",
        "project_key",
        "agents",
        "tools",
        "steps",
    }
    missing = required_keys - plan_json.keys()
    assert not missing, (
        f"plan JSON is missing required keys per ARCHITECTURE_V1.md §6.1: {missing}"
    )
    assert 0.0 <= plan_json["confidence"] <= 1.0, (
        f"confidence out of [0,1]: {plan_json['confidence']}"
    )
    assert isinstance(plan_json["steps"], list) and plan_json["steps"], (
        "steps must be a non-empty list"
    )
    step_ids = [s["id"] for s in plan_json["steps"]]
    assert len(step_ids) == len(set(step_ids)), f"step ids must be unique: {step_ids}"
    assert plan_json["project_key"] == "easy_clean_workforce"

    # Linkage: the same request_id ties task, workflow and plan together (not just
    # each existing independently) — the join key ET-6/NFR-020 also relies on.
    assert task["workflow_id"] == workflow["id"]
