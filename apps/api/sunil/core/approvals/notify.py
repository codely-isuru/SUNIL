"""The ``approval.requested`` webhook — C4 §2 channel 2.

Contract facts implemented here:

* Sent **after the park transaction commits**, never inside it (C4 §2). A
  webhook that fired from inside the transaction could announce an approval that
  a rollback then un-minted.
* **Optional.** ``SUNIL_APPROVAL_NOTIFY_WEBHOOK_URL`` unset ⇒ no call at all,
  and parking still succeeds (ARCHITECTURE_V2 §5).
* **Fire-and-forget with 3 retries at 1 s / 5 s / 25 s.** Delivery failure never
  blocks parking — the dashboard queue is the source of truth (C4 §2), so the
  worst case of a dead webhook is a slower human, not a lost approval.
* **Redacted summary payload only** — the ``ApprovalRequestedEvent`` model. The
  payload is built from that model, so ``params_redacted`` cannot leak through
  this channel by a later edit: the shape has no field for it (C4 contract test
  6 is a redaction-by-shape probe, not a filter check).
* **ADR-033 URL rule**, enforced at construction: loopback, or one of the closed
  named-host set. The set is a frozen constant in code (ADR-033: "adding a host
  is a code change with review, never an env edit"), which is why it lives here
  and not in the config object.

The plain-text rule (C4 §4, Security review item 8) reaches the receiver too:
``summary`` is JSON string data, never markup, and this module never wraps it in
HTML. Any receiver template must treat it as text.
"""

from __future__ import annotations

import asyncio
import logging
from ipaddress import ip_address
from typing import Protocol
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

#: ADR-033's closed, literal named-host set (the Compose service names SUNIL
#: legitimately calls). ``openhands`` joins it in Phase V2-D via an ADR bump.
NAMED_HOSTS = frozenset({"litellm", "n8n"})

#: C4 §2's backoff schedule, in seconds, one entry per retry after the first try.
RETRY_DELAYS = (1.0, 5.0, 25.0)


class ApprovalNotifier(Protocol):
    """The seam the approvals service calls after a successful park."""

    async def notify_requested(self, payload: dict) -> None: ...


def is_loopback(host: str) -> bool:
    """ADR-017/033's loopback test. ``localhost`` is loopback by name; anything
    that parses as an address is judged by the address, so ``127.0.0.2`` and
    ``[::1]`` are in and ``10.0.0.5`` is out (ADR-033 rejected the whole
    RFC-1918 range on purpose: private ranges include the entire LAN)."""
    if host in {"localhost", ""}:
        return True
    try:
        return ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def validate_webhook_url(url: str) -> str:
    """ADR-033: ``host(url)`` is loopback ∨ ``host(url) ∈ NAMED_HOSTS``.

    Raises ``ValueError`` — the caller is ``Settings``/service construction, so
    a mis-set URL refuses to boot rather than timing out later (ADR-033's
    rejected-alternatives table makes that explicit)."""
    parts = urlsplit(url)
    if parts.scheme not in {"http", "https"}:
        raise ValueError(
            f"approval webhook URL must be http(s), got scheme {parts.scheme!r}"
        )
    host = parts.hostname or ""
    if is_loopback(host) or host in NAMED_HOSTS:
        return url
    raise ValueError(
        "approval webhook URL must be loopback or one of the named hosts "
        f"{sorted(NAMED_HOSTS)} (ADR-033); got host {host!r}"
    )


class NullNotifier:
    """The webhook-off case: ``SUNIL_APPROVAL_NOTIFY_WEBHOOK_URL`` unset.

    A no-op object rather than an ``if url:`` branch in the service, so the
    park path has exactly one shape and the "webhook off" case is exercised by
    the same code the "webhook on" case runs through."""

    async def notify_requested(self, payload: dict) -> None:
        return None


class WebhookNotifier:
    """POSTs ``approval.requested`` to a validated URL, fire and forget."""

    def __init__(
        self,
        url: str,
        *,
        client=None,
        retry_delays: tuple[float, ...] = RETRY_DELAYS,
        sleep=asyncio.sleep,
        audit=None,
    ) -> None:
        self.url = validate_webhook_url(url)
        self._client = client
        self._retry_delays = retry_delays
        self._sleep = sleep
        self._audit = audit

    async def notify_requested(self, payload: dict) -> None:
        """Deliver with retries; swallow every failure after auditing it.

        The method returns ``None`` on success AND on total failure by design —
        the caller (park) must not be able to fail because of this channel."""
        attempts = 1 + len(self._retry_delays)
        last_error: str | None = None
        for attempt in range(attempts):
            try:
                await self._post(payload)
                return
            except Exception as exc:  # noqa: BLE001 — never propagate (C4 §2)
                last_error = type(exc).__name__
                if attempt < len(self._retry_delays):
                    await self._sleep(self._retry_delays[attempt])
        # "failures logged + audited, never blocking" (C4 §2). The approval id
        # is logged; the summary is NOT, because it carries
        # attacker-influenceable text and a log line is a rendering surface too.
        logger.warning(
            "approval.requested webhook failed after %d attempts: %s",
            attempts,
            last_error,
        )
        if self._audit is not None:
            await self._audit.record(
                kind="approval_notify_failed",
                approval_id=payload.get("approval_id"),
                detail={"attempts": attempts, "error_kind": last_error},
            )

    async def _post(self, payload: dict) -> None:
        if self._client is not None:
            response = await self._client.post(self.url, json=payload)
        else:
            import httpx  # imported lazily: the webhook is optional

            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(self.url, json=payload)
        status = getattr(response, "status_code", 0)
        if not 200 <= status < 300:  # "any 2xx accepted" (C4 OpenAPI)
            raise RuntimeError(f"webhook returned {status}")


def notifier_for(url: str | None, **kwargs) -> ApprovalNotifier:
    """``NullNotifier`` when the URL is unset, a validated ``WebhookNotifier``
    otherwise. One place decides, so no caller has to remember the rule."""
    if not url:
        return NullNotifier()
    return WebhookNotifier(url, **kwargs)
