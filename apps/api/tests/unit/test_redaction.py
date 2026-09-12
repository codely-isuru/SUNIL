"""``sunil.redaction`` — the mechanism behind C5 §3 and ADR-006.

C5 §3 is normative: the values of inbound `Authorization` and `Cookie` headers
are NEVER written to logs, trace details, audit rows or error messages, on any
lane, for valid and invalid credentials alike. The load-bearing control is
structural (header values are not inputs to any logging call — asserted through
the real route in C5 contract test 7); this module is the second line, and the
one that is unit-testable.
"""

from __future__ import annotations

import pytest

from sunil.redaction import register, reset_registry_for_tests, scrub, scrub_processor


@pytest.fixture(autouse=True)
def _clean_registry() -> None:
    reset_registry_for_tests()


def test_a_registered_value_is_replaced_wherever_it_appears() -> None:
    register("s3cret-session-key-value", name="session_secret")

    scrubbed = scrub({"note": "signed with s3cret-session-key-value today"})

    assert "s3cret-session-key-value" not in scrubbed["note"]
    assert "«redacted:session_secret»" in scrubbed["note"]


@pytest.mark.parametrize("key", ["Authorization", "authorization", "Cookie", "set-cookie"])
def test_authorization_and_cookie_keys_are_redacted_by_name(key: str) -> None:
    """C5 §3 — an invalid bearer is exactly the value most worth not logging, and
    it was never registered anywhere, so name-based redaction is what catches it."""
    scrubbed = scrub({key: "Bearer never-registered-token"})

    assert scrubbed[key] == "«redacted»"


def test_nested_structures_are_walked() -> None:
    register("gh-token-value-1234", name="github_token")

    scrubbed = scrub({"a": [{"b": ("gh-token-value-1234",)}]})

    assert scrubbed["a"][0]["b"] == ("«redacted:github_token»",)


def test_an_unknown_type_is_coerced_and_scrubbed_never_passed_through() -> None:
    """The fail-safe default. An `isinstance` allowlist that returns unmatched
    values unchanged is not a redaction mechanism — the unmatched case (an
    exception, a dataclass, a NamedTuple with a masking repr) is exactly where a
    secret survives. This is the backend memory lesson from M1, kept."""
    register("leaky-value-abcdef", name="db_password")

    class Custom:
        def __repr__(self) -> str:
            return "Custom(password=leaky-value-abcdef)"

    scrubbed = scrub(Custom())

    assert isinstance(scrubbed, str)
    assert "leaky-value-abcdef" not in scrubbed


def test_a_hostile_repr_cannot_break_a_logging_path() -> None:
    class Exploding:
        def __repr__(self) -> str:
            raise RuntimeError("boom")

    assert "unrepresentable" in scrub(Exploding())


def test_safe_scalars_keep_their_type_so_json_shape_survives() -> None:
    assert scrub({"n": 42, "f": 1.5, "b": True, "none": None}) == {
        "n": 42,
        "f": 1.5,
        "b": True,
        "none": None,
    }


def test_high_signal_patterns_catch_an_unregistered_credential() -> None:
    scrubbed = scrub("pushed with ghp_abcdefghijklmnopqrstuvwxyz0123 just now")

    assert "ghp_abcdefghijklmnopqrstuvwxyz0123" not in scrubbed


def test_the_registry_ignores_values_too_short_to_redact_safely() -> None:
    """Redacting a 2-3 character value would corrupt unrelated text; ADR-006 does
    not intend that, and a 3-char secret is not a secret."""
    register("ab", name="tiny")

    assert scrub("a cab and a lab") == "a cab and a lab"


def test_scrub_processor_scrubs_a_whole_structlog_event_dict() -> None:
    register("bearer-token-value-9876", name="service_token")

    event = scrub_processor(None, "info", {"event": "x", "authorization": "Bearer y", "msg": "bearer-token-value-9876"})

    assert event["authorization"] == "«redacted»"
    assert "bearer-token-value-9876" not in event["msg"]


def test_scrub_never_mutates_its_input() -> None:
    register("in-place-secret-value", name="s")
    original = {"a": ["in-place-secret-value"]}

    scrub(original)

    assert original == {"a": ["in-place-secret-value"]}


def test_register_secrets_from_settings_registers_the_v2_secret_set() -> None:
    """§5's secrets + C5 §3's defence-in-depth clause: the configured
    `SUNIL_SERVICE_TOKEN` and `SESSION_SECRET` are registered at startup."""
    from sunil.redaction import register_secrets_from_settings
    from sunil.settings import Settings

    settings = Settings(
        _env_file=None,
        session_secret="the-session-secret-value",
        sunil_service_token="the-service-token-value",
        github_token="the-github-token-value",
    )

    register_secrets_from_settings(settings)

    scrubbed = scrub(
        "the-session-secret-value the-service-token-value the-github-token-value"
    )
    for secret in (
        "the-session-secret-value",
        "the-service-token-value",
        "the-github-token-value",
    ):
        assert secret not in scrubbed
