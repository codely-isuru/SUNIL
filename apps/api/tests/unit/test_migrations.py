"""Unit tests for the `0001_initial` Alembic migration (T2).

Per the L-002 lesson (backend_engineer memory): a persistence/durability
test that passes on the first try is suspect until it has been shown it
can fail, and every assertion must be scoped to the run's own window, never
to state that might pre-exist. Both are applied here: each test points
`DATABASE_URL` at a brand-new file under `tmp_path` (pytest's own per-test
temp directory — nothing is shared across tests or previous runs), and the
round-trip test asserts the *negative* (tables gone) after downgrade, not
just the positive (tables present) after upgrade — so it could actually
fail if `downgrade()` were broken.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config

_API_DIR = Path(__file__).resolve().parents[2]  # apps/api
_ALEMBIC_INI = _API_DIR / "alembic.ini"

_EXPECTED_TABLES = {
    "users",
    "conversations",
    "messages",
    "workflows",
    "tasks",
    "task_status_events",
    "plans",
    "tool_calls",
    "approvals",
    "memories",
    "llm_calls",
    "audit_events",
}

_REQUIRED_ENV = {
    "ANTHROPIC_API_KEY": "sk-ant-fake-test-value",
    "GITHUB_TOKEN": "github_pat_fake-test-value",
    "SESSION_SECRET": "fake-test-session-secret",
    "OWNER_USERNAME": "test-owner",
    "OWNER_PASSWORD": "fake-test-owner-password",
}


def _tables_in(db_path: Path) -> set[str]:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
    finally:
        conn.close()
    return {row[0] for row in rows}


def _alembic_config_for(db_path: Path, monkeypatch: pytest.MonkeyPatch) -> Config:
    for key, value in _REQUIRED_ENV.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{db_path.as_posix()}")

    # `sunil.settings.get_settings()` is process-cached (`lru_cache`); each
    # test must clear it or it would silently reuse a previous test's
    # DATABASE_URL — exactly the cross-test leakage L-002 warns about.
    from sunil.settings import get_settings

    get_settings.cache_clear()

    return Config(str(_ALEMBIC_INI))


def test_upgrade_head_creates_exactly_the_twelve_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "upgrade_only.db"
    assert not db_path.exists()  # nothing pre-existing in this run's window

    config = _alembic_config_for(db_path, monkeypatch)
    command.upgrade(config, "head")

    tables = _tables_in(db_path)
    assert _EXPECTED_TABLES <= tables
    assert tables - _EXPECTED_TABLES == {"alembic_version"}


def test_upgrade_head_sets_alembic_version_to_0001(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path = tmp_path / "version_check.db"
    config = _alembic_config_for(db_path, monkeypatch)
    command.upgrade(config, "head")

    conn = sqlite3.connect(str(db_path))
    try:
        (version,) = conn.execute("SELECT version_num FROM alembic_version").fetchone()
    finally:
        conn.close()
    assert version == "0001"


def test_downgrade_to_base_actually_removes_every_domain_table(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The round-trip test. Asserts the negative after downgrade, not just
    the positive after upgrade — a `downgrade()` that silently did nothing
    would still leave this test able to fail here."""
    db_path = tmp_path / "round_trip.db"
    config = _alembic_config_for(db_path, monkeypatch)

    command.upgrade(config, "head")
    assert _EXPECTED_TABLES <= _tables_in(db_path)  # sanity check before the real assertion

    command.downgrade(config, "base")

    tables_after_downgrade = _tables_in(db_path)
    assert tables_after_downgrade.isdisjoint(_EXPECTED_TABLES), (
        f"downgrade('base') left domain tables behind: {tables_after_downgrade & _EXPECTED_TABLES}"
    )
