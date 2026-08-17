"""Unit tests for `sunil.redaction` (T4 — ADR-006, ET-10).

Every test resets the module-level registry first (`reset_registry_for_tests`)
so one test's registered secret can never leak into another's assertions —
this module holds process-wide state by design (the registry must survive
from `register_secrets_from_settings()` at startup to every later log line
and insert), so tests must scope themselves explicitly.
"""

from __future__ import annotations

import json

import pytest
from sunil.redaction import (
    register,
    register_secrets_from_settings,
    reset_registry_for_tests,
    scrub,
    scrub_processor,
)
from sunil.settings import Settings


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


def test_scrub_redacts_a_registered_value_wherever_it_appears_in_a_string() -> None:
    register("sk-ant-fake-registered-secret", name="anthropic_api_key")

    result = scrub("the key is sk-ant-fake-registered-secret, don't share it")

    assert "sk-ant-fake-registered-secret" not in result
    assert "«redacted:anthropic_api_key»" in result


def test_scrub_leaves_unrelated_text_untouched() -> None:
    register("some-fake-secret-value", name="whatever")

    result = scrub("nothing sensitive in this sentence at all")

    assert result == "nothing sensitive in this sentence at all"


def test_scrub_redacts_high_signal_patterns_even_when_never_registered() -> None:
    """A stray token that was never explicitly `register()`-ed is still
    caught by shape (ADR-006's second, independent layer)."""
    text = (
        "leaked: sk-ant-fakeabcdefghijklmnopqrstuvwxyz and "
        "ghp_fakeABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 and "
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789"
    )

    result = scrub(text)

    assert "sk-ant-fakeabcdefghijklmnopqrstuvwxyz" not in result
    assert "ghp_fakeABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" not in result
    assert "Bearer abcdefghijklmnopqrstuvwxyz0123456789" not in result
    assert "«redacted»" in result


def test_scrub_redacts_dict_values_by_key_name_regardless_of_registration() -> None:
    payload = {
        "api_key": "not-registered-but-should-still-be-redacted",
        "Authorization": "Bearer something",
        "token": "abc123",
        "password": "hunter2",
        "cookie": "session=abc",
        "harmless": "this stays",
    }

    result = scrub(payload)

    assert result["api_key"] == "«redacted»"
    assert result["Authorization"] == "«redacted»"
    assert result["token"] == "«redacted»"
    assert result["password"] == "«redacted»"
    assert result["cookie"] == "«redacted»"
    assert result["harmless"] == "this stays"


def test_scrub_recurses_into_nested_dicts_and_lists() -> None:
    register("nested-fake-secret", name="fake")
    payload = {
        "outer": {
            "inner_list": ["ok", "has nested-fake-secret inside", {"secret": "irrelevant"}],
        }
    }

    result = scrub(payload)

    assert result["outer"]["inner_list"][0] == "ok"
    assert "nested-fake-secret" not in result["outer"]["inner_list"][1]
    assert result["outer"]["inner_list"][2]["secret"] == "«redacted»"


def test_scrub_does_not_mutate_the_original_object() -> None:
    original = {"token": "abc123", "list": ["a", "b"]}
    scrub(original)

    assert original["token"] == "abc123"
    assert original["list"] == ["a", "b"]


def test_scrub_preserves_non_string_scalars() -> None:
    payload = {"count": 3, "enabled": True, "nothing": None}

    result = scrub(payload)

    assert result == {"count": 3, "enabled": True, "nothing": None}


def test_register_ignores_values_shorter_than_four_characters() -> None:
    register("ok", name="too_short")

    # "ok" must not become a redaction landmine in ordinary text.
    assert scrub("that's ok, thanks") == "that's ok, thanks"


def test_scrub_processor_scrubs_a_full_structlog_event_dict() -> None:
    register("event-dict-fake-secret", name="fake")
    event_dict = {"event": "something happened", "detail": "contains event-dict-fake-secret here"}

    result = scrub_processor(None, "info", event_dict)

    assert "event-dict-fake-secret" not in result["detail"]
    assert "«redacted:fake»" in result["detail"]


# -- Fail-safe fallback: QA's review bounce (T4 blockers 1 and 2) ------------
#
# LESSON (backend_engineer memory): a redaction function that dispatches on
# a fixed list of types must treat the unmatched case as unsafe, not as a
# passthrough. `scrub()`'s original isinstance chain (str/dict/list/tuple)
# returned every other type unchanged — an exception instance, a NamedTuple,
# any custom object — which is exactly where a secret survived. These tests
# are QA's exact reproduction, kept as a permanent regression suite.


class _BoomError(Exception):
    """Stands in for any exception whose message happens to carry a
    secret — completely ordinary structlog usage is `log.error(...,
    error=exc)` rather than `exc_info=`."""


class _SecretBearingRepr:
    """A custom object whose `__repr__` embeds a secret — standing in for
    a Pydantic model or dataclass logged directly rather than as a dict."""

    def __init__(self, secret: str) -> None:
        self._secret = secret

    def __repr__(self) -> str:
        return f"SecretBearingRepr(secret={self._secret!r})"


def test_scrub_redacts_a_registered_secret_inside_an_exception_object() -> None:
    register("sk-ant-fakeTHISISASECRETVALUE1234567890", name="anthropic_api_key")
    exc = _BoomError("bad key sk-ant-fakeTHISISASECRETVALUE1234567890")

    result = scrub(exc)

    assert isinstance(result, str)
    assert "sk-ant-fakeTHISISASECRETVALUE1234567890" not in result
    assert "«redacted:anthropic_api_key»" in result


def test_scrub_redacts_an_exception_nested_inside_a_dict_value() -> None:
    """The `detail={"error": exc}` shape QA demonstrated against the real
    `shared_processors` chain."""
    register("sk-ant-fakeTHISISASECRETVALUE1234567890", name="anthropic_api_key")
    payload = {"error": _BoomError("bad key sk-ant-fakeTHISISASECRETVALUE1234567890")}

    result = scrub(payload)

    assert isinstance(result["error"], str)
    assert "sk-ant-fakeTHISISASECRETVALUE1234567890" not in result["error"]


def test_scrub_redacts_a_custom_objects_secret_bearing_repr() -> None:
    register("a-registered-fake-secret-value", name="fake")
    obj = _SecretBearingRepr("a-registered-fake-secret-value")

    result = scrub(obj)

    assert isinstance(result, str)
    assert "a-registered-fake-secret-value" not in result
    assert "«redacted:fake»" in result


def test_scrub_falls_back_safely_when_repr_itself_raises() -> None:
    class _HostileRepr:
        def __repr__(self) -> str:
            raise RuntimeError("boom")

    result = scrub(_HostileRepr())

    assert result == "<unrepresentable _HostileRepr>"


def test_scrub_preserves_safe_scalar_types_exactly() -> None:
    assert scrub(42) == 42
    assert scrub(3.14) == 3.14
    assert scrub(True) is True
    assert scrub(None) is None


def test_scrub_treats_a_named_tuple_as_unsafe_for_positional_iteration() -> None:
    """A `NamedTuple` often has its own privacy-aware `__repr__`
    (`sqlalchemy.engine.URL` masks its password this way) that naive
    positional-tuple iteration would bypass entirely — proven directly
    against the real SQLAlchemy type, not a stand-in."""
    from sqlalchemy.engine import make_url

    url = make_url("postgresql+psycopg://sunil:DbPassw0rdLeak@db:5432/sunil")

    result = scrub(url)

    assert isinstance(result, str)
    assert "DbPassw0rdLeak" not in result
    assert "***" in result  # SQLAlchemy's own masking, now what scrub() preserved


def test_scrub_through_the_real_structlog_chain_redacts_an_exception_value() -> None:
    """QA's exact end-to-end reproduction: log a caught exception object as
    a field value through the real, wired `configure_logging()` chain, and
    confirm the rendered JSON line never carries the secret."""
    import io
    import logging as stdlib_logging

    from sunil.logging import configure_logging, get_logger

    register("sk-ant-fakeTHISISASECRETVALUE1234567890", name="anthropic_api_key")
    configure_logging(log_level="DEBUG", json_output=True)

    root = stdlib_logging.getLogger()
    original_handlers = list(root.handlers)
    buffer = io.StringIO()
    handler = stdlib_logging.StreamHandler(buffer)
    handler.setFormatter(original_handlers[0].formatter)
    root.handlers = [handler]
    try:
        get_logger("test_redaction_real_chain").info(
            "bound_exception_case",
            error=_BoomError("bad key sk-ant-fakeTHISISASECRETVALUE1234567890"),
        )
    finally:
        root.handlers = original_handlers

    output = buffer.getvalue()
    assert "sk-ant-fakeTHISISASECRETVALUE1234567890" not in output
    # The JSON renderer escapes non-ASCII (ensure_ascii, the json module's
    # default) so «» becomes «/» in the raw text — decode before
    # asserting on the marker rather than string-matching the raw bytes.
    decoded = json.loads(output)
    assert "«redacted:anthropic_api_key»" in decoded["error"]


def test_register_secrets_from_settings_registers_every_m1_secret() -> None:
    settings = Settings(
        _env_file=None,
        ANTHROPIC_API_KEY="sk-ant-fake-from-settings",
        GITHUB_TOKEN="github_pat_fake-from-settings",
        OPENAI_API_KEY="sk-fake-openai-from-settings",
        SESSION_SECRET="fake-session-secret-from-settings",
        OWNER_USERNAME="test-owner",
        OWNER_PASSWORD="fake-owner-password-from-settings",
    )

    register_secrets_from_settings(settings)

    for raw in (
        "sk-ant-fake-from-settings",
        "github_pat_fake-from-settings",
        "sk-fake-openai-from-settings",
        "fake-session-secret-from-settings",
        "fake-owner-password-from-settings",
    ):
        assert raw not in scrub(f"a log line mentioning {raw}")


def test_register_secrets_from_settings_tolerates_an_absent_provider_key() -> None:
    """T25: provider API keys are optional (`SecretStr | None`) -- the
    owner has an OpenAI key and no Anthropic key. `register_secrets_from_
    settings()` must not crash calling `.get_secret_value()` on `None`; it
    must simply skip registering whichever provider key is absent, and
    still register the one that is present plus every other secret."""
    settings = Settings(
        _env_file=None,
        GITHUB_TOKEN="github_pat_fake-from-settings-2",
        OPENAI_API_KEY="sk-fake-openai-from-settings-2",
        SESSION_SECRET="fake-session-secret-from-settings-2",
        OWNER_USERNAME="test-owner",
        OWNER_PASSWORD="fake-owner-password-from-settings-2",
    )
    assert settings.anthropic_api_key is None

    register_secrets_from_settings(settings)  # must not raise

    for raw in (
        "github_pat_fake-from-settings-2",
        "sk-fake-openai-from-settings-2",
        "fake-session-secret-from-settings-2",
        "fake-owner-password-from-settings-2",
    ):
        assert raw not in scrub(f"a log line mentioning {raw}")
