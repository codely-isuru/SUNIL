"""Unit test for `scripts/seed-owner.py`'s password hashing (T2, ADR-007).

The script lives at the repo root (`scripts/seed-owner.py`, hyphenated, so
it is not a normal importable module) rather than inside the `sunil`
package — it is loaded here by file path so its hashing format can be
checked without running the whole seeding flow against a database.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[4] / "scripts" / "seed-owner.py"

_ENCODING_PATTERN = re.compile(r"^scrypt\$16384\$8\$1\$[A-Za-z0-9+/=]+\$[A-Za-z0-9+/=]+$")


def _load_seed_owner_module():
    spec = importlib.util.spec_from_file_location("seed_owner_script", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hash_password_matches_the_adr_007_encoding() -> None:
    seed_owner = _load_seed_owner_module()

    encoded = seed_owner.hash_password("a-fake-test-password")

    assert _ENCODING_PATTERN.match(encoded), encoded
    parts = encoded.split("$")
    assert len(parts) == 6
    assert parts[0] == "scrypt"
    assert parts[1] == str(seed_owner._SCRYPT_N)
    assert parts[2] == str(seed_owner._SCRYPT_R)
    assert parts[3] == str(seed_owner._SCRYPT_P)


def test_hash_password_uses_a_fresh_random_salt_every_call() -> None:
    seed_owner = _load_seed_owner_module()

    first = seed_owner.hash_password("same-fake-password")
    second = seed_owner.hash_password("same-fake-password")

    assert first != second  # different salt -> different encoded string


def test_hash_password_never_contains_the_raw_password() -> None:
    seed_owner = _load_seed_owner_module()

    raw = "a-distinctive-fake-password-xyz"
    encoded = seed_owner.hash_password(raw)

    assert raw not in encoded
