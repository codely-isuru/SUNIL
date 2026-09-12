"""The sign-in module's own anti-oracle control, tested at the level it is claimed.

``sunil/api/routes/auth.py`` documents that "an unknown username still runs a
scrypt verification against a dummy hash, so response timing does not separate
'no such user' from 'wrong password'". That property holds only if
``_DUMMY_HASH`` survives ``verify_password``'s format checks: a value that fails
the ``scheme$salt$derived`` split returns ``False`` *before* ``hashlib.scrypt``
is ever called, and the unknown-username path becomes microseconds against the
known-username path's tens of milliseconds — a username-existence oracle
produced by the control that was supposed to prevent one (security review
integration-w1, C-2).

So these tests assert the work, not the wall clock: counting ``hashlib.scrypt``
calls is deterministic, where timing a KDF on a shared CI box is not.
"""

from __future__ import annotations

import hashlib

from sunil.api.routes import auth


def test_dummy_hash_parses_as_a_real_scrypt_hash() -> None:
    """It must satisfy the same shape ``verify_password`` validates against."""
    scheme, salt_hex, derived_hex = auth._DUMMY_HASH.split("$", 2)

    assert scheme == "scrypt"
    assert len(bytes.fromhex(salt_hex)) == auth._SALT_BYTES
    assert len(bytes.fromhex(derived_hex)) == auth._SCRYPT["dklen"]


def test_verifying_against_the_dummy_hash_computes_a_scrypt_hash(monkeypatch) -> None:
    """The unknown-username path pays the KDF cost instead of short-circuiting."""
    calls: list[dict] = []
    real_scrypt = hashlib.scrypt

    def counting_scrypt(*args, **kwargs):
        calls.append(kwargs)
        return real_scrypt(*args, **kwargs)

    monkeypatch.setattr(auth.hashlib, "scrypt", counting_scrypt)

    assert auth.verify_password("some-password", auth._DUMMY_HASH) is False
    assert len(calls) == 1


def test_dummy_and_real_hash_paths_do_the_same_scrypt_work(monkeypatch) -> None:
    """Unknown username and wrong password must be indistinguishable by work done."""
    known_hash = auth.hash_password("the-owner-password")

    calls: list[str] = []
    real_scrypt = hashlib.scrypt

    def counting_scrypt(*args, **kwargs):
        calls.append("scrypt")
        return real_scrypt(*args, **kwargs)

    monkeypatch.setattr(auth.hashlib, "scrypt", counting_scrypt)

    auth.verify_password("wrong-password", auth._DUMMY_HASH)
    unknown_username_work = len(calls)

    calls.clear()
    auth.verify_password("wrong-password", known_hash)
    wrong_password_work = len(calls)

    assert unknown_username_work == wrong_password_work == 1
