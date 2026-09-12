"""``params_redacted`` — what the audit row and the approval card may carry.

C1 §2.1 step 3 / §2.2 require a ``params_redacted`` dict on the
``ToolCallAttempt`` row and on the C4 ``ParkRequest``. Both are read by humans
(the audit browser, the approval card), so a credential that arrived as a
parameter must not land in either.

**Scope note (integration requirement, not a control claim).** ADR-006's
redaction registry — the process-wide one that knows every ``SecretStr``
``Settings`` field by value — belongs to the spine lane (``sunil/redaction.py``
in the M1 reference) and does not exist in this worktree's timeline. This module
is the key-name floor the chokepoint applies unconditionally: it cannot know a
secret by its value, so when the registry lands, the manager must call it on
top of this, never instead of it. Recorded in ``docs/tasks/S-A-tools.md``.

Key-name matching is a denylist and therefore bypassable by construction — the
same posture C1 §3 states for its strip list. It is defence in depth, never the
reason a secret is safe: the load-bearing rule is C1 §5 (credentials reach a
tool through the child env from ``Settings``, never through params).
"""

from __future__ import annotations

from typing import Any

REDACTED = "[redacted]"

#: Substrings that make a key's VALUE unprintable. Matched case-insensitively
#: against the key name, anywhere in it (``github_token``, ``Authorization``,
#: ``client_secret`` all match).
_SECRET_KEY_MARKERS = (
    "token",
    "secret",
    "password",
    "passwd",
    "api_key",
    "apikey",
    "private_key",
    "authorization",
    "credential",
    "cookie",
    "session",
)


def _is_secret_key(key: str) -> bool:
    lowered = key.lower()
    return any(marker in lowered for marker in _SECRET_KEY_MARKERS)


def redact_params(params: Any) -> Any:
    """Return a deep copy with secret-shaped keys' values replaced.

    Never mutates its input: the manager hands the SAME validated params to the
    handler, and a redactor that edited them in place would execute the tool
    against ``"[redacted]"``.
    """
    if isinstance(params, dict):
        return {
            key: REDACTED if _is_secret_key(str(key)) else redact_params(value)
            for key, value in params.items()
        }
    if isinstance(params, list):
        return [redact_params(item) for item in params]
    if isinstance(params, tuple):
        return [redact_params(item) for item in params]
    return params
