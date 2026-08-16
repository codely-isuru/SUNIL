"""Shared scenario builders for exit tests that need a completed (or deliberately
failed) turn as their starting point, so each ET file states only what is distinctive
about it. Plain functions, called from inside test bodies — see tests/_helpers.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.exit._client import app_client, login, post_chat, run_migrations, seed_owner
from tests.exit._mock_upstreams import ScriptedHTTPServer, anthropic_success
from tests.exit._plans import valid_plan_json
from tests.exit.conftest import script_clean_github_activity

DEFAULT_MESSAGE = "Check on EasyClean Workforce"
DEFAULT_ANALYSIS_TEXT = (
    "EasyClean Workforce has had steady activity: recent commits include a CSV export "
    "feature, two open pull requests, and one open issue about invoice rounding that is "
    "worth a look."
)


def run_completed_turn(
    *,
    db_path: Path,
    database_url: str,
    config_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
    mock_server: ScriptedHTTPServer,
    request_id: str,
    message: str = DEFAULT_MESSAGE,
    analysis_text: str = DEFAULT_ANALYSIS_TEXT,
    project_key: str = "easy_clean_workforce",
    conversation_id: str | None = None,
) -> Any:
    """Runs T2 migrations + seeds the owner + scripts a clean GitHub activity set + a
    valid plan + a scripted analysis response, then performs one real chat turn through
    the local mock upstream. Returns the raw HTTP response; callers query `db_path`
    afterwards for DB-level assertions (the SQLite file is real and closed by the time
    the `with app_client(...)` block exits).
    """
    run_migrations(database_url, monkeypatch=monkeypatch)
    seed_owner(db_path)
    script_clean_github_activity(mock_server)
    mock_server.script(
        "POST",
        "/v1/messages",
        anthropic_success(text=valid_plan_json(project_key=project_key)),
    )
    mock_server.script("POST", "/v1/messages", anthropic_success(text=analysis_text))

    with app_client(
        database_url=database_url,
        config_dir=config_dir,
        monkeypatch=monkeypatch,
        anthropic_base_url=mock_server.base_url,
        github_api_base_url=mock_server.base_url,
    ) as client:
        login(client)
        return post_chat(
            client,
            message=message,
            request_id=request_id,
            conversation_id=conversation_id,
        )
