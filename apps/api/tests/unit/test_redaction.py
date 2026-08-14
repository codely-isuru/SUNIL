"""Unit tests for `sunil.redaction` (T4 — ADR-006, ET-10).

Every test resets the module-level registry first (`reset_registry_for_tests`)
so one test's registered secret can never leak into another's assertions —
this module holds process-wide state by design (the registry must survive
from `register_secrets_from_settings()` at startup to every later log line
and insert), so tests must scope themselves explicitly.
"""

from __future__ import annotations

import pytest
from sunil.redaction import (
    redaction_processor,
    register,
    register_secrets_from_settings,
    reset_registry_for_tests,
    scrub,
)
from sunil.settings import Settings


@pytest.fixture(autouse=True)
def _clean_registry():
    reset_registry_for_tests()
    yield
    reset_registry_for_tests()


def test_scrub_redacts_a_registered_value_wherever_it_appears_in_a_string() -> None:
    register("sk-ant-a-fake-registered-secret", name="anthropic_api_key")

    result = scrub("the key is sk-ant-a-fake-registered-secret, don't share it")

    assert "sk-ant-a-fake-registered-secret" not in result
    assert "«redacted:anthropic_api_key»" in result


def test_scrub_leaves_unrelated_text_untouched() -> None:
    register("some-fake-secret-value", name="whatever")

    result = scrub("nothing sensitive in this sentence at all")

    assert result == "nothing sensitive in this sentence at all"


def test_scrub_redacts_high_signal_patterns_even_when_never_registered() -> None:
    """A stray token that was never explicitly `register()`-ed is still
    caught by shape (ADR-006's second, independent layer)."""
    text = (
        "leaked: sk-ant-abcdefghijklmnopqrstuvwxyz and "
        "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 and "
        "Authorization: Bearer abcdefghijklmnopqrstuvwxyz0123456789"
    )

    result = scrub(text)

    assert "sk-ant-abcdefghijklmnopqrstuvwxyz" not in result
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789" not in result
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


def test_redaction_processor_scrubs_a_full_structlog_event_dict() -> None:
    register("event-dict-fake-secret", name="fake")
    event_dict = {"event": "something happened", "detail": "contains event-dict-fake-secret here"}

    result = redaction_processor(None, "info", event_dict)

    assert "event-dict-fake-secret" not in result["detail"]
    assert "«redacted:fake»" in result["detail"]


def test_register_secrets_from_settings_registers_every_m1_secret() -> None:
    settings = Settings(
        _env_file=None,
        ANTHROPIC_API_KEY="sk-ant-fake-from-settings",
        GITHUB_TOKEN="github_pat_fake-from-settings",
        SESSION_SECRET="fake-session-secret-from-settings",
        OWNER_USERNAME="test-owner",
        OWNER_PASSWORD="fake-owner-password-from-settings",
    )

    register_secrets_from_settings(settings)

    for raw in (
        "sk-ant-fake-from-settings",
        "github_pat_fake-from-settings",
        "fake-session-secret-from-settings",
        "fake-owner-password-from-settings",
    ):
        assert raw not in scrub(f"a log line mentioning {raw}")
