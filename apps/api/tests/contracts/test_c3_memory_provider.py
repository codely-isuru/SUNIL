"""C3 — Memory Provider contract suite.

Source of truth: ``docs/contracts/C3-memory-provider.md`` v1.0.0 (FROZEN
2026-09-10); §4a is the single normative dedupe/privacy rule and §5 is the fake
specification. The six numbered tests of C3 §5 are cited in the docstrings.

Open contract gap this suite is written around (finding F-1 in
``docs/tasks/P0-fakes.md``): ``MemoryProvider.write`` takes no scope, yet §2's
normative rules and §5's fake both store and filter items BY scope. The suite
uses the fake's ``write_in(scope, …)`` test helper, which sets the scope for one
write and then calls the frozen ``write(item, rules, *, audit_event_id)``
unchanged. The contract owner must decide how a real caller names a write's
scope before Stream C implements C3.
"""

from __future__ import annotations

from inspect import signature

import pytest

from sunil.core.memory.provider import (
    EntityRef,
    MemoryItem,
    MemoryProvider,
    MemoryScope,
    MemoryUnavailableError,
    MemoryWriteRejected,
    RecallResult,
    WriteReceipt,
    WriteRules,
)
from tests.fakes.fake_memory_provider import FakeMemoryProvider

pytestmark = pytest.mark.contract

CONV_1 = MemoryScope(user_id="owner", kind="conversation", id="conv-1")
CONV_2 = MemoryScope(user_id="owner", kind="conversation", id="conv-2")
CLIENT_X = MemoryScope(user_id="owner", kind="entity", id="client_x")
AUDIT_ID = "audit-evt-1"


def item(
    content: str,
    *,
    privacy: str = "internal",
    memory_type: str = "fact",
    entity_refs: list[EntityRef] | None = None,
) -> MemoryItem:
    """A MemoryItem with every required C3 §2 field populated. ``content`` is
    already-redacted text — the ADR-006 scrub happens BEFORE the seam."""
    return MemoryItem(
        content=content,
        memory_type=memory_type,
        privacy=privacy,
        entity_refs=entity_refs or [],
        source_request_id="req-1",
    )


def rules(*, capture: str = "redacted_full", dedupe: bool = True) -> WriteRules:
    """WriteRules with an explicit ``capture`` — C3 §2 gives it no default (an
    ADR-014 capture class is never implied)."""
    return WriteRules(capture=capture, dedupe=dedupe)


@pytest.fixture
def memory() -> FakeMemoryProvider:
    return FakeMemoryProvider()


# --------------------------------------------------------------------------- #
# C3 contract test 1
# --------------------------------------------------------------------------- #
async def test_c3_1_in_scope_hit_and_sibling_scope_leak_probe(
    memory: FakeMemoryProvider,
) -> None:
    """C3 contract test 1 — write then recall in-scope hits; recall from a sibling
    conversation scope misses (leak probe). C3 §2: scope is a filter the provider
    MUST enforce, not a hint."""
    receipt = await memory.write_in(
        CONV_1, item("Winch recovery signed off"), rules(), audit_event_id=AUDIT_ID
    )

    assert isinstance(receipt, WriteReceipt)
    assert (receipt.memory_id, receipt.op) == ("mem-1", "created")
    assert receipt.audit_event_id == AUDIT_ID

    hit = await memory.recall("winch", CONV_1)
    assert isinstance(hit, RecallResult)
    assert [scored.item.id for scored in hit.items] == ["mem-1"]
    assert hit.items[0].source == "fake"
    assert hit.items[0].item.created_at == "2026-01-01T00:00:00Z"

    miss = await memory.recall("winch", CONV_2)
    assert miss.items == []


# --------------------------------------------------------------------------- #
# C3 contract test 2
# --------------------------------------------------------------------------- #
async def test_c3_2_entity_scope_reaches_across_conversations(
    memory: FakeMemoryProvider,
) -> None:
    """C3 contract test 2 — entity-scoped recall finds an item written in a
    conversation scope but ref'd to the entity (§3 linkage point 1:
    ``entity_refs`` are persisted verbatim so recall can filter by entity without
    joining SUNIL tables)."""
    await memory.write_in(
        CONV_1,
        item(
            "Client X prefers Monday deliveries",
            entity_refs=[EntityRef(entity_type="client", entity_id="client_x")],
        ),
        rules(),
        audit_event_id=AUDIT_ID,
    )
    await memory.write_in(
        CONV_1,
        item("Unrelated note about client Y", entity_refs=[]),
        rules(),
        audit_event_id=AUDIT_ID,
    )

    found = await memory.recall("monday", CLIENT_X)

    assert [scored.item.id for scored in found.items] == ["mem-1"]


# --------------------------------------------------------------------------- #
# C3 contract test 3 — §4a, all three sub-cases
# --------------------------------------------------------------------------- #
async def test_c3_3a_merge_upgrades_the_stored_label(
    memory: FakeMemoryProvider,
) -> None:
    """C3 contract test 3(a) — write ``"Fact X"`` ``internal``, then ``"fact x "``
    ``confidential`` with ``dedupe=True`` → ``op="merged"``, same id, recall shows
    ``privacy="confidential"`` (stored row upgraded — stricter wins, §4a rule 1)."""
    first = await memory.write_in(
        CONV_1, item("Fact X", privacy="internal"), rules(), audit_event_id=AUDIT_ID
    )
    second = await memory.write_in(
        CONV_1,
        item("fact x ", privacy="confidential"),
        rules(dedupe=True),
        audit_event_id="audit-evt-2",
    )

    assert second.op == "merged"
    assert second.memory_id == first.memory_id == "mem-1"
    assert second.audit_event_id == "audit-evt-2"

    found = await memory.recall("fact", CONV_1)
    assert len(found.items) == 1
    assert found.items[0].item.privacy == "confidential"


async def test_c3_3b_merge_retains_a_stricter_stored_label_without_raising(
    memory: FakeMemoryProvider,
) -> None:
    """C3 contract test 3(b) — write ``"Fact Y"`` ``confidential``, then
    ``"fact y"`` ``internal`` with ``dedupe=True`` → ``op="merged"``, recall still
    shows ``"confidential"`` (stored stricter retained, NO exception: §4a rule 1
    never raises over privacy and never lowers a label)."""
    await memory.write_in(
        CONV_1, item("Fact Y", privacy="confidential"), rules(), audit_event_id=AUDIT_ID
    )
    receipt = await memory.write_in(
        CONV_1,
        item("fact y", privacy="internal"),
        rules(dedupe=True),
        audit_event_id=AUDIT_ID,
    )

    assert receipt.op == "merged"
    assert receipt.memory_id == "mem-1"

    found = await memory.recall("fact", CONV_1)
    assert len(found.items) == 1
    assert found.items[0].item.privacy == "confidential"


async def test_c3_3c_widening_append_is_rejected_but_narrowing_appends(
    memory: FakeMemoryProvider,
) -> None:
    """C3 contract test 3(c) — write ``"Fact Z"`` ``confidential``, then
    ``"fact z"`` ``internal`` with ``dedupe=False`` → raises
    ``MemoryWriteRejected(reason="invalid_privacy_transition")``; the same append
    with ``privacy="confidential"`` → ``op="created"``, two rows (§4a rule 2 — the
    genuine widening case)."""
    await memory.write_in(
        CONV_1, item("Fact Z", privacy="confidential"), rules(), audit_event_id=AUDIT_ID
    )

    with pytest.raises(MemoryWriteRejected) as err:
        await memory.write_in(
            CONV_1,
            item("fact z", privacy="internal"),
            rules(dedupe=False),
            audit_event_id=AUDIT_ID,
        )
    assert err.value.reason == "invalid_privacy_transition"

    receipt = await memory.write_in(
        CONV_1,
        item("fact z", privacy="confidential"),
        rules(dedupe=False),
        audit_event_id=AUDIT_ID,
    )
    assert (receipt.op, receipt.memory_id) == ("created", "mem-2")

    found = await memory.recall("fact", CONV_1)
    assert [scored.item.id for scored in found.items] == ["mem-2", "mem-1"]


async def test_c3_3_non_duplicate_content_appends_regardless_of_labels(
    memory: FakeMemoryProvider,
) -> None:
    """C3 §4a rule 3 — non-duplicate content appends regardless of labels; no
    cross-item privacy interaction."""
    await memory.write_in(
        CONV_1,
        item("Alpha", privacy="local_only"),
        rules(dedupe=False),
        audit_event_id=AUDIT_ID,
    )
    receipt = await memory.write_in(
        CONV_1,
        item("Beta", privacy="public"),
        rules(dedupe=False),
        audit_event_id=AUDIT_ID,
    )

    assert (receipt.op, receipt.memory_id) == ("created", "mem-2")


async def test_c3_3_duplicate_detection_is_scope_local(
    memory: FakeMemoryProvider,
) -> None:
    """C3 §4a — two items are duplicates only when they are in the SAME scope, so
    identical content in a sibling scope appends rather than merging."""
    await memory.write_in(
        CONV_1, item("Fact X", privacy="internal"), rules(), audit_event_id=AUDIT_ID
    )
    receipt = await memory.write_in(
        CONV_2, item("Fact X", privacy="public"), rules(), audit_event_id=AUDIT_ID
    )

    assert (receipt.op, receipt.memory_id) == ("created", "mem-2")


# --------------------------------------------------------------------------- #
# C3 contract test 4
# --------------------------------------------------------------------------- #
async def test_c3_4_capture_none_stores_nothing_and_says_so(
    memory: FakeMemoryProvider,
) -> None:
    """C3 contract test 4 — ``capture="none"`` stores nothing and says so; the
    receipt echoes the passed ``audit_event_id`` (§5 step 1)."""
    receipt = await memory.write_in(
        CONV_1,
        item("never stored"),
        rules(capture="none"),
        audit_event_id="audit-evt-none",
    )

    assert (receipt.memory_id, receipt.op) == ("", "skipped")
    assert receipt.audit_event_id == "audit-evt-none"
    assert memory.items == []

    found = await memory.recall("never", CONV_1)
    assert found.items == []


async def test_c3_payload_over_32_kib_is_rejected(memory: FakeMemoryProvider) -> None:
    """C3 §4/§5 step 2 — content over 32 KiB (UTF-8 bytes) raises
    ``MemoryWriteRejected(reason="payload_too_large")``; 32 KiB exactly is fine."""
    at_limit = await memory.write_in(
        CONV_1, item("x" * 32768), rules(), audit_event_id=AUDIT_ID
    )
    assert at_limit.op == "created"

    with pytest.raises(MemoryWriteRejected) as err:
        await memory.write_in(
            CONV_1, item("y" * 32769), rules(), audit_event_id=AUDIT_ID
        )
    assert err.value.reason == "payload_too_large"


async def test_c3_capture_none_precedes_the_size_check(
    memory: FakeMemoryProvider,
) -> None:
    """C3 §5 — the write steps run "in this order", so an oversized payload with
    ``capture="none"`` is skipped, not rejected."""
    receipt = await memory.write_in(
        CONV_1, item("z" * 40000), rules(capture="none"), audit_event_id=AUDIT_ID
    )

    assert receipt.op == "skipped"


# --------------------------------------------------------------------------- #
# C3 contract test 5
# --------------------------------------------------------------------------- #
async def test_c3_5_recall_ordering_is_deterministic(
    memory: FakeMemoryProvider,
) -> None:
    """C3 contract test 5 — deterministic ordering: three seeded items, one query,
    exact expected id order asserted — including two items with EQUAL scores,
    asserting newest-write-first between them (§5 recall step 3: score desc, then
    write order desc, keyed on the integer suffix of ``mem-N``)."""
    for content in (
        "winch recovery training",  # mem-1 — both query tokens → 1.0
        "winch only",  # mem-2 — one token → 0.5
        "recovery only",  # mem-3 — one token → 0.5
        "entirely unrelated",  # mem-4 — 0.0, dropped
    ):
        await memory.write_in(
            CONV_1, item(content), rules(dedupe=False), audit_event_id=AUDIT_ID
        )

    found = await memory.recall("winch recovery", CONV_1)

    assert [scored.item.id for scored in found.items] == ["mem-1", "mem-3", "mem-2"]
    assert [scored.score for scored in found.items] == [1.0, 0.5, 0.5]
    assert all(scored.source == "fake" for scored in found.items)


async def test_c3_5_scores_round_to_four_decimal_places(
    memory: FakeMemoryProvider,
) -> None:
    """C3 §5 recall step 2 — ``score`` is rounded to 4 decimal places, and items
    scoring ``0.0`` are dropped."""
    await memory.write_in(CONV_1, item("winch"), rules(), audit_event_id=AUDIT_ID)

    found = await memory.recall("winch recovery training", CONV_1)

    assert [scored.score for scored in found.items] == [0.3333]


async def test_c3_5_recall_truncates_to_limit(memory: FakeMemoryProvider) -> None:
    """C3 §2/§5 — ``limit`` defaults to 8 and truncates the descending list."""
    for index in range(10):
        await memory.write_in(
            CONV_1,
            item(f"winch note {index}"),
            rules(dedupe=False),
            audit_event_id=AUDIT_ID,
        )

    default_limit = await memory.recall("winch", CONV_1)
    explicit = await memory.recall("winch", CONV_1, limit=2)

    assert len(default_limit.items) == 8
    assert [scored.item.id for scored in explicit.items] == ["mem-10", "mem-9"]


async def test_c3_5_tokenisation_is_lowercased_substring_matching(
    memory: FakeMemoryProvider,
) -> None:
    """C3 §5 recall step 2 — the query is tokenised on whitespace and lowercased;
    a token counts when found as a SUBSTRING of the lowercased content."""
    await memory.write_in(
        CONV_1, item("Winches Recovered"), rules(), audit_event_id=AUDIT_ID
    )

    found = await memory.recall("WINCH   recover", CONV_1)

    assert [scored.score for scored in found.items] == [1.0]


# --------------------------------------------------------------------------- #
# C3 contract test 6
# --------------------------------------------------------------------------- #
async def test_c3_6_unavailable_provider_raises_on_every_call() -> None:
    """C3 contract test 6, provider half — ``unavailable=True`` → every call
    raises ``MemoryUnavailableError`` (§5 constructor flag). The write failure
    surfacing is the contract (§4: a lost write must be visible)."""
    memory = FakeMemoryProvider(unavailable=True)

    with pytest.raises(MemoryUnavailableError):
        await memory.recall("anything", CONV_1)

    with pytest.raises(MemoryUnavailableError):
        await memory.write_in(CONV_1, item("anything"), rules(), audit_event_id=AUDIT_ID)


@pytest.mark.skip(
    reason="C3 contract test 6, service half — 'recall degrades to empty via the "
    "SERVICE' needs core/memory/service.py (Phase 2, Stream C: audit-outside-vendor "
    "+ the §2 latency-budget degrade to memory_retrieved {degraded: true}). The "
    "provider-side raise is asserted above; the degrade is debt."
)
def test_c3_6_service_degrades_recall_and_surfaces_write_failure() -> None:
    """C3 contract test 6 — memory being down degrades a turn; it never fails one."""


# --------------------------------------------------------------------------- #
# C3 §2 — the frozen signature and the audit-linkage parameter
# --------------------------------------------------------------------------- #
def test_c3_write_signature_is_the_frozen_one() -> None:
    """C3 §2 — ``write(item, rules, *, audit_event_id)``: ``audit_event_id`` is
    keyword-only so a vendor adapter cannot positionally confuse it with anything
    else, and a provider cannot be called without receiving the linkage id
    ("vendor library skipped auditing" stays inexpressible).

    The scope gap (finding F-1) is visible here: no parameter names the scope a
    write files into, although §2/§5 require the provider to enforce scope.
    """
    write = signature(MemoryProvider.write)
    recall = signature(MemoryProvider.recall)

    assert list(write.parameters) == ["self", "item", "rules", "audit_event_id"]
    assert write.parameters["audit_event_id"].kind.name == "KEYWORD_ONLY"
    assert write.parameters["audit_event_id"].default is write.empty
    assert list(recall.parameters) == ["self", "query", "scope", "limit"]
    assert recall.parameters["limit"].default == 8
    # F-1, asserted so the gap cannot drift silently into an implementation:
    assert "scope" not in write.parameters


def test_c3_memory_item_privacy_is_required_with_no_default() -> None:
    """C3 §2 — ``MemoryItem.privacy`` is REQUIRED, no default (§26.9). A state
    field whose creation path may omit it reads as its default (memory lesson
    2026-08-17), which is exactly what must not happen to a privacy label."""
    assert MemoryItem.model_fields["privacy"].is_required()
    assert MemoryItem.model_fields["memory_type"].is_required()
    assert MemoryItem.model_fields["source_request_id"].is_required()
    assert MemoryItem.model_fields["id"].default is None


def test_c3_write_rules_requires_an_explicit_capture_class() -> None:
    """C3 §2 — ``WriteRules``: ``capture`` is required (ADR-014 kinds, never
    implied); ``dedupe`` defaults True and ``ttl_days`` None (keep until
    superseded)."""
    built = rules()

    assert built.dedupe is True
    assert built.ttl_days is None
    assert WriteRules.model_fields["capture"].is_required()
    with pytest.raises(Exception):
        WriteRules()
