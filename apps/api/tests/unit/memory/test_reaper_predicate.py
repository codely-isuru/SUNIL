"""The reaper's WHERE clause, graded on every leg — including the ones with no
database at all.

`test_reaper_sql.py` proves the rows actually move, and it is the better test:
it runs the statement against a real pgvector Postgres and counts what survives.
It is also **gated**, and on a machine where the Docker daemon will not start it
SKIPS — which is exactly the shape a "green" suite should not hide, because the
property at stake is destructive and one-way. A reaper whose boundary drifted
from `_candidate_query`'s TTL filter would delete memories the owner can still
recall, and no amount of SQLite-leg green would notice.

So this file grades the SAME production statement without a server: the provider
builds it, SQLAlchemy compiles it against the REAL Postgres dialect, and the
assertions are on the emitted SQL. The engine here records the statement and
returns a row count; nothing about the reaper's behaviour is simulated, and the
statement is not restated in the test (a test that rebuilt the `delete()` would
pass against itself).
"""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.dialects import postgresql

from sunil.core.memory.embedding import HashingEmbedder
from sunil.memory_providers.pgvector_provider import PgVectorMemoryProvider

#: A fixed "now", so the compiled SQL can be asserted to carry the PROVIDER's
#: clock rather than a wall clock read somewhere inside the statement.
FROZEN = datetime(2026, 9, 18, 12, 0, tzinfo=timezone.utc)


class CapturingEngine:
    """Records the statements executed inside `engine.begin()`.

    Deliberately NOT a mock of the provider: the provider is real, the statement
    is real, and the only thing standing in for the database is the transport.
    """

    def __init__(self, rowcount: int | None = 0) -> None:
        self.statements: list[object] = []
        self._rowcount = rowcount

    def begin(self):  # noqa: ANN201 - an async context manager, by hand
        engine = self

        class _Transaction:
            async def __aenter__(self):
                class _Connection:
                    async def execute(self, statement):  # noqa: ANN001
                        engine.statements.append(statement)
                        return SimpleNamespace(rowcount=engine._rowcount)

                return _Connection()

            async def __aexit__(self, *exc_info) -> bool:
                return False

        return _Transaction()


def provider_over(engine: CapturingEngine) -> PgVectorMemoryProvider:
    return PgVectorMemoryProvider(
        engine=engine,  # type: ignore[arg-type] - transport double, see above
        embedder=HashingEmbedder(),
        clock=lambda: FROZEN,
    )


def compiled(engine: CapturingEngine) -> str:
    """The one statement `delete_expired` built, as Postgres would receive it."""
    assert len(engine.statements) == 1, "delete_expired ran more than one statement"
    return str(
        engine.statements[0].compile(  # type: ignore[attr-defined]
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


async def test_the_reaper_deletes_only_what_the_recall_filter_already_hides() -> None:
    """`_candidate_query`'s TTL filter KEEPS a row when
    `expires_at IS NULL OR expires_at > now`. The complement — the only rows
    recall hides — is `expires_at IS NOT NULL AND expires_at <= now`, and that
    must be the delete's whole predicate.

    The `IS NOT NULL` half is the one worth a test on every leg: drop it and the
    statement still compiles, still deletes, and quietly destroys every
    "keep until superseded" memory in the store — the ones with no TTL at all,
    which is to say the ones the owner never asked to expire.
    """
    engine = CapturingEngine(rowcount=2)

    assert await provider_over(engine).delete_expired() == 2

    sql = compiled(engine)
    assert sql.startswith("DELETE FROM memories")
    where = sql.split("WHERE", 1)[1]
    assert "expires_at IS NOT NULL" in where
    assert "expires_at <= " in where
    # The keep-until-superseded rows are never matched: no `IS NULL` branch, and
    # no `>` that would invert the boundary onto the live side of the filter.
    assert "IS NULL" not in where
    assert "expires_at >" not in where


async def test_the_boundary_is_the_provider_s_clock() -> None:
    """The cut-off is the injected clock's instant, not `now()` evaluated by the
    database — the same clock `_candidate_query` binds, so the filter and the
    delete cannot disagree about when "expired" starts under clock skew."""
    engine = CapturingEngine(rowcount=0)

    await provider_over(engine).delete_expired()

    assert "2026-09-18 12:00:00" in compiled(engine)


async def test_a_driver_that_reports_no_rowcount_counts_as_zero() -> None:
    """`rowcount` is `-1`/`None` on drivers that do not report it. The reaper's
    return value feeds the audit row, so an unreportable batch must count as
    zero rather than crash the tick or write `None` into the trail."""
    engine = CapturingEngine(rowcount=None)

    assert await provider_over(engine).delete_expired() == 0
