"""The ``approval.requested`` webhook — C4 §2 and ADR-033's URL rule.

Four contract properties get coverage here, each with a reason it matters:

* **URL validation at construction.** ADR-033: loopback ∨ ``{litellm, n8n}``,
  a frozen set in code. A mis-set URL must refuse to boot, not time out later
  (ADR-033's rejected-alternatives table says so explicitly) — and the URL is a
  capability, so a redirected webhook exfiltrates every approval summary to
  whoever owns the new host.
* **Redaction by shape.** The payload is built from
  ``ApprovalRequestedEvent``, which has no ``params_redacted`` field, so params
  cannot leak through this channel even by a careless later edit.
* **Retries 1 s / 5 s / 25 s, then give up quietly.** Delivery failure must
  never block parking — the dashboard queue is the source of truth (C4 §2), so
  a dead webhook costs a slower human, not a lost approval.
* **Never inside the park transaction.** Tested in ``test_park_notify.py``'s
  companion assertions below: a caller-owned park defers the send to
  :meth:`notify_parked`, which the caller runs after its commit. Announcing a
  row that a rollback then un-mints is the failure that ordering prevents.
"""

from __future__ import annotations

import pytest

from sunil.core.approvals.notify import (
    NAMED_HOSTS,
    RETRY_DELAYS,
    NullNotifier,
    WebhookNotifier,
    notifier_for,
    validate_webhook_url,
)

from tests.fakes.clock import FakeClock
from tests.unit.approvals import factory
from tests.unit.approvals.harness import RecordingNotifier
from tests.unit.approvals.test_real_service_contract import park_request


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


class ScriptedClient:
    """An httpx-shaped double: one scripted outcome per call."""

    def __init__(self, outcomes: list) -> None:
        self.outcomes = list(outcomes)
        self.posts: list[tuple[str, dict]] = []

    async def post(self, url: str, *, json: dict):
        self.posts.append((url, json))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


# --------------------------------------------------------------------------- #
# ADR-033 URL rule
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "url",
    [
        "http://localhost:5680/webhook/approvals",
        "http://127.0.0.1:9000/hook",
        "http://127.0.0.2:9000/hook",
        "http://[::1]:9000/hook",
        "http://n8n:5678/webhook/approvals",
        "https://litellm:4000/hook",
    ],
)
def test_loopback_and_named_hosts_are_accepted(url: str) -> None:
    """ADR-033: ``host(url)`` is loopback ∨ ``host(url) ∈ {litellm, n8n}``."""
    assert validate_webhook_url(url) == url


@pytest.mark.parametrize(
    "url",
    [
        "http://10.0.0.5/hook",  # RFC-1918 is the whole LAN — ADR-033 rejected it
        "http://192.168.1.20/hook",
        "http://evil.example.com/hook",
        "http://openhands:3000/hook",  # joins the set in V2-D, not before
        "ftp://localhost/hook",
        "file:///tmp/hook",
    ],
)
def test_everything_else_refuses_to_construct(url: str) -> None:
    """A bad URL raises at construction. The webhook URL is a capability: a
    private-range or public host would carry every approval summary off-box,
    and ADR-033 rejected "allow any RFC-1918 host" for exactly that reason."""
    with pytest.raises(ValueError):
        validate_webhook_url(url)


def test_the_named_host_set_is_closed_and_literal() -> None:
    """ADR-033: "a frozen constant in code, not configuration — adding a host is
    a code change with review, never an env edit". This test is the tripwire on
    that sentence: if the set grows, it grows in a reviewed diff that also
    updates ARCHITECTURE_V2 §5."""
    assert NAMED_HOSTS == frozenset({"litellm", "n8n"})


def test_unset_url_yields_a_no_op_notifier() -> None:
    """ARCHITECTURE_V2 §5: unset ⇒ webhook off, and parking still works."""
    assert isinstance(notifier_for(None), NullNotifier)
    assert isinstance(notifier_for(""), NullNotifier)
    assert isinstance(notifier_for("http://localhost:1/hook"), WebhookNotifier)


# --------------------------------------------------------------------------- #
# Delivery, retries, and never blocking
# --------------------------------------------------------------------------- #
async def test_a_2xx_is_one_post_and_no_retry() -> None:
    """C4 OpenAPI: "Receiver acknowledged (any 2xx accepted)"."""
    client = ScriptedClient([204])
    slept: list[float] = []

    async def sleep(delay: float) -> None:
        slept.append(delay)

    notifier = WebhookNotifier(
        "http://localhost:9000/hook", client=client, sleep=sleep
    )
    await notifier.notify_requested({"event": "approval.requested"})

    assert len(client.posts) == 1
    assert slept == []


async def test_failures_retry_three_times_on_the_contracts_backoff() -> None:
    """C4 §2: "3 retries (1 s/5 s/25 s backoff)" — four attempts in total."""
    client = ScriptedClient([500, RuntimeError("connreset"), 502, 200])
    slept: list[float] = []

    async def sleep(delay: float) -> None:
        slept.append(delay)

    notifier = WebhookNotifier(
        "http://localhost:9000/hook", client=client, sleep=sleep
    )
    await notifier.notify_requested({"event": "approval.requested"})

    assert len(client.posts) == 4
    assert slept == list(RETRY_DELAYS)


async def test_total_failure_is_swallowed_audited_and_never_raises() -> None:
    """C4 §2: "failures logged + audited, never blocking". The notifier returns
    ``None`` on total failure by design — a dead webhook must not be able to
    fail a park, because the dashboard queue is the source of truth."""
    client = ScriptedClient([500, 500, 500, 500])
    recorded: list[dict] = []

    class Audit:
        async def record(self, **kwargs) -> None:
            recorded.append(kwargs)

    notifier = WebhookNotifier(
        "http://localhost:9000/hook",
        client=client,
        sleep=_no_sleep,
        audit=Audit(),
    )

    assert await notifier.notify_requested({"approval_id": "apr-1"}) is None
    assert len(client.posts) == 4
    assert recorded and recorded[0]["kind"] == "approval_notify_failed"
    assert recorded[0]["detail"]["attempts"] == 4


async def _no_sleep(delay: float) -> None:
    return None


# --------------------------------------------------------------------------- #
# Ordering: the send happens after the park transaction commits
# --------------------------------------------------------------------------- #
async def test_park_sends_the_event_after_its_own_transaction() -> None:
    """The service-owned park commits, then notifies (C4 §2)."""
    engine = await factory.make_engine(factory.SQLITE_URL)
    try:
        notifier = RecordingNotifier()
        service = factory.make_service(
            engine, clock=FakeClock().now, notifier=notifier
        )
        parked = await service.park(park_request())

        assert [p["approval_id"] for p in notifier.sent] == [parked.approval_id]
        assert notifier.sent[0]["event"] == "approval.requested"
    finally:
        await engine.dispose()


async def test_a_caller_owned_park_defers_the_send_until_notify_parked() -> None:
    """C1 §2.1 step 4's park-path clause — the Tool Manager parks inside its own
    transaction, so the service cannot know when the commit happened and must
    not announce anything. The event is held and sent when the caller says so.

    The failure this prevents is concrete: a webhook fired mid-transaction
    announces an approval that a subsequent rollback un-mints, and the receiver
    (n8n) then notifies a human about a row the dashboard has never heard of.
    """
    engine = await factory.make_engine(factory.SQLITE_URL)
    try:
        notifier = RecordingNotifier()
        service = factory.make_service(
            engine, clock=FakeClock().now, notifier=notifier
        )

        async with engine.begin() as conn:
            parked = await service.park(park_request(), conn=conn)
            assert notifier.sent == []  # still inside the caller's transaction

        assert notifier.sent == []  # committed, but the caller has not asked yet
        await service.notify_parked(parked.approval_id)
        assert [p["approval_id"] for p in notifier.sent] == [parked.approval_id]

        # The row is really there, and its continuation was persisted with it.
        assert await service.continuation_for(parked.approval_id) is not None
        # A second notify is a no-op, so a retrying caller cannot double-send.
        await service.notify_parked(parked.approval_id)
        assert len(notifier.sent) == 1
    finally:
        await engine.dispose()
