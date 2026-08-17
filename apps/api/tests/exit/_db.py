"""Raw, synchronous SQLite readers used to assert against the tables in
ARCHITECTURE_V1.md §7.3, by table/column name only.

Deliberately does NOT import `sunil.db.models` — the app writes with an async driver
(`aiosqlite`), but the result is still an ordinary SQLite file on disk once a write has
committed, and the stdlib `sqlite3` module can read it synchronously with zero
dependency on sunil's ORM layer existing. That keeps this module importable at hour 0,
and keeps every exit test's assertions scoped to table/column names that are frozen in
the architecture doc, not to sunil-internal object shapes.

Every query below takes `request_id` and filters on it explicitly (never a bare
`SELECT * FROM table`) — see .minions/memory/backend_engineer.md L-002: a prior exit
test passed for the wrong reason by counting rows left over from an earlier run. Every
helper here forces the caller to scope to one run's `request_id`.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _connect(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    return conn


def _rows_as_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def fetch_all(
    db_path: str | Path, sql: str, params: tuple = ()
) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        return _rows_as_dicts(conn.execute(sql, params).fetchall())
    finally:
        conn.close()


def fetch_one(
    db_path: str | Path, sql: str, params: tuple = ()
) -> dict[str, Any] | None:
    rows = fetch_all(db_path, sql, params)
    return rows[0] if rows else None


def count_for_request(db_path: str | Path, table: str, request_id: str) -> int:
    row = fetch_one(
        db_path,
        f"SELECT COUNT(*) AS n FROM {table} WHERE request_id = ?",
        (request_id,),
    )
    return int(row["n"]) if row else 0


def audit_stages_for_request(
    db_path: str | Path, request_id: str
) -> list[dict[str, Any]]:
    """Ordered by `seq` — the column ET-6 is graded on (ARCHITECTURE_V1.md §8.1's own
    canonical query, reproduced here so ET-6 tests the documented invariant directly)."""
    return fetch_all(
        db_path,
        "SELECT stage, seq, at FROM audit_events WHERE request_id = ? ORDER BY seq",
        (request_id,),
    )


def llm_calls_for_request(
    db_path: str | Path, request_id: str, *, purpose: str | None = None
) -> list[dict[str, Any]]:
    if purpose is None:
        return fetch_all(
            db_path,
            "SELECT * FROM llm_calls WHERE request_id = ? ORDER BY id",
            (request_id,),
        )
    return fetch_all(
        db_path,
        "SELECT * FROM llm_calls WHERE request_id = ? AND purpose = ? ORDER BY id",
        (request_id, purpose),
    )


def tool_calls_for_request(
    db_path: str | Path, request_id: str
) -> list[dict[str, Any]]:
    return fetch_all(
        db_path,
        "SELECT * FROM tool_calls WHERE request_id = ? ORDER BY id",
        (request_id,),
    )


def plans_for_request(db_path: str | Path, request_id: str) -> list[dict[str, Any]]:
    return fetch_all(
        db_path,
        "SELECT * FROM plans WHERE request_id = ? ORDER BY attempt",
        (request_id,),
    )


def task_for_request(db_path: str | Path, request_id: str) -> dict[str, Any] | None:
    return fetch_one(db_path, "SELECT * FROM tasks WHERE request_id = ?", (request_id,))


def workflow_for_request(db_path: str | Path, request_id: str) -> dict[str, Any] | None:
    return fetch_one(
        db_path, "SELECT * FROM workflows WHERE request_id = ?", (request_id,)
    )


def task_status_events_for_task(
    db_path: str | Path, task_id: str
) -> list[dict[str, Any]]:
    return fetch_all(
        db_path,
        "SELECT * FROM task_status_events WHERE task_id = ? ORDER BY at",
        (task_id,),
    )


def all_text_blob(row: dict[str, Any], *keys: str) -> str:
    """Concatenate the given columns of one row into one search string, JSON-encoding
    non-string values first — used by ET-10/ET-12's "this value must never appear
    anywhere in this row" checks so a dict/list column is actually searched, not just
    `str()`-ed in a way that could hide a match."""
    parts = []
    for k in keys:
        v = row.get(k)
        if v is None:
            continue
        parts.append(v if isinstance(v, str) else json.dumps(v, default=str))
    return "\n".join(parts)
