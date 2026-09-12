"""Unit tests — the manager's own hasher and params redactor.

The hasher is C1 §6.4's normative rule implemented in PRODUCTION code
(``sunil.core.tool_framework.canonical``). QA keeps an independent copy in
``tests/fakes/canonical.py``; if the two ever disagree, C1 contract test 4's
``args_hash`` assertion fails. These tests pin the production one against the
rule's own words (and a literal digest), never against the QA copy — comparing
two implementations that drifted together would pass while both were wrong.
"""

from __future__ import annotations

from hashlib import sha256

from pydantic import BaseModel

from sunil.core.tool_framework.canonical import args_hash, canonical_json
from sunil.core.tool_framework.redaction import redact_params


class _Params(BaseModel, extra="forbid"):
    key: str
    value: str


def test_canonical_json_sorts_keys_and_uses_compact_separators() -> None:
    assert canonical_json({"value": "1", "key": "demo"}) == '{"key":"demo","value":"1"}'


def test_args_hash_is_the_sha256_of_the_canonical_form() -> None:
    expected = sha256(b'{"key":"demo","value":"1"}').hexdigest()

    assert args_hash(_Params(key="demo", value="1")) == expected
    assert args_hash({"key": "demo", "value": "1"}) == expected
    assert args_hash({"value": "1", "key": "demo"}) == expected
    assert len(expected) == 64


def test_args_hash_separates_a_different_value() -> None:
    assert args_hash({"key": "demo", "value": "1"}) != args_hash(
        {"key": "demo", "value": "2"}
    )


def test_args_hash_is_stable_for_nested_structures() -> None:
    """Sorting must reach nested dicts too — otherwise two identical calls whose
    nested params were built in a different order would park two approvals with
    different hashes, and neither would bind on resume."""
    first = args_hash({"outer": {"b": 1, "a": [1, {"y": 2, "x": 3}]}})
    second = args_hash({"outer": {"a": [1, {"x": 3, "y": 2}], "b": 1}})

    assert first == second


def test_redact_params_masks_secret_shaped_keys_at_every_depth() -> None:
    redacted = redact_params(
        {
            "project_key": "sunil",
            "github_token": "unit-test-secret",
            "nested": {"Authorization": "Bearer abc", "safe": "keep"},
            "items": [{"api_key": "sk-123"}, {"count": 2}],
        }
    )

    assert redacted == {
        "project_key": "sunil",
        "github_token": "[redacted]",
        "nested": {"Authorization": "[redacted]", "safe": "keep"},
        "items": [{"api_key": "[redacted]"}, {"count": 2}],
    }


def test_redact_params_does_not_mutate_its_input() -> None:
    original = {"token": "abc", "nested": {"password": "p"}}
    snapshot = {"token": "abc", "nested": {"password": "p"}}

    redact_params(original)

    assert original == snapshot
