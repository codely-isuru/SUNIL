"""The three approvals settings, as a constructor argument rather than an import.

``ARCHITECTURE_V2`` §5 names them and ``settings.py`` is the system's single env
seam — but ``settings.py`` belongs to the spine lane and does not exist in every
worktree. So the approvals service takes its configuration as a value object
(this module) and the spine builds one from ``Settings`` when it wires the
routes. Nothing here reads ``os.environ``: the M1 law ("``settings.py`` is the
single env seam") holds, and this service is testable without an environment.

| ARCHITECTURE_V2 §5 variable | field | default |
|---|---|---|
| ``SUNIL_APPROVAL_TTL_HOURS`` | ``ttl_hours`` | 72 |
| ``SUNIL_APPROVAL_CONSUME_GRACE_HOURS`` | ``consume_grace_hours`` | 1 (owner-ratified) |
| ``SUNIL_APPROVAL_NOTIFY_WEBHOOK_URL`` | ``notify_webhook_url`` | ``None`` (webhook off) |

There is deliberately **no** auto-approve / log-only / approvals-disabled field
(C4 §1, "No service-level bypass mode (structural)"). Adding one would put a
mode scalar over a mixed population in exactly the place the 2026-08-17 memory
lesson forbids; the only way an operation stops parking is its
``permissions.yaml`` grant, evaluated before this service is reached.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ApprovalsConfig:
    """Immutable so no request path can retune the TTL or the grace window."""

    ttl_hours: int = 72
    consume_grace_hours: int = 1
    notify_webhook_url: str | None = None

    def __post_init__(self) -> None:
        if self.ttl_hours <= 0:
            raise ValueError("ttl_hours must be positive")
        if self.consume_grace_hours <= 0:
            # A zero/negative grace makes every approved row instantly stale —
            # the consume CAS would never match and no approval could ever be
            # spent. Fail at construction, not at the first continuation.
            raise ValueError("consume_grace_hours must be positive")
