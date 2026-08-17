"""Unit tests for `sunil.api.deps` (T5): password verification, the login
throttle, and the two auth/CSRF dependencies.
"""

from __future__ import annotations

import base64
import hashlib

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from sunil.api.deps import (
    LoginThrottled,
    check_not_locked_out,
    record_login_failure,
    record_login_success,
    require_client_header,
    require_owner_session,
    reset_login_throttle_for_tests,
    verify_password,
)

# -- test helpers -------------------------------------------------------------


def _encode_scrypt(password: str, *, n: int = 2**14, r: int = 8, p: int = 1) -> str:
    salt = b"0123456789ABCDEF"  # fixed for deterministic tests
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=32)
    salt_b64 = base64.b64encode(salt).decode()
    hash_b64 = base64.b64encode(digest).decode()
    return f"scrypt${n}${r}${p}${salt_b64}${hash_b64}"


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self._now = start

    def __call__(self) -> float:
        return self._now

    def advance(self, seconds: float) -> None:
        self._now += seconds


def _make_request(*, headers: dict[str, str] | None = None, session: dict | None = None) -> Request:
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()],
        "query_string": b"",
    }
    request = Request(scope)
    request.scope["session"] = session if session is not None else {}
    return request


@pytest.fixture(autouse=True)
def _clean_throttle():
    reset_login_throttle_for_tests()
    yield
    reset_login_throttle_for_tests()


# -- verify_password ----------------------------------------------------------


def test_verify_password_accepts_the_correct_password() -> None:
    encoded = _encode_scrypt("correct-horse-battery-staple")
    assert verify_password("correct-horse-battery-staple", encoded) is True


def test_verify_password_rejects_the_wrong_password() -> None:
    encoded = _encode_scrypt("correct-horse-battery-staple")
    assert verify_password("wrong-password", encoded) is False


@pytest.mark.parametrize(
    "malformed",
    [
        "not-the-right-format-at-all",
        "bcrypt$16384$8$1$c2FsdA==$aGFzaA==",  # wrong scheme
        "scrypt$notanumber$8$1$c2FsdA==$aGFzaA==",  # non-numeric n
        "scrypt$16384$8$1$not-valid-base64!!!$aGFzaA==",
    ],
)
def test_verify_password_fails_closed_on_a_malformed_hash(malformed: str) -> None:
    assert verify_password("anything", malformed) is False


# -- login throttle -----------------------------------------------------------


def test_check_not_locked_out_passes_with_no_prior_failures() -> None:
    check_not_locked_out("nobody-yet")  # must not raise


def test_five_failures_lock_out_the_sixth_attempt() -> None:
    clock = _FakeClock()
    username = "flaky-user"

    for _ in range(5):
        record_login_failure(username, clock=clock)

    with pytest.raises(LoginThrottled):
        check_not_locked_out(username, clock=clock)


def test_fewer_than_five_failures_do_not_lock_out() -> None:
    clock = _FakeClock()
    username = "almost-locked"

    for _ in range(4):
        record_login_failure(username, clock=clock)

    check_not_locked_out(username, clock=clock)  # must not raise


def test_lockout_expires_after_sixty_seconds() -> None:
    clock = _FakeClock()
    username = "will-recover"

    for _ in range(5):
        record_login_failure(username, clock=clock)

    with pytest.raises(LoginThrottled):
        check_not_locked_out(username, clock=clock)

    clock.advance(60.1)
    check_not_locked_out(username, clock=clock)  # must not raise now


def test_a_success_clears_the_failure_count() -> None:
    clock = _FakeClock()
    username = "redeemed-user"

    for _ in range(4):
        record_login_failure(username, clock=clock)
    record_login_success(username)

    # Failing four more times afterward should not lock out — the count
    # was reset, not merely paused.
    for _ in range(4):
        record_login_failure(username, clock=clock)
    check_not_locked_out(username, clock=clock)  # must not raise


# -- require_owner_session ----------------------------------------------------


def test_require_owner_session_rejects_a_request_with_no_session() -> None:
    request = _make_request(session={})

    with pytest.raises(HTTPException) as exc_info:
        require_owner_session(request)

    assert exc_info.value.status_code == 401


def test_require_owner_session_returns_the_user_id_when_present() -> None:
    request = _make_request(session={"user_id": "user-123"})

    assert require_owner_session(request) == "user-123"


# -- require_client_header ----------------------------------------------------


def test_require_client_header_rejects_a_missing_header() -> None:
    request = _make_request(headers={})

    with pytest.raises(HTTPException) as exc_info:
        require_client_header(request)

    assert exc_info.value.status_code == 403


def test_require_client_header_rejects_the_wrong_value() -> None:
    request = _make_request(headers={"X-SUNIL-Client": "not-web"})

    with pytest.raises(HTTPException) as exc_info:
        require_client_header(request)

    assert exc_info.value.status_code == 403


def test_require_client_header_accepts_web_with_no_origin_header() -> None:
    request = _make_request(headers={"X-SUNIL-Client": "web"})

    require_client_header(request)  # must not raise


@pytest.fixture
def _fixed_web_origin(monkeypatch: pytest.MonkeyPatch):
    """`require_client_header` reads `get_settings().web_origin` — pin it
    explicitly (env + cache-clear, both directions) so these two tests are
    deterministic regardless of what any other test in the process has
    already done to the cached `Settings` singleton."""
    from sunil.settings import get_settings

    for key, value in {
        "ANTHROPIC_API_KEY": "sk-ant-fake",
        "GITHUB_TOKEN": "github_pat_fake",
        "OPENAI_API_KEY": "sk-fake-test-value-for-openai",
        "SESSION_SECRET": "fake-secret",
        "OWNER_USERNAME": "test-owner",
        "OWNER_PASSWORD": "fake-password",
        "WEB_ORIGIN": "http://localhost:3000",
    }.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_require_client_header_rejects_a_mismatched_origin(_fixed_web_origin: None) -> None:
    request = _make_request(headers={"X-SUNIL-Client": "web", "Origin": "http://evil.example"})

    with pytest.raises(HTTPException) as exc_info:
        require_client_header(request)

    assert exc_info.value.status_code == 403


def test_require_client_header_accepts_the_configured_web_origin(_fixed_web_origin: None) -> None:
    request = _make_request(headers={"X-SUNIL-Client": "web", "Origin": "http://localhost:3000"})

    require_client_header(request)  # must not raise
