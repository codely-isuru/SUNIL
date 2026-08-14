"""ET-11 — docs/REQUIREMENTS_V1.md §7:
"Given a project name with no entry in the FR-107 config mapping, When the owner asks
'Check project <unknown>', Then SUNIL responds that it does not recognise that project
rather than crashing, hallucinating data, or calling the tool with a garbage
identifier."

Coverage map: made passable by T3 + T9 + T11b + T16.

The schema's own `project_key: "__unknown__"` sentinel (ARCHITECTURE_V1.md §6.1) makes
this structural rather than best-effort: an unrecognised project name has a legal,
non-executing representation, so the model is never forced to invent an identifier.
The fixture test scripts that sentinel directly; the live test asks about a genuinely
unconfigured project name against the real, schema-constrained model and expects the
same structural outcome with zero fault injection needed at all.
"""

from __future__ import annotations

import pytest

from tests.exit._client import app_client, login, post_chat, run_migrations, seed_owner
from tests.exit._contract import FAILURE_KINDS
from tests.exit._db import count_for_request
from tests.exit._mock_upstreams import anthropic_success
from tests.exit._plans import unknown_project_plan_json


def test_et11_unknown_project_plan_sentinel_yields_graceful_failure(
    db_path, database_url, qa_config_dir, monkeypatch, mock_server, request_id
):
    run_migrations(database_url, monkeypatch=monkeypatch)
    seed_owner(db_path)
    mock_server.script(
        "POST", "/v1/messages", anthropic_success(text=unknown_project_plan_json())
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
            client,
            message="Check project some-totally-unconfigured-project-xyz",
            request_id=request_id,
        )

    assert resp.status_code == 200, (
        f"unexpected status {resp.status_code}: {resp.text[:500]}"
    )
    body = resp.json()
    assert body["outcome"] == "failed", (
        f"expected outcome=failed, got {body.get('outcome')}"
    )
    assert body["failure"]["kind"] == "unknown_project", (
        f"expected failure.kind=unknown_project, got {body['failure']}"
    )
    assert body["failure"]["kind"] in FAILURE_KINDS

    known = body["failure"].get("known_projects")
    assert known, (
        "expected a non-empty known_projects list so the UI can offer real choices"
    )
    keys = {p["key"] for p in known}
    assert "easy_clean_workforce" in keys, (
        f"expected the configured project in known_projects, got keys: {keys}"
    )
    for p in known:
        assert "display_name" in p, (
            f"each known_projects entry needs a display_name: {p}"
        )

    assert count_for_request(db_path, "tool_calls", request_id) == 0, (
        "an unknown project must never reach the tool -- no garbage-identifier call (FR-107)"
    )


@pytest.mark.live
def test_et11_live_unconfigured_project_is_graceful_no_fault_injection_needed(
    db_path, database_url, qa_config_dir, monkeypatch, live_env, request_id
):
    from tests.conftest import require_live_credentials

    creds = require_live_credentials(live_env)
    run_migrations(database_url, monkeypatch=monkeypatch)
    seed_owner(db_path)

    with app_client(
        database_url=database_url,
        config_dir=qa_config_dir,
        monkeypatch=monkeypatch,
        extra_env=creds,
    ) as client:
        login(client)
        resp = post_chat(
            client,
            message="Check project totally-made-up-project-that-does-not-exist",
            request_id=request_id,
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["outcome"] == "failed"
    assert body["failure"]["kind"] == "unknown_project", (
        f"the real, schema-constrained model should be structurally unable to emit anything "
        f"but the __unknown__ sentinel for an unconfigured project: got {body['failure']}"
    )
    assert count_for_request(db_path, "tool_calls", request_id) == 0
