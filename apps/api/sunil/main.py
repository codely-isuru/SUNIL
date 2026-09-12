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
    validation_error_handler,
)
from sunil.api.middleware import install_middleware
from sunil.api.routes import auth as auth_routes
from sunil.api.routes import chat as chat_routes
from sunil.api.routes import health as health_routes
from sunil.api.wiring import Seams
from sunil.agents.project_manager import ProjectManagerAgent
from sunil.core.conversations.resolver import DbConversationResolver
from sunil.core.memory.service import MemoryService
from sunil.core.orchestrator.plan_validator import ToolCatalogue
from sunil.core.orchestrator.turn import GovernedTurnExecutor
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

    provider = wiring.resolve_provider(settings, seams)
    memory_provider = wiring.resolve_memory_provider(settings, seams)
    approvals = wiring.resolve_approvals(settings, seams)
    tool_manager = wiring.resolve_tool_manager(settings, seams)

    catalogue = ToolCatalogue.from_adapters(seams.tool_adapters)

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

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        for adapter in seams.tool_adapters:
            await adapter.start()
        logger.info("app_started", lane=settings.sunil_llm_provider_lane)
        try:
            yield
        finally:
            for adapter in seams.tool_adapters:
                await adapter.stop()
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
    app.state.conversation_resolver = conversation_resolver
    app.state.turn_executor = turn_executor
    app.state.logger = logger

    install_middleware(app, settings)

    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)

    # Explicit, one at a time, with no router-level dependencies — see
    # `routes/__init__.py` for why that matters.
    for router in (health_routes.router, auth_routes.router, chat_routes.router):
        _mount(app, router)

    return app


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
