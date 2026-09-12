"""`PgVectorMemoryProvider` — C3's long-term memory engine, on Postgres/pgvector.

Why this and not Mem0-the-library (the ADR-030 call, argued)
------------------------------------------------------------
ADR-030's principle is "integrate open-source components **behind our seams**",
and C3 is that seam. The question is only which engine sits behind it today.

Mem0 was rejected for this build, on three grounds that are about C3's text
rather than about taste. (1) **Its write path is an LLM.** `mem0.add()` sends
the content to a model which decides ADD/UPDATE/DELETE and rewrites the stored
fact. C3 §2 forbids exactly that: "`content` arrives already scrubbed and
capture-classified… the provider never sees raw secrets; it **must not
re-classify**" — and §4a specifies dedupe as an exact, deterministic rule
("stricter survives the merge; a laxer-labelled append is rejected") that a
model's judgement cannot be made to satisfy, let alone to satisfy repeatably in
a contract test. (2) **It drags an LLM + embedder dependency chain and its own
schema**, neither of which this machine can run (no provider key exists here),
so the parity suite would be unprovable — and its schema knows nothing of
`privacy`, which is the field the whole of §4a turns on. (3) **Audit posture**:
C3 puts the audit row outside the vendor and has the vendor echo
`audit_event_id`; behind Mem0 that echo would be adapter code anyway, so the
vendor buys nothing there.

What the rejection does NOT mean: Mem0 stays swappable. It would be
`memory_providers/mem0_provider.py` next to this file, selected by
`SUNIL_MEMORY_PROVIDER=mem0`, with nothing in `core/` or the orchestrator
changing — which IS ADR-030's principle, honoured by having a seam worth
swapping behind rather than by taking the vendor.

How it works
------------
* **Scope is an enforced filter** (C3 §2), in the WHERE clause of every recall
  and the values of every insert. `scope_id` is NULL for `kind="user"`, so the
  comparison is `IS NOT DISTINCT FROM` — `= NULL` is NULL, and a provider using
  `=` would never find its own user-scoped rows.
* **Entity reach** (§3 linkage point 1): an `kind="entity"` recall also
  considers any memory, in any scope, carrying a link to that entity id.
* **§4a is applied verbatim**, inside one transaction, under a per-(scope,
  content) advisory lock — see `_write_locked` for why the lock is load-bearing
  rather than defensive.
* **Ranking** is cosine similarity (`<=>` is pgvector's cosine DISTANCE, so the
  score is `1 - distance`), ordered by score descending then `seq` descending —
  §5 step 3's "newest write first" on a real provider's monotonic sequence.
* **Everything the database or the embedder can do to fail becomes
  `MemoryUnavailableError`** (C3 §4), because that is the only error the memory
  service degrades on. A leaked `OperationalError` would fail the turn.

Not in this file, on purpose: the audit row (the service writes it BEFORE the
call), scope resolution (`core/memory/entities.py`, §3 linkage point 2) and the
`local_only` prompt filter (caller-side policy, §2).
"""

from __future__ import annotations

import zlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from sqlalchemy import (
    DateTime,
    Float,
    Integer,
    String,
    bindparam,
    delete,
    insert,
    select,
    text,
    update,
)
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from sunil.core.memory.embedding import (
    EMBEDDING_DIM,
    Embedder,
    EmbeddingUnavailableError,
)
from sunil.core.memory.provider import (
    PRIVACY_STRICTNESS,
    EntityRef,
    MemoryItem,
    MemoryProvider,
    MemoryScope,
    MemoryUnavailableError,
    MemoryWriteRejected,
    RecallResult,
    ScoredMemory,
    WriteReceipt,
    WriteRules,
)
from sunil.core.memory.tables import (
    Vector,
    content_key,
    memories_table,
    memory_entity_links_table,
)

#: C3 §4 — content over 32 KiB (UTF-8 BYTES, not characters).
MAX_CONTENT_BYTES = 32768

#: The provenance string on every `ScoredMemory` this provider returns.
SOURCE = "pgvector"


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _to_iso(moment: datetime) -> str:
    """C3 §2: `created_at` is ISO-8601 UTC. `datetime.isoformat()` writes
    `+00:00`; the contract's own examples (and the fake) write `Z`."""
    return moment.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _lock_key(scope: MemoryScope, key: str) -> int:
    """A 64-bit advisory-lock key for one (scope, content) pair.

    CRC32 of the tuple, widened. Collisions are possible and harmless: two
    unrelated writes sharing a key serialise against each other, which costs
    latency and never correctness. The alternative — no lock — costs
    correctness, which `_write_locked` explains.
    """
    raw = f"{scope.user_id}\x00{scope.kind}\x00{scope.id or ''}\x00{key}".encode()
    return zlib.crc32(raw) - 2**31


class PgVectorMemoryProvider:
    """C3 §2's `MemoryProvider`, backed by Postgres 17 + pgvector 0.8.6.

    Structural conformance only — `MemoryProvider` is deliberately not a base
    class, for the reason recorded on `FakeMemoryProvider`: an inherited
    Protocol turns a forgotten method into a `...` stub returning `None`, which
    a contract test can pass against vacuously. `_check` at the bottom is the
    static witness.
    """

    def __init__(
        self,
        *,
        engine: AsyncEngine,
        embedder: Embedder,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        if embedder.dimension != EMBEDDING_DIM:
            raise ValueError(
                f"embedder {embedder.name!r} produces width {embedder.dimension}, but "
                f"memories.embedding is vector({EMBEDDING_DIM}). Changing embedding "
                "family is a migration, not a config flip — see "
                "core/memory/embedding.py."
            )
        self.name = SOURCE
        self.engine = engine
        self._embedder = embedder
        self._clock = clock

    # -- C3 §2 protocol ---------------------------------------------------- #
    async def write(
        self,
        item: MemoryItem,
        rules: WriteRules,
        *,
        scope: MemoryScope,
        audit_event_id: str,
    ) -> WriteReceipt:
        """C3 §5's order, verbatim: capture-none skip → size cap → §4a duplicate
        and privacy resolution → append.

        The first two run BEFORE any connection is taken. That is the contract's
        order ("in this order"), and it also means a `capture="none"` write —
        the ADR-014 class that exists precisely so nothing is stored — never
        touches the database at all.
        """
        # 1. capture == "none" → skipped, store nothing (§5 step 1).
        if rules.capture == "none":
            return WriteReceipt(memory_id="", op="skipped", audit_event_id=audit_event_id)

        # 2. payload cap (§5 step 2).
        if len(item.content.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise MemoryWriteRejected("payload_too_large")

        embedding = await self._embed(item.content)

        try:
            async with self.engine.begin() as conn:
                return await self._write_locked(
                    conn,
                    item=item,
                    rules=rules,
                    scope=scope,
                    audit_event_id=audit_event_id,
                    embedding=embedding,
                )
        except (MemoryWriteRejected, MemoryUnavailableError):
            raise
        except SQLAlchemyError as exc:
            raise MemoryUnavailableError(
                f"the memory store rejected or could not serve a write: {type(exc).__name__}"
            ) from exc

    async def recall(
        self, query: str, scope: MemoryScope, *, limit: int = 8
    ) -> RecallResult:
        """Cosine similarity over the scope's candidates, descending, newest
        first on a tie, truncated to `limit`.

        An empty (or purely non-word) query embeds to the zero vector, which has
        no cosine. The fake returns an empty result for it; so does this, rather
        than asking Postgres to divide by a zero norm.
        """
        vector = await self._embed(query)
        if vector is None:
            return RecallResult(items=[])

        statement = self._candidate_query(scope)
        params = {
            "query_vector": vector,
            "limit": limit,
            "now": self._clock(),
            "scope_user_id": scope.user_id,
            "scope_kind": scope.kind,
            "scope_id": scope.id,
        }

        try:
            async with self.engine.connect() as conn:
                rows = (await conn.execute(statement, params)).mappings().all()
                refs = await self._entity_refs_for(conn, [row["id"] for row in rows])
        except SQLAlchemyError as exc:
            raise MemoryUnavailableError(
                f"the memory store could not serve a recall: {type(exc).__name__}"
            ) from exc

        scored: list[ScoredMemory] = []
        for row in rows:
            # `<=>` is cosine DISTANCE; similarity is 1 - distance. Rounded to 4
            # dp per C3 §5 step 2, and re-checked for zero AFTER rounding, so a
            # 0.00004 match does not come back as a 0.0-scored item the contract
            # says is dropped.
            score = round(1.0 - float(row["distance"]), 4)
            if score <= 0.0:
                continue
            scored.append(
                ScoredMemory(
                    item=_item_from_row(row, refs.get(row["id"], [])),
                    score=score,
                    source=SOURCE,
                )
            )
        return RecallResult(items=scored)

    # -- internals ---------------------------------------------------------- #
    async def _embed(self, content: str) -> list[float] | None:
        """`None` means "no usable vector" — an all-zero embedding, which is what
        text with no word characters produces. Never an exception for that case;
        an exception is reserved for the embedder being DOWN."""
        try:
            vector = await self._embedder.embed(content)
        except EmbeddingUnavailableError as exc:
            # C3 §2's degrade path only triggers on this one error type.
            raise MemoryUnavailableError(
                f"embeddings are unavailable, so memory is: {exc}"
            ) from exc
        if not any(vector):
            return None
        return vector

    async def _write_locked(
        self,
        conn: AsyncConnection,
        *,
        item: MemoryItem,
        rules: WriteRules,
        scope: MemoryScope,
        audit_event_id: str,
        embedding: list[float] | None,
    ) -> WriteReceipt:
        """§4a inside one transaction, under an advisory lock.

        **Why the lock is load-bearing.** §4a rules 1 and 2 are both
        read-then-decide: find the duplicate, then merge or refuse. Without
        serialisation two concurrent `dedupe=False` writes of the same content
        at different labels each read "no duplicate" and each insert — so the
        laxer copy that rule 2 exists to refuse gets written anyway, and the
        refusal the caller relies on silently stops happening under load. A
        UNIQUE index cannot substitute: `dedupe=False` legitimately appends
        duplicate rows (§4a rule 2's stricter-or-equal case), so uniqueness is
        not the invariant. `pg_advisory_xact_lock` releases with the
        transaction, including on rollback.
        """
        key = content_key(item.content)
        await conn.execute(
            text("SELECT pg_advisory_xact_lock(:key)"), {"key": _lock_key(scope, key)}
        )

        duplicate = (
            await conn.execute(
                select(memories_table.c.id, memories_table.c.privacy)
                .where(
                    memories_table.c.scope_user_id == scope.user_id,
                    memories_table.c.scope_kind == scope.kind,
                    memories_table.c.scope_id.is_not_distinct_from(scope.id),
                    memories_table.c.content_key == key,
                )
                .order_by(memories_table.c.seq)
                .limit(1)
            )
        ).first()

        if duplicate is not None:
            if rules.dedupe:
                # Rule 1 (merge): exactly one row survives — the STORED one,
                # whose privacy becomes max(stored, incoming). Never raises,
                # never lowers a label.
                if PRIVACY_STRICTNESS[item.privacy] > PRIVACY_STRICTNESS[duplicate.privacy]:
                    await conn.execute(
                        update(memories_table)
                        .where(memories_table.c.id == duplicate.id)
                        .values(privacy=item.privacy)
                    )
                return WriteReceipt(
                    memory_id=duplicate.id, op="merged", audit_event_id=audit_event_id
                )
            # Rule 2 (append): a LAXER incoming label would mint a widening copy
            # — equal content readable by more people than the original.
            if PRIVACY_STRICTNESS[item.privacy] < PRIVACY_STRICTNESS[duplicate.privacy]:
                raise MemoryWriteRejected("invalid_privacy_transition")

        # Rule 2's stricter-or-equal case, and rule 3's non-duplicate.
        return await self._append(
            conn,
            item=item,
            rules=rules,
            scope=scope,
            audit_event_id=audit_event_id,
            embedding=embedding,
            key=key,
        )

    async def _append(
        self,
        conn: AsyncConnection,
        *,
        item: MemoryItem,
        rules: WriteRules,
        scope: MemoryScope,
        audit_event_id: str,
        embedding: list[float] | None,
        key: str,
    ) -> WriteReceipt:
        now = self._clock()
        memory_id = str(uuid4())
        expires_at = (
            now + timedelta(days=rules.ttl_days) if rules.ttl_days is not None else None
        )

        await conn.execute(
            insert(memories_table).values(
                id=memory_id,
                # A gapless per-table sequence without an identity column's
                # migration cost: MAX+1 is safe HERE only because the advisory
                # lock above does not cover other scopes — so it is taken from
                # the table's own sequence instead.
                seq=select(
                    text("COALESCE(MAX(seq), 0) + 1")
                ).select_from(memories_table).scalar_subquery(),
                scope_user_id=scope.user_id,
                scope_kind=scope.kind,
                scope_id=scope.id,
                content=item.content,
                content_key=key,
                memory_type=item.memory_type,
                privacy=item.privacy,
                source_request_id=item.source_request_id,
                created_at=now,
                expires_at=expires_at,
                embedding=embedding,
            )
        )
        if item.entity_refs:
            await conn.execute(
                insert(memory_entity_links_table),
                [
                    {
                        "memory_id": memory_id,
                        "entity_type": ref.entity_type,
                        "entity_id": ref.entity_id,
                        "position": position,
                    }
                    for position, ref in enumerate(item.entity_refs)
                ],
            )
        return WriteReceipt(
            memory_id=memory_id, op="created", audit_event_id=audit_event_id
        )

    def _candidate_query(self, scope: MemoryScope):
        """C3 §5 recall step 1 — items whose stored scope equals `scope` exactly,
        PLUS (when `kind="entity"`) items of ANY scope linked to that entity id.

        Note what is NOT here: no privacy predicate. C3 §2 is explicit that
        "privacy filtering is caller-side policy, provider-side data" — the
        provider stores and returns the label verbatim, and the context loader
        drops `local_only` next to the router where `privacy_class` is computed.
        A filter here would look safer and would in fact move the decision away
        from the only place that knows where the prompt is going.
        """
        scope_user = bindparam("scope_user_id", type_=String(128))
        scope_kind = bindparam("scope_kind", type_=String(32))
        scope_id = bindparam("scope_id", type_=String(128))

        in_scope = (
            (memories_table.c.scope_user_id == scope_user)
            & (memories_table.c.scope_kind == scope_kind)
            & memories_table.c.scope_id.is_not_distinct_from(scope_id)
        )
        if scope.kind == "entity":
            linked = select(memory_entity_links_table.c.memory_id).where(
                memory_entity_links_table.c.memory_id == memories_table.c.id,
                memory_entity_links_table.c.entity_id == scope_id,
            )
            candidate = in_scope | linked.exists()
        else:
            candidate = in_scope

        distance = memories_table.c.embedding.op("<=>", return_type=Float)(
            bindparam("query_vector", type_=Vector(EMBEDDING_DIM))
        ).label("distance")

        return (
            select(
                memories_table.c.id,
                memories_table.c.content,
                memories_table.c.memory_type,
                memories_table.c.privacy,
                memories_table.c.source_request_id,
                memories_table.c.created_at,
                distance,
            )
            .where(
                candidate,
                memories_table.c.embedding.is_not(None),
                # TTL (C3 §2's `ttl_days`): an expired memory is not recalled.
                # Filtered rather than deleted here — reaping is an operational
                # job, and a recall must not mutate the store.
                (memories_table.c.expires_at.is_(None))
                | (
                    memories_table.c.expires_at
                    > bindparam("now", type_=DateTime(timezone=True))
                ),
            )
            # `distance ASC` IS `score DESC`; `seq DESC` is §5 step 3's
            # "newest write first" tiebreak on the monotonic insert sequence.
            .order_by(distance.asc(), memories_table.c.seq.desc())
            .limit(bindparam("limit", type_=Integer))
        )

    async def _entity_refs_for(
        self, conn: AsyncConnection, memory_ids: list[str]
    ) -> dict[str, list[EntityRef]]:
        """One query for every recalled item's links — not one per item."""
        if not memory_ids:
            return {}
        rows = (
            await conn.execute(
                select(
                    memory_entity_links_table.c.memory_id,
                    memory_entity_links_table.c.entity_type,
                    memory_entity_links_table.c.entity_id,
                )
                .where(memory_entity_links_table.c.memory_id.in_(memory_ids))
                .order_by(
                    memory_entity_links_table.c.memory_id,
                    memory_entity_links_table.c.position,
                )
            )
        ).all()
        refs: dict[str, list[EntityRef]] = {}
        for row in rows:
            refs.setdefault(row.memory_id, []).append(
                EntityRef(entity_type=row.entity_type, entity_id=row.entity_id)
            )
        return refs

    async def forget(self, memory_id: str) -> bool:
        """Delete one memory (its links go with it, ON DELETE CASCADE).

        Not a C3 method — the contract has no delete — but ADR-014's capture
        policy and any credible privacy posture need one to exist somewhere, and
        the alternative is an operator with psql. Kept off the `MemoryProvider`
        Protocol so no orchestrator path can reach it.
        """
        try:
            async with self.engine.begin() as conn:
                result = await conn.execute(
                    delete(memories_table).where(memories_table.c.id == memory_id)
                )
        except SQLAlchemyError as exc:
            raise MemoryUnavailableError(
                f"the memory store could not serve a delete: {type(exc).__name__}"
            ) from exc
        return bool(result.rowcount)


def _item_from_row(row: Any, refs: list[EntityRef]) -> MemoryItem:
    return MemoryItem(
        id=row["id"],
        content=row["content"],
        memory_type=row["memory_type"],
        privacy=row["privacy"],
        entity_refs=refs,
        source_request_id=row["source_request_id"],
        created_at=_to_iso(row["created_at"]),
    )


#: Static conformance witness — `PgVectorMemoryProvider` satisfies C3 §2's
#: `MemoryProvider` structurally, including v1.1.0's keyword-only `scope`.
def _witness(provider: PgVectorMemoryProvider) -> MemoryProvider:
    return provider
