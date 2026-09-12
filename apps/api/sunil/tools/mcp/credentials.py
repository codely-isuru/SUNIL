"""C1 §5 — ``credential_env:`` → ``Settings``, and the minimal child env.

    each list entry is an UPPER_SNAKE env-var name (e.g. ``GITHUB_TOKEN``); its
    ``Settings`` field is the lowercased same name (``settings.github_token``),
    typed ``SecretStr`` ... A ``credential_env:`` name with no matching
    ``Settings`` field — or one whose value is unset — raises
    ``ToolAdapterStartupError`` at wiring time ... never a ``KeyError`` at call
    time.

The child gets **only** those variables plus :data:`BOOTSTRAP_ENV_NAMES`, never
the parent's environment (ARCHITECTURE_V2 TB4). That ordering matters: SUNIL's
own process env holds the session secret, the service token and (in the direct
lane) provider keys, none of which an MCP server has any business reading.

**And `credential_env:` itself is bounded** — :data:`GRANTABLE_CREDENTIAL_NAMES`
(Security wave-1 condition C-3). Filtering the parent environment is worth
nothing if the config file can name any `Settings` field it likes and have the
value handed over anyway.
"""

from __future__ import annotations

import os
from typing import Any

from sunil.core.tool_framework.base import ToolAdapterStartupError

#: The only parent variables that reach the child, and the reason each does: a
#: process with no PATH / SystemRoot cannot load its own runtime on Windows, and
#: a spawned interpreter needs its temp dir. Nothing here can carry a
#: credential, which is asserted in the unit test rather than trusted.
BOOTSTRAP_ENV_NAMES: tuple[str, ...] = (
    "PATH",
    "PATHEXT",
    "SystemRoot",
    "windir",
    "COMSPEC",
    "TEMP",
    "TMP",
    "TMPDIR",
    "HOME",
    "USERPROFILE",
    "LANG",
    "LC_ALL",
)


#: **The grantable-field allowlist** (Security wave-1 condition C-3,
#: `docs/THREAT_MODEL.md` §9). Every name a tool may legally be handed, and
#: nothing else.
#:
#: Without it, `_settings_value` resolved ANY lowercase-matching `Settings`
#: field, so `credential_env: [SESSION_SECRET]` — or `SUNIL_SERVICE_TOKEN`, or
#: `DATABASE_URL` — in `config/tools.yaml` handed the cookie-signing key, the
#: ADR-035 machine credential or the Postgres password to a spawned child **by a
#: config change alone**. ADR-016 makes `config/*.yaml` deployment-free and
#: mounted, which is exactly what made that one-line edit a full privilege
#: escalation with no code review anywhere on its path.
#:
#: A frozen CODE constant, deliberately, for the same reason ADR-033's named-host
#: set is one: a control that can be widened from the environment it is meant to
#: constrain is not a control. Adding a name here is a reviewed code change, and
#: the reviewer's question is a single one — "is this a credential belonging to a
#: TOOL, or a secret belonging to SUNIL?"
#:
#: Contents are the `credential_env:` / `auth_token_env:` entries of
#: `config/tools.yaml`, and they are asserted by name in
#: `tests/unit/tools/test_mcp_credentials.py`.
GRANTABLE_CREDENTIAL_NAMES: frozenset[str] = frozenset(
    {
        "GITHUB_TOKEN",  # config/tools.yaml: github_mcp.credential_env
        "SUNIL_N8N_MCP_AUTH_TOKEN",  # config/tools.yaml: n8n_mcp.auth_token_env
    }
)


def _settings_value(settings: Any, name: str) -> str:
    # The allowlist is checked FIRST — before the `Settings` lookup — so an
    # ungrantable name is refused for being ungrantable rather than for
    # happening not to resolve on this deployment's `Settings`. A lookup-first
    # order would silently start granting a name the day the field was added.
    if name not in GRANTABLE_CREDENTIAL_NAMES:
        raise ToolAdapterStartupError(
            f"credential_env names {name!r}, which is not grantable to a tool. "
            f"Only {sorted(GRANTABLE_CREDENTIAL_NAMES)} may be injected into a "
            "tool's environment (THREAT_MODEL §9 condition C-3): SUNIL's own "
            "secrets — the session signing key, the service token, the database "
            "URL — are not tool credentials, and config must not be able to grant "
            "them. Refusing to start the adapter."
        )
    field = name.lower()
    if not hasattr(settings, field):
        raise ToolAdapterStartupError(
            f"credential_env names {name!r}, but Settings has no field {field!r} "
            "(C1 §5: the field is the lowercased variable name, typed SecretStr)"
        )
    raw = getattr(settings, field)
    getter = getattr(raw, "get_secret_value", None)
    value = getter() if callable(getter) else raw
    if not isinstance(value, str) or value == "":
        raise ToolAdapterStartupError(
            f"credential_env names {name!r}, but settings.{field} is unset — "
            "refusing to start the adapter (C1 §5: a tool that cannot start is "
            "absent from the registry, never half-present)"
        )
    return value


def build_child_env(
    credential_env: list[str] | tuple[str, ...],
    settings: Any,
    *,
    base_env: dict[str, str] | None = None,
) -> dict[str, str]:
    """The exact environment an ``mcp_stdio`` child is spawned with.

    Raises :class:`ToolAdapterStartupError` — never ``KeyError`` — for a missing
    field or an unset value, and never puts a credential VALUE in the message,
    so a startup failure is safe to paste into an issue.
    """
    source = os.environ if base_env is None else base_env
    # Case-insensitive by key, keeping the SOURCE's spelling: Windows'
    # `os.environ` upper-cases its keys (`SYSTEMROOT`), POSIX does not
    # (`SystemRoot` would simply be absent), and a case-sensitive match here
    # silently ships a child with no PATH — which fails as "the MCP server
    # exited immediately", a long way from its cause.
    wanted = {name.lower(): name for name in BOOTSTRAP_ENV_NAMES}
    env = {
        key: value for key, value in source.items() if key.lower() in wanted
    }
    for name in credential_env:
        env[name] = _settings_value(settings, name)
    return env
