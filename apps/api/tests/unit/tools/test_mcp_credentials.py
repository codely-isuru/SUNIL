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
from sunil.tools.mcp.credentials import (
    BOOTSTRAP_ENV_NAMES,
    GRANTABLE_CREDENTIAL_NAMES,
    build_child_env,
)

#: The three Settings secrets a tool must never be able to ask for (Security
#: wave-1 condition C-3, THREAT_MODEL §9). Each is real and each is fatal in a
#: different way: the cookie-signing key forges an owner session, the service
#: token is the ADR-035 machine lane, the database URL embeds the Postgres
#: password.
UNGRANTABLE = ("SESSION_SECRET", "SUNIL_SERVICE_TOKEN", "DATABASE_URL")


class _Settings(BaseModel):
    github_token: SecretStr = SecretStr("unit-test-token-value")
    sunil_n8n_mcp_auth_token: SecretStr = SecretStr("")
    # The three C-3 names, PRESENT and populated exactly as they are on the real
    # `Settings`: the allowlist has to refuse them because they are ungrantable,
    # not because the lookup happened to fail.
    session_secret: SecretStr = SecretStr("cookie-signing-key")
    sunil_service_token: SecretStr = SecretStr("machine-lane-token")
    database_url: SecretStr = SecretStr("postgresql+psycopg://sunil:pw@localhost/sunil")


class _PlainGitHub(BaseModel):
    github_token: str = "plain_value"


def test_the_named_variable_is_injected_from_the_lowercased_settings_field() -> None:
    env = build_child_env(["GITHUB_TOKEN"], _Settings(), base_env={})

    assert env["GITHUB_TOKEN"] == "unit-test-token-value"


def test_a_plain_str_settings_field_is_accepted_too() -> None:
    """The mapping is about the NAME, not the wrapper: a field that is not yet a
    ``SecretStr`` still resolves, so a partially-migrated ``Settings`` cannot
    make a tool unstartable for a reason the operator cannot see."""
    assert build_child_env(["GITHUB_TOKEN"], _PlainGitHub(), base_env={})[
        "GITHUB_TOKEN"
    ] == "plain_value"


# --------------------------------------------------------------------------- #
# Security wave-1 condition C-3 — the grantable-field allowlist
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("name", UNGRANTABLE)
def test_a_config_edit_cannot_grant_an_ungrantable_settings_secret(name: str) -> None:
    """C-3, verbatim: ``credential_env: [SESSION_SECRET]`` (or
    ``SUNIL_SERVICE_TOKEN``, or ``DATABASE_URL``) in ``config/tools.yaml`` "hands
    the cookie-signing key to a spawned child by config change alone".

    Before the allowlist, ``_settings_value`` resolved ANY lowercase-matching
    ``Settings`` field, so every one of these three names produced a live secret
    in the child's environment. The refusal is a startup failure — the tool is
    absent from the registry rather than half-present with a stolen credential —
    and the message names the variable, never its value.
    """
    with pytest.raises(ToolAdapterStartupError) as caught:
        build_child_env([name], _Settings(), base_env={})

    message = str(caught.value)
    assert name in message
    assert "cookie-signing-key" not in message
    assert "machine-lane-token" not in message
    assert "pw@localhost" not in message


def test_the_allowlist_holds_tool_credentials_only() -> None:
    """The allowlist is the whole control, so its CONTENT is the assertion: only
    names a tool legitimately needs (``config/tools.yaml``'s ``credential_env:``
    and ``auth_token_env:`` entries), and none of the process's own secrets."""
    assert GRANTABLE_CREDENTIAL_NAMES == frozenset(
        {"GITHUB_TOKEN", "SUNIL_N8N_MCP_AUTH_TOKEN"}
    )
    assert set(UNGRANTABLE).isdisjoint(GRANTABLE_CREDENTIAL_NAMES)


def test_the_allowlist_is_checked_before_the_settings_lookup() -> None:
    """Order matters for what the operator is told: an ungrantable name is
    refused for BEING ungrantable, whether or not this deployment happens to
    have that field set. A lookup-first order would answer "no such field" for a
    `Settings` that simply had not grown the attribute yet — and would start
    granting it the day it did."""

    class _NoSecrets(BaseModel):
        github_token: SecretStr = SecretStr("t")

    with pytest.raises(ToolAdapterStartupError, match="not grantable"):
        build_child_env(["SESSION_SECRET"], _NoSecrets(), base_env={})


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


def test_a_grantable_name_with_no_settings_field_fails_at_wiring_time() -> None:
    """The C1 §5 mapping failure, still reached once the allowlist admits the
    name: a `Settings` that has not grown the field is a wiring-time refusal,
    never a `KeyError` at call time."""

    class _Partial(BaseModel):
        github_token: SecretStr = SecretStr("t")

    with pytest.raises(ToolAdapterStartupError, match="sunil_n8n_mcp_auth_token"):
        build_child_env(["SUNIL_N8N_MCP_AUTH_TOKEN"], _Partial(), base_env={})


def test_an_unset_credential_value_fails_at_wiring_time() -> None:
    """An empty secret is the failure mode that otherwise surfaces as a 401 from
    the upstream SaaS, hours later, with no obvious cause."""
    with pytest.raises(ToolAdapterStartupError, match="SUNIL_N8N_MCP_AUTH_TOKEN"):
        build_child_env(["SUNIL_N8N_MCP_AUTH_TOKEN"], _Settings(), base_env={})


def test_the_error_message_never_contains_the_secret_value() -> None:
    class _Leaky(BaseModel):
        github_token: SecretStr = SecretStr("s3cr3t-value")

    # A name that fails to resolve while a SIBLING is secret: the message names
    # the variable, never a value, so a startup failure is safe to paste into an
    # issue.
    with pytest.raises(ToolAdapterStartupError) as caught:
        build_child_env(["SUNIL_N8N_MCP_AUTH_TOKEN"], _Leaky(), base_env={})

    assert "s3cr3t-value" not in str(caught.value)


def test_default_base_env_is_the_process_environment_filtered() -> None:
    os.environ["SUNIL_TEST_LEAK_MARKER"] = "leak"
    try:
        env = build_child_env(["GITHUB_TOKEN"], _Settings())
    finally:
        del os.environ["SUNIL_TEST_LEAK_MARKER"]

    assert "SUNIL_TEST_LEAK_MARKER" not in env
    assert env["GITHUB_TOKEN"] == "unit-test-token-value"
