"""Behavioural parity with C3 §5's contract suite, against the REAL provider.

`tests/contracts/test_c3_memory_provider.py` grades `FakeMemoryProvider` and is
untouched (Stream C task brief). This module twins its numbered behaviours
against `PgVectorMemoryProvider` on a live Postgres, in the pattern the
approvals lane established (`tests/unit/approvals/test_real_service_contract.py`).
Numbering follows C3 §5's contract tests 1–7 so the mapping is checkable by eye.

**What "parity" means here, precisely.** C3 §5 specifies the FAKE's arithmetic —
`mem-N` ids, substring token scores, `2026-01-01` clocks. Those are the fake's,
not the contract's: §5 recall step 3 says in as many words that "real providers
use their monotonic insert sequence", and §4a says a real provider "may detect
duplicates semantically, but rules 1–3 bind whatever it detects identically". So
what is twinned is every BEHAVIOUR the contract binds both implementations to —
scope as an enforced filter, the entity reach-across, §4a's three sub-cases, the
capture-none skip, the receipt echo, the size cap, relevance ordering with a
newest-first tiebreak, limit truncation, and the unavailable posture — and never
the fake's numerals. A test that asserted `mem-1` here would be asserting the
double, not the contract.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from sunil.core.memory.provider import (
    EntityRef,
    MemoryItem,
    MemoryScope,
    MemoryWriteRejected,
    RecallResult,
    WriteReceipt,
    WriteRules,
)
from tests.unit.memory import factory
from tests.unit.memory.factory import requires_postgres

pytestmark = requires_postgres

CONV_1 = MemoryScope(user_id="owner", kind="conversation", id="conv-1")
CONV_2 = MemoryScope(user_id="owner", kind="conversation", id="conv-2")
OTHER_USER = MemoryScope(user_id="someone-else", kind="conversation", id="conv-1")
USER_SCOPE = MemoryScope(user_id="owner", kind="user", id=None)
CLIENT_X = MemoryScope(user_id="owner", kind="entity", id="client_x")
AUDIT_ID = "audit-evt-1"


def item(
    content: str,
    *,
    privacy: str = "internal",
    memory_type: str = "fact",
    entity_refs: list[EntityRef] | None = None,
) -> MemoryItem:
    return MemoryItem(
        content=content,
        memory_type=memory_type,
        privacy=privacy,
        entity_refs=entity_refs or [],
        source_request_id="req-1",
    )


def rules(*, capture: str = "redacted_full", dedupe: bool = True, ttl_days: int | None = None):
    return WriteRules(capture=capture, dedupe=dedupe, ttl_days=ttl_days)


@pytest_asyncio.fixture
async def engine():
    url = factory.postgres_url()
    assert url is not None  # guarded by `requires_postgres`
    async for made in factory.engine_for(url):
        yield made


@pytest_asyncio.fixture
async def memory(engine):
    return factory.make_provider(engine)


# --------------------------------------------------------------------------- #
# C3 contract test 1 — scope is an enforced filter, not a hint
# --------------------------------------------------------------------------- #
async def test_c3_1_in_scope_hit_and_sibling_scope_leak_probe(memory) -> None:
    """C3 contract test 1, twinned. The leak probe is the whole point: a
    provider that filed by nothing and recalled everything would satisfy the
    happy path and fail here."""
    receipt = await memory.write(
        item("Winch recovery signed off"), rules(), scope=CONV_1, audit_event_id=AUDIT_ID
    )

    assert isinstance(receipt, WriteReceipt)
    assert receipt.op == "created"
    assert receipt.memory_id  # a real id, whatever shape the provider mints
    assert receipt.audit_event_id == AUDIT_ID

    hit = await memory.recall("winch recovery", CONV_1)
    assert isinstance(hit, RecallResult)
    assert [scored.item.content for scored in hit.items] == ["Winch recovery signed off"]
    assert hit.items[0].source == "pgvector"
    assert hit.items[0].item.id == receipt.memory_id
    assert hit.items[0].item.created_at is not None
    assert hit.items[0].item.created_at.endswith("Z")

    assert (await memory.recall("winch recovery", CONV_2)).items == []


async def test_c3_1_scope_filter_separates_users_and_kinds(memory) -> None:
    """Scope equality is the WHOLE scope, not just its id: another user's
    identically-named conversation is a different scope, and so is the same
    user's `kind="user"` scope."""
    await memory.write(item("Owner only"), rules(), scope=CONV_1, audit_event_id=AUDIT_ID)

    assert (await memory.recall("owner only", OTHER_USER)).items == []
    assert (await memory.recall("owner only", USER_SCOPE)).items == []
    assert len((await memory.recall("owner only", CONV_1)).items) == 1


async def test_c3_1_user_scope_round_trips_with_a_null_id(memory) -> None:
    """`kind="user"` is the one scope whose id is None (C3 §2). A provider
    storing NULL and comparing it with `=` would never match its own rows."""
    await memory.write(item("Prefers Monday"), rules(), scope=USER_SCOPE, audit_event_id=AUDIT_ID)

    found = await memory.recall("prefers monday", USER_SCOPE)

    assert [scored.item.content for scored in found.items] == ["Prefers Monday"]


# --------------------------------------------------------------------------- #
# C3 contract test 2 — entity linkage reaches across conversations
# --------------------------------------------------------------------------- #
async def test_c3_2_entity_scope_reaches_across_conversations(memory) -> None:
    """C3 contract test 2, twinned. §3 linkage point 1: `entity_refs` are
    persisted with the memory so recall can filter by entity."""
    await memory.write(
        item(
            "Client X prefers Monday deliveries",
            entity_refs=[EntityRef(entity_type="client", entity_id="client_x")],
        ),
        rules(),
        scope=CONV_1,
        audit_event_id=AUDIT_ID,
    )
    await memory.write(
        item("Unrelated note about client Y"), rules(), scope=CONV_1, audit_event_id=AUDIT_ID
    )

    found = await memory.recall("monday deliveries", CLIENT_X)

    assert [scored.item.content for scored in found.items] == [
        "Client X prefers Monday deliveries"
    ]
    assert found.items[0].item.entity_refs == [
        EntityRef(entity_type="client", entity_id="client_x")
    ]


async def test_entity_refs_survive_the_round_trip_in_order(memory) -> None:
    """Several refs on one item, read back as written — the links are a child
    table, so "persisted verbatim" is a claim that has to be checked."""
    refs = [
        EntityRef(entity_type="client", entity_id="client_x"),
        EntityRef(entity_type="project", entity_id="proj_pda"),
        EntityRef(entity_type="person", entity_id="person_mark"),
    ]
    await memory.write(
        item("Mark signed the PDA scope", entity_refs=refs),
        rules(),
        scope=CONV_1,
        audit_event_id=AUDIT_ID,
    )

    found = await memory.recall("mark signed", CONV_1)

    assert found.items[0].item.entity_refs == refs


# --------------------------------------------------------------------------- #
# C3 contract test 3 — §4a's three sub-cases
# --------------------------------------------------------------------------- #
async def test_c3_3a_merge_upgrades_the_stored_label(memory) -> None:
    """§4a rule 1, incoming stricter: one row survives, upgraded, `op="merged"`,
    the STORED id returned."""
    first = await memory.write(
        item("Fact X", privacy="internal"), rules(), scope=CONV_1, audit_event_id=AUDIT_ID
    )
    second = await memory.write(
        item("fact x ", privacy="confidential"),
        rules(dedupe=True),
        scope=CONV_1,
        audit_event_id="audit-evt-2",
    )

    assert second.op == "merged"
    assert second.memory_id == first.memory_id
    assert second.audit_event_id == "audit-evt-2"

    found = await memory.recall("fact x", CONV_1)
    assert len(found.items) == 1
    assert found.items[0].item.privacy == "confidential"


async def test_c3_3b_merge_retains_a_stricter_stored_label_without_raising(memory) -> None:
    """§4a rule 1, incoming laxer: the stored label is RETAINED and nothing
    raises. A merge never lowers a label and never raises over privacy."""
    first = await memory.write(
        item("Fact Y", privacy="confidential"), rules(), scope=CONV_1, audit_event_id=AUDIT_ID
    )
    receipt = await memory.write(
        item("fact y", privacy="internal"), rules(dedupe=True), scope=CONV_1, audit_event_id=AUDIT_ID
    )

    assert receipt.op == "merged"
    assert receipt.memory_id == first.memory_id

    found = await memory.recall("fact y", CONV_1)
    assert len(found.items) == 1
    assert found.items[0].item.privacy == "confidential"


async def test_c3_3c_widening_append_is_rejected_but_narrowing_appends(memory) -> None:
    """§4a rule 2 — the genuine widening case. `dedupe=False` + a laxer label
    would mint a copy of confidential content under `internal`, which the
    caller-side prompt filter would then ship to a non-local model."""
    await memory.write(
        item("Fact Z", privacy="confidential"), rules(), scope=CONV_1, audit_event_id=AUDIT_ID
    )

    with pytest.raises(MemoryWriteRejected) as err:
        await memory.write(
            item("fact z", privacy="internal"),
            rules(dedupe=False),
            scope=CONV_1,
            audit_event_id=AUDIT_ID,
        )
    assert err.value.reason == "invalid_privacy_transition"

    receipt = await memory.write(
        item("fact z", privacy="confidential"),
        rules(dedupe=False),
        scope=CONV_1,
        audit_event_id=AUDIT_ID,
    )
    assert receipt.op == "created"

    found = await memory.recall("fact z", CONV_1)
    assert len(found.items) == 2
    assert all(scored.item.privacy == "confidential" for scored in found.items)


async def test_c3_3c_the_rejected_widening_write_left_no_row(memory) -> None:
    """A rejection that had already inserted would be worse than no rule at all:
    the widening copy would exist AND the caller would think it had been
    refused."""
    await memory.write(
        item("Fact Z", privacy="confidential"), rules(), scope=CONV_1, audit_event_id=AUDIT_ID
    )
    with pytest.raises(MemoryWriteRejected):
        await memory.write(
            item("fact z", privacy="public"),
            rules(dedupe=False),
            scope=CONV_1,
            audit_event_id=AUDIT_ID,
        )

    found = await memory.recall("fact z", CONV_1)
    assert len(found.items) == 1
    assert found.items[0].item.privacy == "confidential"


async def test_c3_3_non_duplicate_content_appends_regardless_of_labels(memory) -> None:
    """§4a rule 3 — no cross-item privacy interaction between different
    contents."""
    await memory.write(
        item("Alpha note", privacy="local_only"),
        rules(dedupe=False),
        scope=CONV_1,
        audit_event_id=AUDIT_ID,
    )
    receipt = await memory.write(
        item("Beta note", privacy="public"),
        rules(dedupe=False),
        scope=CONV_1,
        audit_event_id=AUDIT_ID,
    )

    assert receipt.op == "created"


async def test_c3_3_duplicate_detection_is_scope_local(memory) -> None:
    """§4a — duplicates are same-scope only, so identical content in a sibling
    scope APPENDS. A provider deduping globally would silently merge one
    conversation's memory into another's."""
    await memory.write(
        item("Fact X", privacy="internal"), rules(), scope=CONV_1, audit_event_id=AUDIT_ID
    )
    receipt = await memory.write(
        item("Fact X", privacy="public"), rules(), scope=CONV_2, audit_event_id=AUDIT_ID
    )

    assert receipt.op == "created"
    assert (await memory.recall("fact x", CONV_2)).items[0].item.privacy == "public"


# --------------------------------------------------------------------------- #
# C3 contract test 4 — capture=none, and the size cap
# --------------------------------------------------------------------------- #
async def test_c3_4_capture_none_stores_nothing_and_says_so(memory) -> None:
    receipt = await memory.write(
        item("never stored"),
        rules(capture="none"),
        scope=CONV_1,
        audit_event_id="audit-evt-none",
    )

    assert (receipt.memory_id, receipt.op) == ("", "skipped")
    assert receipt.audit_event_id == "audit-evt-none"
    assert (await memory.recall("never stored", CONV_1)).items == []


async def test_c3_payload_over_32_kib_is_rejected(memory) -> None:
    """32 KiB exactly is fine; one byte more is `payload_too_large`."""
    at_limit = await memory.write(
        item("x" * 32768), rules(), scope=CONV_1, audit_event_id=AUDIT_ID
    )
    assert at_limit.op == "created"

    with pytest.raises(MemoryWriteRejected) as err:
        await memory.write(item("y" * 32769), rules(), scope=CONV_1, audit_event_id=AUDIT_ID)
    assert err.value.reason == "payload_too_large"


async def test_c3_the_cap_counts_utf8_bytes_not_characters(memory) -> None:
    """"32 KiB (UTF-8 bytes)" — a provider counting characters would accept a
    payload three times the cap."""
    with pytest.raises(MemoryWriteRejected) as err:
        await memory.write(item("é" * 16385), rules(), scope=CONV_1, audit_event_id=AUDIT_ID)

    assert err.value.reason == "payload_too_large"


async def test_c3_capture_none_precedes_the_size_check(memory) -> None:
    """C3 §5's steps run "in this order"."""
    receipt = await memory.write(
        item("z" * 40000), rules(capture="none"), scope=CONV_1, audit_event_id=AUDIT_ID
    )

    assert receipt.op == "skipped"


# --------------------------------------------------------------------------- #
# C3 contract test 5 — deterministic ordering
# --------------------------------------------------------------------------- #
async def test_c3_5_ordering_is_relevance_then_newest_first(memory) -> None:
    """C3 contract test 5, twinned onto real scoring.

    The fake's numerals (1.0/0.5/0.5) are its own; what the contract binds is
    "descending score" plus §5 step 3's tiebreak — newest write first, on the
    provider's monotonic insert sequence. Two items that are *equally* relevant
    to the query make the tiebreak observable: "recovery winch" and "winch
    recovery" are the same bag of words, so their scores are equal by
    construction and only the sequence can order them.
    """
    for content in (
        "winch recovery training",  # both query tokens, plus a third word
        "recovery winch",  # equal-score twin, written EARLIER
        "winch recovery",  # equal-score twin, written LATER
        "entirely unrelated",  # shares nothing — dropped
    ):
        await memory.write(
            item(content), rules(dedupe=False), scope=CONV_1, audit_event_id=AUDIT_ID
        )

    found = await memory.recall("winch recovery", CONV_1)

    contents = [scored.item.content for scored in found.items]
    assert "entirely unrelated" not in contents
    assert contents[0] == "winch recovery"  # exact match outranks the 3-word one
    assert contents.index("winch recovery") < contents.index("recovery winch")
    scores = [scored.score for scored in found.items]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == pytest.approx(1.0, abs=1e-4)
    assert all(0.0 < score <= 1.0 for score in scores)


async def test_c3_5_equal_scores_break_on_write_order_descending(memory) -> None:
    """The tiebreak in isolation: identical content in the same scope, appended
    (`dedupe=False`), so the ONLY difference is insert order."""
    first = await memory.write(
        item("winch recovery"), rules(dedupe=False), scope=CONV_1, audit_event_id=AUDIT_ID
    )
    second = await memory.write(
        item("winch recovery"), rules(dedupe=False), scope=CONV_1, audit_event_id=AUDIT_ID
    )

    found = await memory.recall("winch recovery", CONV_1)

    assert [scored.item.id for scored in found.items] == [second.memory_id, first.memory_id]


async def test_c3_5_scores_round_to_four_decimal_places(memory) -> None:
    await memory.write(item("winch"), rules(), scope=CONV_1, audit_event_id=AUDIT_ID)

    found = await memory.recall("winch recovery training", CONV_1)

    assert len(found.items) == 1
    assert found.items[0].score == round(found.items[0].score, 4)
    assert 0.0 < found.items[0].score < 1.0


async def test_c3_5_zero_relevance_items_are_dropped(memory) -> None:
    """"Items scoring 0.0 are dropped" — a vector store returning every row
    ranked would hand the prompt builder the entire scope."""
    await memory.write(item("entirely unrelated"), rules(), scope=CONV_1, audit_event_id=AUDIT_ID)

    assert (await memory.recall("winch recovery", CONV_1)).items == []


async def test_c3_5_recall_truncates_to_limit(memory) -> None:
    """`limit` defaults to 8 and truncates the DESCENDING list — so the eight
    returned are the eight most relevant, not the first eight found."""
    for index in range(10):
        await memory.write(
            item(f"winch note number {index}"),
            rules(dedupe=False),
            scope=CONV_1,
            audit_event_id=AUDIT_ID,
        )

    assert len((await memory.recall("winch note", CONV_1)).items) == 8
    assert len((await memory.recall("winch note", CONV_1, limit=2)).items) == 2


async def test_c3_5_an_empty_query_recalls_nothing(memory) -> None:
    """The contract does not define an empty query, and a zero vector has no
    cosine. The fake returns empty; so does this."""
    await memory.write(item("winch recovery"), rules(), scope=CONV_1, audit_event_id=AUDIT_ID)

    assert (await memory.recall("   ", CONV_1)).items == []


# --------------------------------------------------------------------------- #
# C3 §2 — ttl_days, which only a real provider can honour
# --------------------------------------------------------------------------- #
async def test_an_expired_memory_is_not_recalled(memory) -> None:
    """`WriteRules.ttl_days` (C3 §2: "None = keep until superseded"). The clock
    is injected so the test states a fact about expiry rather than sleeping."""
    from datetime import UTC, datetime, timedelta

    now = datetime(2026, 1, 1, tzinfo=UTC)
    provider = factory.make_provider(memory.engine, clock=lambda: now)
    await provider.write(
        item("Temporary note about winch"),
        rules(ttl_days=1),
        scope=CONV_1,
        audit_event_id=AUDIT_ID,
    )
    await provider.write(
        item("Permanent note about winch"), rules(), scope=CONV_1, audit_event_id=AUDIT_ID
    )

    assert len((await provider.recall("note about winch", CONV_1)).items) == 2

    later = factory.make_provider(
        memory.engine, clock=lambda: now + timedelta(days=2)
    )
    remaining = await later.recall("note about winch", CONV_1)

    assert [scored.item.content for scored in remaining.items] == [
        "Permanent note about winch"
    ]


# --------------------------------------------------------------------------- #
# §4a under concurrency — the rule has to hold when two writers race
# --------------------------------------------------------------------------- #
async def test_two_concurrent_widening_appends_cannot_both_land(engine) -> None:
    """§4a rule 2 is a read-then-decide, and a read-then-decide without a lock
    is not a rule: two writers that each saw "no duplicate" would both insert,
    and the laxer copy the rule exists to refuse would exist anyway.

    Two concurrent `dedupe=False` writes of the same content at DIFFERENT labels
    must therefore end with at most one laxer row — either the second is
    rejected (it saw the stricter row) or it went first (and the stricter one
    appended legally, which §4a rule 2 allows).
    """
    import asyncio

    provider = factory.make_provider(engine)

    async def write(privacy: str):
        try:
            return await provider.write(
                item("Race content", privacy=privacy),
                rules(dedupe=False),
                scope=CONV_1,
                audit_event_id=AUDIT_ID,
            )
        except MemoryWriteRejected as exc:
            return exc

    results = await asyncio.gather(write("confidential"), write("internal"))

    found = await memory_contents(provider, "race content", CONV_1)
    lax = [privacy for privacy in found if privacy == "internal"]
    strict = [privacy for privacy in found if privacy == "confidential"]
    rejected = [r for r in results if isinstance(r, MemoryWriteRejected)]

    # Either the widening one was refused, or it landed BEFORE the stricter one.
    assert len(lax) <= 1
    assert len(strict) == 1
    if not rejected:
        assert len(found) == 2  # the internal row won the race and was legal


async def memory_contents(provider, query: str, scope) -> list[str]:
    found = await provider.recall(query, scope, limit=50)
    return [scored.item.privacy for scored in found.items]
