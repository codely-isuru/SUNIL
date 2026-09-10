"""``FakeMemoryProvider`` — C3 §5's fake specification, verbatim.

Source of truth: ``docs/contracts/C3-memory-provider.md`` §5 with §4a's
duplicate/privacy rule applied verbatim (**v1.1.0**, FROZEN 2026-09-10).
``name="fake"``. In-memory, deterministic, no I/O.

Scope comes from the call (v1.1.0): ``write(item, rules, *, scope,
audit_event_id)`` files its item under the ``scope`` argument, which is also what
``_find_duplicate`` compares ("the SAME scope", §4a) and what ``recall``
filters on. The interim ``current_scope``/``write_in`` machinery of the
fakes-build round — which existed only because v1.0.0's ``write`` named no scope
(finding F-1) — is deleted: scope is no longer state on this object, so nothing
here can file a write anywhere other than where its caller said.
"""

from __future__ import annotations

from datetime import timedelta

from sunil.core.memory.provider import (
    PRIVACY_STRICTNESS,
    MemoryItem,
    MemoryScope,
    MemoryUnavailableError,
    MemoryWriteRejected,
    RecallResult,
    ScoredMemory,
    WriteReceipt,
    WriteRules,
)

from tests.fakes.clock import DEFAULT_START, from_iso, to_iso

#: C3 §4 — content over 32 KiB (UTF-8 bytes) is rejected.
MAX_CONTENT_BYTES = 32768


def _write_order(memory_id: str) -> int:
    """C3 §5 recall step 3 — the integer suffix of ``mem-N``, numerically.

    Never lexicographic: the contract calls this out explicitly, because text
    comparison puts ``mem-10`` before ``mem-2``.
    """
    return int(memory_id.rsplit("-", 1)[1])


class FakeMemoryProvider:
    """C3 §5 fake. ``unavailable=True`` → every call raises
    ``MemoryUnavailableError`` (tests assert the SERVICE degrades recall and
    surfaces write failure).

    Structural conformance to ``MemoryProvider`` only — the Protocol is
    deliberately NOT a base class (backend review F2: an explicitly-inherited
    Protocol turns every method the fake forgets into an inherited ``...`` stub
    that returns ``None``, which a contract test can pass against vacuously).
    ``_check`` at the bottom of this module is the static conformance assertion;
    ``tests/contracts/test_fake_conformance.py`` is the runtime one.
    """

    def __init__(self, unavailable: bool = False) -> None:
        self.name = "fake"
        self.unavailable = unavailable
        self.items: list[tuple[MemoryScope, MemoryItem]] = []

    # -- C3 §2 protocol ---------------------------------------------------- #
    async def write(
        self,
        item: MemoryItem,
        rules: WriteRules,
        *,
        scope: MemoryScope,
        audit_event_id: str,
    ) -> WriteReceipt:
        """C3 §5's exact behaviour, in this order: capture-none skip → size
        rejection → §4a duplicate/privacy resolution → append. The item is filed
        under the ``scope`` argument (v1.1.0) and every receipt echoes the
        ``audit_event_id`` parameter."""
        if self.unavailable:
            raise MemoryUnavailableError("fake memory provider is unavailable")

        # 1. capture == "none" → skipped, store nothing.
        if rules.capture == "none":
            return WriteReceipt(
                memory_id="", op="skipped", audit_event_id=audit_event_id
            )

        # 2. payload cap.
        if len(item.content.encode()) > MAX_CONTENT_BYTES:
            raise MemoryWriteRejected("payload_too_large")

        # 3. §4a — duplicate detection + privacy resolution, within this scope.
        duplicate = self._find_duplicate(scope, item.content)
        if duplicate is not None:
            stored = duplicate
            if rules.dedupe:
                # Rule 1 (merge): exactly one row survives — the stored one, whose
                # privacy becomes the stricter of the two. Never raises, never
                # lowers a label.
                if (
                    PRIVACY_STRICTNESS[item.privacy]
                    > PRIVACY_STRICTNESS[stored.privacy]
                ):
                    stored.privacy = item.privacy
                assert stored.id is not None
                return WriteReceipt(
                    memory_id=stored.id, op="merged", audit_event_id=audit_event_id
                )
            # Rule 2 (append): a laxer incoming label would mint a widening copy.
            if PRIVACY_STRICTNESS[item.privacy] < PRIVACY_STRICTNESS[stored.privacy]:
                raise MemoryWriteRejected("invalid_privacy_transition")

        # 4. append (rule 2's stricter-or-equal case, and rule 3's non-duplicate).
        return self._append(scope, item, audit_event_id)

    async def recall(
        self, query: str, scope: MemoryScope, *, limit: int = 8
    ) -> RecallResult:
        """C3 §5's exact scoring, fully deterministic (candidates → substring
        token score rounded to 4 dp, zeros dropped → score desc, write order desc
        → truncate to ``limit``)."""
        if self.unavailable:
            raise MemoryUnavailableError("fake memory provider is unavailable")

        tokens = [token.lower() for token in query.split()]
        if not tokens:
            # The contract does not define an empty query; scoring it would be a
            # division by zero. Empty result, recorded as a finding.
            return RecallResult(items=[])

        scored: list[ScoredMemory] = []
        for candidate in self._candidates(scope):
            content = candidate.content.lower()
            matched = sum(1 for token in tokens if token in content)
            score = round(matched / len(tokens), 4)
            if score == 0.0:
                continue
            scored.append(ScoredMemory(item=candidate, score=score, source="fake"))

        scored.sort(
            key=lambda entry: (entry.score, _write_order(entry.item.id or "mem-0")),
            reverse=True,
        )
        return RecallResult(items=scored[:limit])

    # -- internals ---------------------------------------------------------- #
    def _append(
        self, scope: MemoryScope, item: MemoryItem, audit_event_id: str
    ) -> WriteReceipt:
        write_index = len(self.items)
        stored = item.model_copy(
            update={
                "id": f"mem-{write_index + 1}",
                "created_at": to_iso(
                    from_iso(DEFAULT_START) + timedelta(seconds=write_index)
                ),
            }
        )
        self.items.append((scope, stored))
        assert stored.id is not None
        return WriteReceipt(
            memory_id=stored.id, op="created", audit_event_id=audit_event_id
        )

    def _find_duplicate(self, scope: MemoryScope, content: str) -> MemoryItem | None:
        """C3 §4a — duplicates are items written under the SAME scope whose
        ``content.strip()`` compare equal case-insensitively."""
        needle = content.strip().casefold()
        for stored_scope, stored in self.items:
            if stored_scope == scope and stored.content.strip().casefold() == needle:
                return stored
        return None

    def _candidates(self, scope: MemoryScope) -> list[MemoryItem]:
        """C3 §5 recall step 1 — items whose stored scope equals ``scope``
        exactly, PLUS (when ``scope.kind == "entity"``) items of any scope
        carrying an ``EntityRef`` with that ``entity_id``."""
        candidates: list[MemoryItem] = []
        for stored_scope, stored in self.items:
            if stored_scope == scope:
                candidates.append(stored)
            elif scope.kind == "entity" and any(
                ref.entity_id == scope.id for ref in stored.entity_refs
            ):
                candidates.append(stored)
        return candidates
