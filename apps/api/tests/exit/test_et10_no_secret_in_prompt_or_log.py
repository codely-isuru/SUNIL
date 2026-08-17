"""ET-10 — docs/REQUIREMENTS_V1.md §7:
"No secret/credential value appears in any prompt sent to the LLM or in any persisted
log for the request (spot-check against NFR-001/005)."

Coverage map: made passable by T4 + T19. QA's own exit-level version of this claim --
narrower, named mechanism tests (`test_registered_secret_never_appears_in_log_output`,
`test_registered_secret_never_appears_in_persisted_llm_call`) are Security's (T19,
docs/THREAT_MODEL.md §11), living in `apps/api/tests/security/`. This test asks the
same question at the "for a completed M1 request" altitude ET-10 is written at, which
is a legitimate, different-lane check even though the underlying mechanism overlaps.

Uses distinctive CANARY secret values (never a real key) as `ANTHROPIC_API_KEY` /
`GITHUB_TOKEN` -- ARCHITECTURE_V1.md §9.1 states secrets are registered for redaction
at Settings load time regardless of their value, so a fake canary is exactly as
effective a probe as a real key, without this suite ever handling a real one.
"""

from __future__ import annotations

from tests.exit._db import all_text_blob, fetch_all
from tests.exit._scenarios import run_completed_turn

CANARY_API_KEY = "sk-ant-test-canary-do-not-use-for-real-calls"
CANARY_GITHUB_TOKEN = "github_pat_test-canary-do-not-use-for-real-calls"


def test_et10_no_secret_in_any_persisted_row_or_log_output(
    db_path, database_url, qa_config_dir, monkeypatch, mock_server, request_id, capsys
):
    resp = run_completed_turn(
        db_path=db_path,
        database_url=database_url,
        config_dir=qa_config_dir,
        monkeypatch=monkeypatch,
        mock_server=mock_server,
        request_id=request_id,
    )
    assert resp.status_code == 200, f"unexpected status {resp.status_code}: {resp.text[:500]}"
    body = resp.json()
    assert body["outcome"] == "ok", (
        f"expected outcome=ok, got {body.get('outcome')}: {body.get('failure')}"
    )

    canaries = (CANARY_API_KEY, CANARY_GITHUB_TOKEN)

    llm_rows = fetch_all(db_path, "SELECT * FROM llm_calls WHERE request_id = ?", (request_id,))
    assert llm_rows, "expected at least one llm_calls row to inspect"
    for row in llm_rows:
        blob = all_text_blob(
            row,
            "request_system",
            "request_messages",
            "request_schema",
            "response_text",
            "response_json",
        )
        for canary in canaries:
            assert canary not in blob, (
                f"secret value leaked into llm_calls row {row['id']}: found {canary!r}"
            )

    tool_rows = fetch_all(db_path, "SELECT * FROM tool_calls WHERE request_id = ?", (request_id,))
    for row in tool_rows:
        blob = all_text_blob(row, "parameters", "result")
        for canary in canaries:
            assert canary not in blob, (
                f"secret value leaked into tool_calls row {row['id']}: found {canary!r}"
            )

    audit_rows = fetch_all(
        db_path, "SELECT * FROM audit_events WHERE request_id = ?", (request_id,)
    )
    assert audit_rows, "expected at least some audit_events rows to inspect"
    for row in audit_rows:
        blob = all_text_blob(row, "summary", "detail")
        for canary in canaries:
            assert canary not in blob, (
                f"secret value leaked into audit_events row {row['id']}: found {canary!r}"
            )

    # Captured stdout/stderr -- structured JSON log lines land here (ARCHITECTURE_V1.md §8.2).
    captured = capsys.readouterr()
    for canary in canaries:
        assert canary not in captured.out, (
            f"secret value leaked into stdout log output: found {canary!r}"
        )
        assert canary not in captured.err, (
            f"secret value leaked into stderr log output: found {canary!r}"
        )
