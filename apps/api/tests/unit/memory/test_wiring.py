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

from sunil.api.wiring import (
    Seams,
    SeamUnavailable,
    build_memory_service,
    resolve_memory_provider,
)
from sunil.core.memory.service import MemoryService
from sunil.core.registry.loader import ProjectDefinition
from sunil.memory_providers.pgvector_provider import PgVectorMemoryProvider
from tests.fakes.fake_memory_provider import FakeMemoryProvider
from tests.ops_harness import build_ops_app
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


# --------------------------------------------------------------------------- #
# R13 item 4 — the MemoryService construction site
# --------------------------------------------------------------------------- #
def test_the_engine_branch_builds_a_service_with_a_resolver() -> None:
    """R13 item 4. Without this the resolver Stream C built is dead code in the
    deployed app: a `kind="project"` scope reaches the provider with the human
    key still in it, and every memory about a project is filed under the literal
    string "pda" — a scope nothing that resolves ids will ever read."""
    from sunil.core.memory.entities import EntityResolver

    application_engine = engine()

    service = build_memory_service(
        build_settings(sunil_memory_provider="pgvector"),
        Seams(),
        engine=application_engine,
    )

    assert isinstance(service, MemoryService)
    assert isinstance(service._resolver, EntityResolver)
    assert service._resolver.engine is application_engine


def test_the_fake_wired_composition_gets_no_resolver() -> None:
    """The frozen C3 contract suite runs against the fake-wired app, and its
    scopes are already ids. A resolver there would put an entity-table read in
    front of every recall in a composition that has no entity tables."""
    service = build_memory_service(
        build_settings(sunil_memory_provider="fake"),
        Seams(memory_provider=FakeMemoryProvider()),
        engine=None,
    )

    assert service._resolver is None


def test_the_service_carries_the_project_registry_for_r12_rule_3() -> None:
    """R12 rule 3 materialises registry → table on the write path, so the service
    needs the PROJECT REGISTRY (`config/projects.yaml`). Passing `None` would
    make rule 3 unreachable in the deployed app while its tests stayed green on
    an injected mapping."""
    registry = {"pda": ProjectDefinition(key="pda", display_name="PDA Learning")}

    service = build_memory_service(
        build_settings(sunil_memory_provider="pgvector"),
        Seams(),
        engine=engine(),
        projects=registry,
    )

    assert service._project_registry == registry


def test_the_composed_app_gives_its_turn_executor_a_resolved_memory_service() -> None:
    """The call site, not just the builder. `main.create_app` constructed
    `MemoryService(memory_provider)` by hand, so a resolver added to `wiring.py`
    alone would be wired into nothing — the deployed turn would still recall with
    an unresolved scope. This asserts the APPLICATION's own turn executor holds
    the service the builder makes, registry included.
    """
    from sunil.core.memory.entities import EntityResolver

    app, sessionmaker = build_ops_app()
    memory = app.state.turn_executor._memory

    assert isinstance(memory._resolver, EntityResolver)
    assert memory._resolver.engine is sessionmaker.kw["bind"]
    # The PROJECT REGISTRY (`config/projects.yaml`), not the entity table.
    assert memory._project_registry == app.state.registries.projects


# --------------------------------------------------------------------------- #
# The reaper's kill switch and its lifespan wiring (R15, S2-C §7.4)
# --------------------------------------------------------------------------- #
def _app_with_a_real_memory_store(**overrides):
    """A composition whose memory provider is the REAL one (`pgvector`) — the
    only shape that HAS a `delete_expired` to schedule. Composed here rather than
    through `build_ops_app`, which injects the C3 fake as a seam (and an injected
    seam wins over the selection, correctly). Nothing here touches a database:
    the question is what `create_app` WIRES, not what the store returns.
    """
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.pool import StaticPool

    from sunil.main import create_app
    from sunil.settings import Settings
    from tests.fakes.fake_approvals import FakeApprovalsService
    from tests.fakes.fake_provider import FakeProvider
    from tests.ops_harness import CONFIG_DIR

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    return create_app(
        Settings(
            _env_file=None,
            session_secret="test-session-secret-not-a-real-key",
            sunil_config_dir=CONFIG_DIR,
            sunil_memory_provider="pgvector",
            sunil_tool_manager="fake",
            sunil_approvals_service="fake",
            sunil_llm_provider_lane="fake",
            **overrides,
        ),
        seams=Seams(
            sessionmaker=async_sessionmaker(engine, expire_on_commit=False),
            provider=FakeProvider(),
            approvals=FakeApprovalsService(),
            tool_manager=lambda audit_hook: None,
        ),
    )


def test_the_reaper_is_built_by_default() -> None:
    """Defaults ON, like the approvals sweeper's switch and for the mirror-image
    reason: the safe posture is the one an operator gets by doing nothing, and
    here "nothing" means expired memories are filtered from recall forever and
    never actually destroyed."""
    from sunil.core.memory.reaper import MemoryReaper

    app = _app_with_a_real_memory_store()

    assert isinstance(app.state.memory_reaper, MemoryReaper)


def test_the_kill_switch_turns_the_reaper_off() -> None:
    """The switch exists for the real operator cases — a second process owning
    the schedule, or a reap implicated in an incident — and it must leave the app
    bootable with the rest of memory working."""
    app = _app_with_a_real_memory_store(sunil_memory_reaper_enabled=False)

    assert app.state.memory_reaper is None


def test_a_store_that_cannot_delete_gets_no_reaper() -> None:
    """The C3 fake has no `delete_expired`, and neither will Mem0 until someone
    builds it. A runner over a store with no delete would tick forever doing
    nothing — so it is not built, and the reason is logged rather than inferred
    later from an ever-growing table."""
    assert not hasattr(FakeMemoryProvider(), "delete_expired")

    app, _ = build_ops_app()  # fake-wired memory provider

    assert app.state.memory_reaper is None


async def test_the_reaper_is_started_on_boot_and_cancelled_on_shutdown() -> None:
    """The lifespan half — the sweeper's own lifespan test, for the other runner.
    A reaper built and never started is a reaper that deletes nothing, and a
    reaper never cancelled holds a connection into `engine.dispose()` and logs an
    error on every restart."""
    app = _app_with_a_real_memory_store()

    async with app.router.lifespan_context(app):
        reaper = app.state.memory_reaper
        assert reaper is not None, "the reaper seam was left unwired"
        task = reaper._task
        assert task is not None and not task.done()

    assert task.cancelled() or task.done(), "shutdown must stop the reap loop"
    assert app.state.memory_reaper._task is None
