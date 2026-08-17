"""Coverage for `scripts/seed-owner.py` itself — approved by the Architect ruling batch
(docs/M1_BUILD_PLAN.md: "Seeding the owner row in fixtures by raw SQL is approved... It
does leave scripts/seed-owner.py itself untested: T18 owns one test that calls the
script's hash_password()/seeding function and then logs in through the API, which also
closes §10's coverage gap on walkthrough steps 1 and 3.").

This is deliberately a DIFFERENT code path from `_client.seed_owner_directly()` (which
every other exit test uses, and which never touches this script at all): that helper
exists so the other eleven exit tests do not depend on this script's own interface;
this file is the one place that actually exercises the script, so its logic is not
otherwise coverage-free.

Named distinctly from T2's own `tests/unit/test_seed_owner.py` — two test files sharing
one basename previously aborted the whole pytest collection (docs/STATUS.md, the
`test_capture.py` collision, fixed by T22) — never repeat that class of bug from this
side.

Loaded via `importlib.util.spec_from_file_location`, which resolves by file path and so
works regardless of the script's hyphenated filename (`seed-owner.py` is not a valid
`import` target as a dotted name).

Script-context settings (ADR-018 §3): `scripts/seed-owner.py` uses `get_settings()`
internally, which stays `@lru_cache`d outside an `app` — so, unlike every app-building
test in this suite, `get_settings.cache_clear()` + env vars *is* the sanctioned seam
here, not a rejected shortcut.

This second test is deliberately a plain *sync* function, not `@pytest.mark.asyncio` --
VERIFIED against the real T2 code that `run_migrations()` (Alembic) runs its own async
migration via an internal `asyncio.run()`, which raises `RuntimeError: asyncio.run()
cannot be called from a running event loop` if the surrounding test is itself already
inside pytest-asyncio's loop. `asyncio.run(module.seed_owner())` is called directly,
exactly the way the script's own `if __name__ == "__main__":` block invokes it.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import importlib.util
import sqlite3
from pathlib import Path
from types import ModuleType

import pytest

from tests._helpers import import_or_fail
from tests.exit._client import app_client, build_settings, login, run_migrations

_REPO_ROOT = Path(__file__).resolve().parents[4]  # exit -> tests -> api -> apps -> repo root
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "seed-owner.py"


def _load_seed_owner_script() -> ModuleType:
    if not _SCRIPT_PATH.exists():
        pytest.fail(
            f"NOT YET BUILT: {_SCRIPT_PATH} does not exist yet. Blocked on T2.",
            pytrace=False,
        )
    spec = importlib.util.spec_from_file_location("qa_seed_owner_script_under_test", _SCRIPT_PATH)
    if spec is None or spec.loader is None:
        pytest.fail(
            f"NOT YET BUILT: could not load a module spec for {_SCRIPT_PATH}.",
            pytrace=False,
        )
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - a clean red failure, not a broken collection
        pytest.fail(
            f"NOT YET BUILT or a real defect: importing {_SCRIPT_PATH} raised "
            f"{exc.__class__.__name__}: {exc}. Blocked on T2.",
            pytrace=False,
        )
    for attr in ("hash_password", "seed_owner"):
        if not hasattr(module, attr):
            pytest.fail(
                f"NOT YET BUILT: {_SCRIPT_PATH} has no `{attr}` -- T18's brief requires "
                f"the script's logic to be importable, not only under "
                f"`if __name__ == '__main__':`. Blocked on T2.",
                pytrace=False,
            )
    return module


def _verify_scrypt_hash(encoded: str, *, candidate_password: str) -> bool:
    """Independent re-implementation of the §9.6 verification side, since T5's real
    login route does not exist yet. Parses `scrypt$n$r$p$salt_b64$hash_b64` and
    recomputes -- this is what proves `hash_password()` produced something a correct
    verifier would actually accept, not just something shaped like the right format.
    """
    scheme, n, r, p, salt_b64, hash_b64 = encoded.split("$")
    assert scheme == "scrypt", f"unexpected scheme in encoded hash: {encoded!r}"
    salt = base64.b64decode(salt_b64)
    expected = base64.b64decode(hash_b64)
    candidate = hashlib.scrypt(
        candidate_password.encode("utf-8"),
        salt=salt,
        n=int(n),
        r=int(r),
        p=int(p),
        dklen=len(expected),
    )
    return candidate == expected


def test_hash_password_produces_a_verifiable_scrypt_9_6_encoding():
    module = _load_seed_owner_script()
    encoded = module.hash_password("correct horse battery staple")

    parts = encoded.split("$")
    assert len(parts) == 6, f"expected scrypt$n$r$p$salt_b64$hash_b64, got: {encoded!r}"
    assert parts[0] == "scrypt"
    assert parts[1:4] == ["16384", "8", "1"], (
        f"expected n=16384 r=8 p=1 per §9.6, got: {parts[1:4]}"
    )

    assert _verify_scrypt_hash(encoded, candidate_password="correct horse battery staple")
    assert not _verify_scrypt_hash(encoded, candidate_password="wrong password")

    # A fresh random salt every call -- hashing the same password twice must never
    # produce the same encoded string (ARCHITECTURE_V1.md §9.6 / the script's own docstring).
    encoded_again = module.hash_password("correct horse battery staple")
    assert encoded != encoded_again, "hash_password() must salt freshly on every call"


def test_seed_owner_script_creates_then_updates_and_the_owner_can_log_in(
    db_path, database_url, qa_config_dir, monkeypatch
):
    run_migrations(database_url, monkeypatch=monkeypatch)
    module = _load_seed_owner_script()

    get_settings = import_or_fail("sunil.settings.get_settings", blocked_on="T1 (Settings)")

    def _run_script_as_owner(username: str, password: str) -> None:
        monkeypatch.setenv("OWNER_USERNAME", username)
        monkeypatch.setenv("OWNER_PASSWORD", password)
        monkeypatch.setenv("DATABASE_URL", database_url)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-canary-do-not-use-for-real-calls")
        monkeypatch.setenv("GITHUB_TOKEN", "github_pat_test-canary-do-not-use-for-real-calls")
        monkeypatch.setenv("SESSION_SECRET", "qa-test-session-secret-32-bytes-minimum-000000")
        # Script context (ADR-018 §3): get_settings() is legitimately cached here, so a
        # fresh read for THIS call requires clearing it first -- the one place in this
        # whole harness where cache_clear() is the sanctioned pattern, not a rejected one.
        get_settings.cache_clear()

    username = "qa-seeded-owner"

    # -- create path --
    _run_script_as_owner(username, "first-password-Xk9!")
    asyncio.run(module.seed_owner())

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1, f"expected exactly one users row after the first seed, got {len(rows)}"
    first_hash = rows[0][0]
    assert _verify_scrypt_hash(first_hash, candidate_password="first-password-Xk9!")

    # -- update path: re-running with a different password must update, not duplicate --
    _run_script_as_owner(username, "second-password-Zq3!")
    asyncio.run(module.seed_owner())

    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT password_hash FROM users WHERE username = ?", (username,)
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1, (
        f"re-running the seed script for the same username must UPDATE the one row, "
        f"never create a second one -- got {len(rows)} rows"
    )
    second_hash = rows[0][0]
    assert second_hash != first_hash, (
        "the password hash must change after re-seeding with a new password"
    )
    assert _verify_scrypt_hash(second_hash, candidate_password="second-password-Zq3!")
    assert not _verify_scrypt_hash(second_hash, candidate_password="first-password-Xk9!"), (
        "the OLD password must no longer verify once the script has updated it"
    )

    # -- "and then logs in through the API" (closes walkthrough step 1: authenticate) --
    get_settings.cache_clear()
    settings = build_settings(
        database_url=database_url,
        config_dir=qa_config_dir,
        owner_username=username,
        owner_password="second-password-Zq3!",
    )
    with app_client(settings=settings) as client:
        login(client, username=username, password="second-password-Zq3!")
        session_resp = client.get("/api/v1/auth/session")

    assert session_resp.status_code == 200
    session_body = session_resp.json()
    assert session_body["authenticated"] is True, (
        f"expected an authenticated session after login, got {session_body}"
    )
