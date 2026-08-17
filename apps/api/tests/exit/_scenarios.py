"""Shared scenario builders for exit tests that need a completed (or deliberately
failed) turn as their starting point, so each ET file states only what is distinctive
about it. Plain functions, called from inside test bodies — see tests/_helpers.py.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from tests.exit._client import (
    app_client,
    build_settings,
    login,
    post_chat,
    run_migrations,
    seed_owner_directly,
)
from tests.exit._mock_upstreams import ScriptedHTTPServer, openai_success
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
    turn_deadline_s: int | None = None,
) -> Any:
    """Runs T2 migrations + seeds the owner + scripts a clean GitHub activity set + a
    valid plan + a scripted analysis response, then performs one real chat turn through
    the local mock upstream (ADR-017's transport seam, wired via a fresh `Settings`
    instance per ADR-018 — see `build_settings()`/`app_client()`). Returns the raw HTTP
    response; callers query `db_path` afterwards for DB-level assertions (the SQLite
    file is real and closed by the time the `with app_client(...)` block exits).

    T24: `general_reasoning` (`config/models.yaml`) now resolves to `openai` — both the
    plan call and the analysis call go through `POST /v1/chat/completions`, not
    Anthropic's `/v1/messages`, so this scripts the OpenAI response shape.
    """
    run_migrations(database_url, monkeypatch=monkeypatch)
    seed_owner_directly(db_path)
    script_clean_github_activity(mock_server)
    mock_server.script(
        "POST",
        "/v1/chat/completions",
        openai_success(text=valid_plan_json(project_key=project_key)),
    )
    mock_server.script("POST", "/v1/chat/completions", openai_success(text=analysis_text))

    settings = build_settings(
        database_url=database_url,
        config_dir=config_dir,
        anthropic_base_url=mock_server.base_url,
        github_api_base_url=mock_server.base_url,
        # `/v1` is NOT optional here (found empirically, T24): unlike
        # Anthropic's client, which appends the full `/v1/messages` path
        # itself onto a bare host, `openai`'s client joins its relative
        # `/chat/completions` path onto `base_url` verbatim -- the `/v1`
        # segment is expected to already be part of `base_url` (exactly
        # matching the real default `https://api.openai.com/v1`,
        # `sunil/settings.py`'s `_CANONICAL_BASE_URLS`).
        openai_base_url=f"{mock_server.base_url}/v1",
        turn_deadline_s=turn_deadline_s,
    )
    with app_client(settings=settings) as client:
        login(client)
        return post_chat(
            client,
            message=message,
            request_id=request_id,
            conversation_id=conversation_id,
        )
