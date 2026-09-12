"""`SUNIL_MEMORY_PROVIDER` resolution — wiring.py's C3 seam.

Three postures, all of them `wiring.py`'s stated rules rather than new ones:

* `fake` still requires an INJECTED seam. Production code never imports a test
  double, so an uninjected `fake` is a boot failure and not a fallback.
* `pgvector` is now REAL — it resolves to `memory_providers/pgvector_provider.py`
  on the application's engine.
* `mem0` is still unbuilt, and selecting it is a loud `SeamUnavailable` naming
  the module, never a silent fallback to the built provider. That matters more
  now than it did while both were unbuilt: falling back would give an operator
  who asked for Mem0 a different engine with different retrieval, silently.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import create_async_engine

from sunil.api.wiring import Seams, SeamUnavailable, resolve_memory_provider
from sunil.memory_providers.pgvector_provider import PgVectorMemoryProvider
from tests.spine_harness import build_settings


def engine():
    return create_async_engine("postgresql+psycopg://u:p@127.0.0.1:1/none")


def test_fake_without_an_injected_seam_refuses_to_boot() -> None:
    with pytest.raises(SeamUnavailable) as err:
        resolve_memory_provider(build_settings(sunil_memory_provider="fake"), Seams())

    assert "SUNIL_MEMORY_PROVIDER" in str(err.value)


def test_fake_with_an_injected_seam_returns_exactly_what_was_injected() -> None:
    injected = object()

    resolved = resolve_memory_provider(
        build_settings(sunil_memory_provider="fake"),
        Seams(memory_provider=injected),
    )

    assert resolved is injected


def test_pgvector_resolves_to_the_real_provider_on_the_application_engine() -> None:
    """The application's engine, never one of its own: a provider holding a
    second engine would write memories into one database while the rest of the
    turn — the audit row that names them included — used another."""
    application_engine = engine()

    resolved = resolve_memory_provider(
        build_settings(sunil_memory_provider="pgvector"), Seams(), engine=application_engine
    )

    assert isinstance(resolved, PgVectorMemoryProvider)
    assert resolved.engine is application_engine
    assert resolved.name == "pgvector"


def test_pgvector_without_an_engine_refuses_to_boot() -> None:
    """A memory provider with no database is a memory provider that loses every
    write. `resolve_approvals` makes the same refusal for the same reason."""
    with pytest.raises(SeamUnavailable) as err:
        resolve_memory_provider(build_settings(sunil_memory_provider="pgvector"), Seams())

    assert "engine" in str(err.value)


def test_pgvector_uses_the_configured_embedder() -> None:
    """`SUNIL_MEMORY_EMBEDDER` chooses; `hashing` is the default because it is
    the only one that needs no credential."""
    resolved = resolve_memory_provider(
        build_settings(sunil_memory_provider="pgvector"), Seams(), engine=engine()
    )

    assert resolved._embedder.name == "hashing"


def test_the_gateway_embedder_without_a_key_refuses_to_boot() -> None:
    """Not a downgrade to lexical hashing: a deployment that ASKED for semantic
    recall must not quietly get something else."""
    from sunil.core.memory.embedding import EmbeddingUnavailableError

    with pytest.raises(EmbeddingUnavailableError) as err:
        resolve_memory_provider(
            build_settings(sunil_memory_provider="pgvector", sunil_memory_embedder="gateway"),
            Seams(),
            engine=engine(),
        )

    assert "SUNIL_MEMORY_EMBEDDING_API_KEY" in str(err.value)


def test_mem0_is_still_unbuilt_and_says_so() -> None:
    """ADR-030's seam is real only if the OTHER engine is still selectable and
    still refuses loudly. A silent fallback to pgvector here would mean an
    operator who configured Mem0 got different retrieval without being told."""
    with pytest.raises(SeamUnavailable) as err:
        resolve_memory_provider(
            build_settings(sunil_memory_provider="mem0"), Seams(), engine=engine()
        )

    assert "mem0_provider.py" in str(err.value)


def test_an_injected_seam_still_wins_over_a_real_selection() -> None:
    """The pattern every other seam follows: a stream building ahead of its
    neighbours passes the one it owns."""
    injected = object()

    resolved = resolve_memory_provider(
        build_settings(sunil_memory_provider="pgvector"),
        Seams(memory_provider=injected),
        engine=engine(),
    )

    assert resolved is injected
