"""ET-6 — docs/REQUIREMENTS_V1.md §7:
"For the request's ID, all twelve observability stages in NFR-020 are present and in
order — the full trace is reconstructable from logs alone."

Coverage map: made passable by T4 + T11a + T11b.

Checked against the `audit_events` table using ARCHITECTURE_V1.md §8.1's own canonical
query ("the full trace is reconstructable from logs alone" — audit_events IS that log),
and cross-checked against the frozen §6 HTTP response's inline `trace[]` array, which
must describe the same twelve stages in the same order. Presence AND uniqueness are
both asserted, per ARCHITECTURE_V1.md §3.4: "each of the twelve stages is emitted at
most once per turn... retries do not emit extra stage events."
"""

from __future__ import annotations

from tests.exit._contract import TRACE_STAGES
from tests.exit._db import audit_stages_for_request
from tests.exit._scenarios import run_completed_turn


def test_et6_all_twelve_stages_present_in_order_and_unique(
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
    assert resp.status_code == 200, f"unexpected status {resp.status_code}: {resp.text[:500]}"
    body = resp.json()
    assert body["outcome"] == "ok", (
        f"expected outcome=ok, got {body.get('outcome')}: {body.get('failure')}"
    )

    # -- From the database (ARCHITECTURE_V1.md §8.1's own query) --
    rows = audit_stages_for_request(db_path, request_id)
    stages_in_order = [r["stage"] for r in rows]

    assert len(rows) == 12, (
        f"expected exactly 12 audit_events rows for this request, got {len(rows)}: "
        f"{stages_in_order}"
    )
    assert set(stages_in_order) == set(TRACE_STAGES), (
        f"stage set mismatch.\n  expected: {sorted(TRACE_STAGES)}\n"
        f"  got:      {sorted(set(stages_in_order))}"
    )
    assert stages_in_order == list(TRACE_STAGES), (
        f"stages are not in the documented order.\n  expected: {list(TRACE_STAGES)}\n"
        f"  got:      {stages_in_order}"
    )
    seqs = [r["seq"] for r in rows]
    assert seqs == sorted(seqs) and len(set(seqs)) == len(seqs), (
        f"seq must be strictly increasing and unique: {seqs}"
    )
    assert len(set(stages_in_order)) == len(stages_in_order), (
        "a stage was emitted more than once -- retries must land in `detail`, "
        f"never as extra rows: {stages_in_order}"
    )

    # -- Cross-checked against the frozen §6 HTTP response's inline trace --
    response_trace = body["trace"]
    response_stages = [t["stage"] for t in response_trace]
    assert response_stages == list(TRACE_STAGES), (
        f"response `trace[]` should list the same twelve stages in the same order as "
        f"the audit log.\n  expected: {list(TRACE_STAGES)}\n  got:      {response_stages}"
    )
