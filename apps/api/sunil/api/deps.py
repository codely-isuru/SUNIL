"""Shared FastAPI dependencies: session auth, the CSRF/client-header check,
password verification, and the login throttle (ADR-007, ADR-008).
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from base64 import b64decode
from collections.abc import Callable

from fastapi import HTTPException, Request

from sunil.settings import get_settings

# -- Login throttle (ADR-007: 5 consecutive failures -> 60 s lockout, ------
# -- in-memory, keyed by username) -----------------------------------------

_FAILURE_THRESHOLD = 5
_LOCKOUT_SECONDS = 60.0

_throttle_lock = threading.Lock()
# username -> (consecutive_failure_count, locked_until_monotonic_or_None)
_throttle_state: dict[str, tuple[int, float | None]] = {}


class LoginThrottled(Exception):
    """Raised when a username has hit the 5-failure/60s lockout."""


def check_not_locked_out(username: str, *, clock: Callable[[], float] = time.monotonic) -> None:
    """Raise `LoginThrottled` if `username` is currently locked out.

    Does not itself count as an attempt — call this before verifying the
    password, then call `record_login_failure`/`record_login_success`
    after, exactly once per attempt.
    """
    with _throttle_lock:
        _count, locked_until = _throttle_state.get(username, (0, None))
        if locked_until is not None and clock() < locked_until:
            raise LoginThrottled(f"too many failed login attempts for {username!r}")


def record_login_failure(username: str, *, clock: Callable[[], float] = time.monotonic) -> None:
    with _throttle_lock:
        count, _locked_until = _throttle_state.get(username, (0, None))
        count += 1
        locked_until = clock() + _LOCKOUT_SECONDS if count >= _FAILURE_THRESHOLD else None
        _throttle_state[username] = (count, locked_until)


def record_login_success(username: str) -> None:
    """A successful login clears the failure count entirely — ADR-007
    does not specify a decay policy, so the simplest one (reset on
    success) is used."""
    with _throttle_lock:
        _throttle_state.pop(username, None)


def reset_login_throttle_for_tests() -> None:
    """Test-only: this module holds process-wide state by design (a
    lockout must survive across requests), so tests must scope themselves
    explicitly rather than relying on import order."""
    with _throttle_lock:
        _throttle_state.clear()


# -- Password verification (ADR-007's exact scrypt encoding) ---------------


def verify_password(password: str, encoded_hash: str) -> bool:
    """Verify `password` against the ADR-007 encoding
    `scrypt$n$r$p$salt_b64$hash_b64` (the same format
    `scripts/seed-owner.py` writes). Never raises on a malformed hash —
    returns `False`, so a corrupt row fails closed rather than 500s.
    """
    try:
        scheme, n_s, r_s, p_s, salt_b64, hash_b64 = encoded_hash.split("$")
        if scheme != "scrypt":
            return False
        n, r, p = int(n_s), int(r_s), int(p_s)
        salt = b64decode(salt_b64)
        expected = b64decode(hash_b64)
    except (ValueError, TypeError):
        return False

    candidate = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected)
    )
    return hmac.compare_digest(candidate, expected)


# -- Auth / CSRF dependencies -----------------------------------------------


def require_owner_session(request: Request) -> str:
    """401 if there is no authenticated session (ADR-007). Returns the
    session's `user_id` on success, for handlers that need it."""
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="authentication required")
    return user_id


def require_client_header(request: Request) -> None:
    """403 if `X-SUNIL-Client: web` is missing or wrong, or if an `Origin`
    header is present and does not match `WEB_ORIGIN` (ADR-008's CSRF
    control — a custom header cannot be sent cross-origin without a
    successful preflight, and the preflight only succeeds for
    `WEB_ORIGIN`). `Origin` is not required to be present at all — some
    legitimate non-browser or same-origin callers omit it; only a
    *mismatched* `Origin` is rejected.
    """
    if request.headers.get("X-SUNIL-Client") != "web":
        raise HTTPException(status_code=403, detail="missing or invalid X-SUNIL-Client header")

    origin = request.headers.get("origin")
    if origin is not None and origin != get_settings().web_origin:
        raise HTTPException(status_code=403, detail="origin does not match WEB_ORIGIN")
