"""Unit tests — C1 §5's ``credential_env:`` → ``Settings`` mapping.

Closes the SECOND C1 row in ``docs/tasks/P0-fakes.md``'s deferred-coverage
table, which named exactly two tests to write here: "the mapping/redaction
round-trip, and a spawned child's env containing exactly the named variables and
nothing else" (the second lives in ``test_mcp_stdio.py``, where a real child
process reports its own environment).

C1 §5, verbatim: each ``credential_env:`` entry is an UPPER_SNAKE env-var name;
its ``Settings`` field is the lowercased same name, typed ``SecretStr``. A name
with no matching field — or one whose value is unset — raises
``ToolAdapterStartupError`` at WIRING time, never a ``KeyError`` at call time,
because a tool that cannot start is absent from the registry, never
half-present.
"""

from __future__ import annotations

import os

import pytest
from pydantic import BaseModel, SecretStr

from sunil.core.tool_framework.base import ToolAdapterStartupError
from sunil.tools.mcp.credentials import BOOTSTRAP_ENV_NAMES, build_child_env


class _Settings(BaseModel):
    github_token: SecretStr = SecretStr("unit-test-token-value")
    empty_token: SecretStr = SecretStr("")
    plain_token: str = "plain_value"


def test_the_named_variable_is_injected_from_the_lowercased_settings_field() -> None:
    env = build_child_env(["GITHUB_TOKEN"], _Settings(), base_env={})

    assert env["GITHUB_TOKEN"] == "unit-test-token-value"


def test_a_plain_str_settings_field_is_accepted_too() -> None:
    """The mapping is about the NAME, not the wrapper: a field that is not yet a
    ``SecretStr`` still resolves, so a partially-migrated ``Settings`` cannot
    make a tool unstartable for a reason the operator cannot see."""
    assert build_child_env(["PLAIN_TOKEN"], _Settings(), base_env={})["PLAIN_TOKEN"] == (
        "plain_value"
    )


def test_the_child_env_carries_nothing_from_the_parent_but_the_bootstrap_names() -> None:
    """C1 §5 / ARCHITECTURE_V2 TB4 — "never the parent's full environment"."""
    base = {
        "PATH": "/usr/bin",
        "SUNIL_SERVICE_TOKEN": "leak-me",
        "ANTHROPIC_API_KEY": "leak-me-too",
        "RANDOM_PARENT_VAR": "x",
    }

    env = build_child_env(["GITHUB_TOKEN"], _Settings(), base_env=base)

    assert set(env) == {"GITHUB_TOKEN", "PATH"}
    assert "SUNIL_SERVICE_TOKEN" not in env
    assert "ANTHROPIC_API_KEY" not in env


def test_bootstrap_names_are_a_short_documented_allowlist() -> None:
    """The child still has to be able to *execute*: on Windows a process with no
    ``SystemRoot``/``PATH`` cannot load its own runtime. The allowlist is
    therefore explicit, short, and contains nothing that could carry a
    credential."""
    assert "PATH" in BOOTSTRAP_ENV_NAMES
    assert "SystemRoot" in BOOTSTRAP_ENV_NAMES
    assert not any(
        marker in name.lower()
        for name in BOOTSTRAP_ENV_NAMES
        for marker in ("token", "key", "secret", "password")
    )


def test_an_unknown_credential_name_fails_at_wiring_time() -> None:
    with pytest.raises(ToolAdapterStartupError, match="NO_SUCH_TOKEN"):
        build_child_env(["NO_SUCH_TOKEN"], _Settings(), base_env={})


def test_an_unset_credential_value_fails_at_wiring_time() -> None:
    """An empty secret is the failure mode that otherwise surfaces as a 401 from
    the upstream SaaS, hours later, with no obvious cause."""
    with pytest.raises(ToolAdapterStartupError, match="EMPTY_TOKEN"):
        build_child_env(["EMPTY_TOKEN"], _Settings(), base_env={})


def test_the_error_message_never_contains_the_secret_value() -> None:
    class _Leaky(BaseModel):
        present_token: SecretStr = SecretStr("s3cr3t-value")

    # A name that resolves but whose SIBLING is secret: the message names the
    # variable, never a value, so a startup failure is safe to paste into an
    # issue.
    with pytest.raises(ToolAdapterStartupError) as caught:
        build_child_env(["MISSING_TOKEN"], _Leaky(), base_env={})

    assert "s3cr3t-value" not in str(caught.value)


def test_default_base_env_is_the_process_environment_filtered() -> None:
    os.environ["SUNIL_TEST_LEAK_MARKER"] = "leak"
    try:
        env = build_child_env(["GITHUB_TOKEN"], _Settings())
    finally:
        del os.environ["SUNIL_TEST_LEAK_MARKER"]

    assert "SUNIL_TEST_LEAK_MARKER" not in env
    assert env["GITHUB_TOKEN"] == "unit-test-token-value"
