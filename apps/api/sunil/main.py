"""`create_app()` — the application factory (ADR-018).

**One `Settings` per application, on `app.state`.** Nothing in the request path
calls `get_settings()`: that module-level cache exists for contexts with no app
(Alembic, `scripts/*`), and using it here would make two apps with two
configurations impossible in one process — which is exactly what the test suite
needs, and what a "it works on my machine because of an ambient env var" bug is
made of.

**The app either boots correctly or does not boot.** Registry load, seam
resolution and secret registration all happen during construction, so a missing
`config/agents.yaml`, an unwired seam or an unbuilt implementation is a startup
failure with a named cause rather than a 500 on the first real request.

Order inside the factory is deliberate: settings → logging → **secret
registration** → registries → seams → routes. Registration comes before anything
that could log, so a secret cannot reach a log line during boot itself.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from sunil.api import wiring
from sunil.api.errors import (
    ApiError,
    api_error_handler,
    http_exception_handler,
    ops_api_error_handler,
    validation_error_handler,
)
from sunil.api.middleware import install_middleware
from sunil.api.routes import activity as activity_routes
from sunil.api.routes import approvals as approvals_routes
from sunil.api.routes import audit as audit_routes
from sunil.api.routes import auth as auth_routes
from sunil.api.routes import chat as chat_routes
from sunil.api.routes import health as health_routes
from sunil.api.routes import tasks as tasks_routes
from sunil.api.wiring import Seams
from sunil.agents.project_manager import ProjectManagerAgent
from sunil.core.conversations.resolver import DbConversationResolver
from sunil.core.memory.service import MemoryService
from sunil.core.orchestrator.plan_validator import ToolCatalogue
from sunil.core.orchestrator.turn import GovernedTurnExecutor
from sunil.core.approvals.sweeper import ApprovalSweeper
from sunil.core.registry.loader import load_registries
from sunil.db.session import get_engine, get_sessionmaker
from sunil.logging import configure_logging, get_logger
from sunil.redaction import register_secrets_from_settings
from sunil.settings import Settings


def create_app(settings: Settings | None = None, *, seams: Seams | None = None) -> FastAPI:
    """Build an application. `seams` injects implementations a deployment (or a
    test) provides itself; everything else is resolved from `settings`."""
    settings = settings if settings is not None else Settings()
    seams = seams if seams is not None else Seams()

    configure_logging(log_level=settings.log_level)
    # Before anything else can log or persist (C5 §3's defence-in-depth clause).
    register_secrets_from_settings(settings)
    logger = get_logger("sunil.api")

    registries = load_registries(settings.sunil_config_dir)

    engine = None
    sessionmaker: async_sessionmaker[AsyncSession]
    if seams.sessionmaker is not None:
        sessionmaker = seams.sessionmaker
    else:
        engine = get_engine(settings)
        sessionmaker = get_sessionmaker(engine)

    # The engine the C4 service, the ops reads and the chokepoint's audit hook
    # must all share. Derived from an injected sessionmaker when a test supplied
    # one, so "the queue reads what the chokepoint wrote" holds in both shapes.
    read_engine = engine if engine is not None else sessionmaker.kw.get("bind")

    provider = wiring.resolve_provider(settings, seams)
    # The APPLICATION's engine, for `resolve_memory_provider`'s reason: the audit
    # row that names a memory is written on this connection, and a provider
    # holding a second engine would file the memory in one database while its own
    # trail lived in another.
    memory_provider = wiring.resolve_memory_provider(settings, seams, engine=read_engine)
    approvals = wiring.resolve_approvals(settings, seams, engine=read_engine)

    # The tool registry is built ONCE, here: the plan catalogue the model is
    # offered and the adapters the chokepoint can reach must be the same set, or
    # the model is offered a tool that cannot execute (or the reverse — a tool
    # nothing can plan). An injected `tool_adapters` wins, because a test that
    # injects adapters is describing the whole registry.
    tool_registry = None
    adapters: tuple[Any, ...] = seams.tool_adapters
    if settings.sunil_tool_manager != "fake" and seams.tool_manager is None:
        tool_registry = wiring.build_tool_registry(settings)
        if not adapters:
            adapters = tool_registry.adapters
    tool_manager = wiring.resolve_tool_manager(
        settings,
        seams,
        approvals=approvals,
        sessionmaker=sessionmaker,
        registry=tool_registry,
    )

    catalogue = ToolCatalogue.from_adapters(adapters)
    # Wave-1 ruling R1's follow-up: a grant naming a tool this process did not
    # wire can never be planned, and says so at boot rather than at request time.
    wiring.warn_on_ungrantable_catalogue(
        registries, catalogue_tools={adapter.name for adapter in adapters}
    )

    conversation_resolver = (
        seams.conversation_resolver
        if seams.conversation_resolver is not None
        else DbConversationResolver(sessionmaker)
    )

    turn_executor = seams.turn_executor
    if turn_executor is None:
        turn_executor = GovernedTurnExecutor(
            sessionmaker=sessionmaker,
            provider=provider,
            memory=MemoryService(memory_provider),
            # The Tool Manager is constructed per plan execution, because its
            # audit hook is bound to that plan's id (ADR-004 Amendment 1). The
            # factory closes over the seam-resolved manager rather than building
            # a second chokepoint here.
            tool_manager_factory=_tool_manager_factory(tool_manager),
            registries=registries,
            catalogue=catalogue,
            agent=ProjectManagerAgent(),
            turn_deadline_s=settings.sunil_turn_deadline_s,
        )

    sweeper = _build_sweeper(approvals, settings, logger)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        started_adapters: list[Any] = []
        for adapter in adapters:
            # C1 §5 / S-A-tools §4: a failed start does not take the app down —
            # an MCP server that is not running must not stop the owner talking
            # to SUNIL.
            #
            # Precisely (security residual D-1): this is NOT the build-time
            # "absent from the registry" case. The registry already exists by
            # now, so the tool remains PRESENT and plannable and its calls fail
            # at the chokepoint as `transport_error` — which is what the warning
            # below states, and what this comment used to contradict.
            try:
                await adapter.start()
                started_adapters.append(adapter)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "tool_start_failed",
                    tool=getattr(adapter, "name", "?"),
                    error=type(exc).__name__,
                    consequence="the tool is present in the catalogue but its "
                    "transport is down; calls will fail as transport_error",
                )
        # C2 §3's model-parity check, when the wired provider has one: a drifted
        # gateway alias namespace is a boot failure, never a 400 mid-turn.
        provider_start = getattr(provider, "start", None)
        if callable(provider_start):
            await provider_start()
        if sweeper is not None:
            # Before the first request is served: `start()` awaits C4 §3 /
            # ADR-031's one-shot reconciliation, and a failure there is NOT
            # swallowed (see sweeper.py) — an API that booted having silently
            # skipped it would leave interrupted continuations looking runnable.
            await sweeper.start()
        logger.info("app_started", lane=settings.sunil_llm_provider_lane)
        try:
            yield
        finally:
            # Stopped FIRST, and before the engine is disposed: a sweep tick
            # holding a connection into `engine.dispose()` is a shutdown that
            # logs an error on every restart.
            if sweeper is not None:
                await sweeper.stop()
            for adapter in started_adapters:
                await adapter.stop()
            provider_close = getattr(provider, "aclose", None)
            if callable(provider_close):
                await provider_close()
            if engine is not None:
                await engine.dispose()

    app = FastAPI(
        title="SUNIL V2 API",
        version="0.1.0",
        lifespan=lifespan,
        # The C5/C4 contracts are the source of truth for the wire shape; the
        # generated schema is a convenience, never the specification.
        openapi_url="/openapi.json",
    )

    app.state.settings = settings
    app.state.registries = registries
    app.state.seams = seams
    app.state.sessionmaker = sessionmaker
    app.state.engine = engine
    app.state.provider = provider
    app.state.approvals = approvals
    app.state.tool_manager = tool_manager
    app.state.catalogue = catalogue
    app.state.tool_adapters = adapters
    app.state.conversation_resolver = conversation_resolver
    app.state.turn_executor = turn_executor
    app.state.approvals_sweeper = sweeper
    app.state.logger = logger

    # The three names Stream D's routers read off app state. They are set here,
    # in the factory, rather than by whoever mounts the routers, because each has
    # a failure mode that is invisible at the route:
    #   * `approvals_service` — a 500 if missing (C4's own choice: an unwired
    #     route is a deployment bug, and a 404 would hide it).
    #   * `ops_engine` — a RuntimeError if missing, deliberately, because an
    #     unwired ops route answering `{"tasks": []}` looks like a quiet system.
    #     Derived from the sessionmaker when a caller injected one, so the reads
    #     and the writes are guaranteed to be the same database rather than two.
    #   * `web_origin` — Stream D's `require_web_client` SKIPS the Origin
    #     comparison when this is unset. Unset is not lenient, it is absent: the
    #     ADR-008 CSRF pair would silently be down to one header.
    app.state.approvals_service = approvals
    app.state.ops_engine = read_engine
    app.state.web_origin = settings.web_origin

    install_middleware(app, settings)

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(approvals_routes.ApiError, ops_api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    # Explicit, one at a time, with no router-level dependencies — see
    # `routes/__init__.py` for why that matters. Stream D's routers are factories
    # (a fresh router per app, so two apps in one process cannot share route
    # objects); the spine's are module-level singletons. Both mount flat.
    for router in (health_routes.router, auth_routes.router, chat_routes.router):
        _mount(app, router)
    for factory in (
        approvals_routes.create_router,
        tasks_routes.create_router,
        activity_routes.create_router,
        audit_routes.create_router,
    ):
        _mount(app, factory())

    return app


def _build_sweeper(approvals: Any, settings: Settings, logger: Any) -> ApprovalSweeper | None:
    """C4 §1's schedule, or `None` with a reason.

    Stream D built the runner and left the wiring as the seam
    (`docs/tasks/S-D-approvals.md` §5); this is that seam, closed.

    Two ways to get `None`, and they are not the same thing, so they are not
    logged the same way:

    * the operator turned it off — an informational line, the switch worked;
    * the resolved C4 seam has no schedule (C4 §6's fake has `sweep(now)` and no
      `reconcile_on_startup`) — a WARNING, because "no sweeper" is a real
      degradation of C4 §1 whenever the service could have had one, and a silent
      `None` is how a deployment discovers it from an expired approval that was
      still spendable.

    Not a boot failure: refusing to start would make every test and every
    in-memory deployment that legitimately has nothing to sweep unbootable, and
    `wiring.py` already fails closed on the seam that actually matters (an
    unbuilt implementation). This is a schedule over a wired service, not a
    missing contract.
    """
    if not settings.sunil_approvals_sweeper_enabled:
        logger.info("approvals_sweeper_disabled", reason="SUNIL_APPROVALS_SWEEPER_ENABLED")
        return None
    if not hasattr(approvals, "reconcile_on_startup"):
        logger.warning(
            "approvals_sweeper_unavailable",
            reason="the resolved C4 service has no reconcile_on_startup()",
            service=type(approvals).__name__,
            consequence="C4 §1's startup + 60 s schedule does not run in this process",
        )
        return None
    return ApprovalSweeper(approvals)


def _mount(app: FastAPI, router: Any) -> None:
    """Attach a router's routes to the application table, flat.

    `include_router()` on FastAPI ≥ 0.141 records a lazy `_IncludedRouter` entry
    instead of appending the individual routes, so `app.routes` no longer exposes
    a per-route `dependant`. That breaks the ONE audit that can prove the
    machine-token blast radius at build time — C5 contract test 8 (Security
    review item 6) walks `app.routes` and asserts `require_service_token` is
    reachable from exactly one route's dependency tree.

    Appending the routes keeps that table walkable, and has a second property
    worth having: there is no `dependencies=` parameter on this call at all, so a
    router-wide dependency (the exact mistake test 8 exists to catch) cannot be
    added here by habit.
    """
    for route in router.routes:
        app.router.routes.append(route)


def _tool_manager_factory(tool_manager: Any) -> Any:
    """Bind the turn's audit hook to the resolved Tool Manager.

    Two shapes are supported on purpose: a *callable* seam (the app constructs a
    manager per plan, passing the hook) and an already-constructed manager (a
    test's double, or a deployment that built one at boot). The second path
    attaches the hook rather than rebuilding the chokepoint — the spine must
    never construct a second one.
    """

    def factory(audit_hook: Any) -> Any:
        if callable(tool_manager) and not hasattr(tool_manager, "execute"):
            return tool_manager(audit_hook)
        return tool_manager

    return factory
