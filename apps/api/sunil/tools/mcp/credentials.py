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


def _settings_value(settings: Any, name: str) -> str:
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
