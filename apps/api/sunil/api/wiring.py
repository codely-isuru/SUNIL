"""The seam table — where every frozen contract's implementation is plugged in.

`create_app()` resolves four seams (C1 Tool Manager, C2 provider, C3 memory, C4
approvals) plus the conversation resolver and the turn executor, choosing each
from `Settings` (§3's plug order). Two rules make this a boundary rather than a
convenience:

1. **Production code never imports a test double.** A `fake` selection resolves
   to the object the caller INJECTED via `Seams`; nothing here imports
   `tests.fakes`. An uninjected `fake` raises `SeamUnavailable` at boot, so an
   app cannot come up half-wired and discover it on the first request.
2. **An unbuilt `real` implementation is a loud boot failure**, naming the stream
   that owns it. Streams A/B/D land their implementations behind these same
   names; until then "real" is a `SeamUnavailable`, never a silent fallback to a
   fake — a fallback is how a fake reaches production.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from sunil.core.conversations.resolver import ResolvedConversation
from sunil.logging import get_logger


class SeamUnavailable(Exception):
    """A contract's implementation was selected but is not wired.

    Raised at application construction, never on the request path: the whole
    point of ADR-018's factory is that a misconfigured app does not boot.
    """


class ConversationResolver(Protocol):
    """Resolution happens in the ROUTE, before any turn machinery runs, because
    a 404 for an unknown or out-of-lane conversation is an authorisation answer
    and must not depend on the orchestrator having started."""

    async def resolve(
        self, *, lane: str, conversation_id: str | None, user_id: str | None,
        channel_label: str | None = None,
    ) -> ResolvedConversation: ...


class TurnExecutor(Protocol):
    """One governed turn. The real one is
    `core.orchestrator.turn.GovernedTurnExecutor`; C5 §4's `StubTurnExecutor`
    satisfies the same shape, which is what lets the C5 suite exercise the REAL
    route (auth deps + validation + envelope builder) before the orchestrator is
    involved."""

    async def run(
        self,
        *,
        message: str,
        conversation: ResolvedConversation,
        request_id: str,
        lane: str,
        user_id: str | None,
        channel_label: str | None,
    ) -> Any: ...  # a `schemas.ChatResponse`; typed `Any` to keep core/api decoupled


@dataclass(frozen=True)
class Seams:
    """Injected implementations. Every field defaults to `None`, meaning "resolve
    from settings"; a test (or a stream building ahead of its neighbours) passes
    the ones it owns."""

    sessionmaker: async_sessionmaker[AsyncSession] | None = None
    provider: Any | None = None  # C2 LLMProvider
    memory_provider: Any | None = None  # C3 MemoryProvider
    approvals: Any | None = None  # C4 ApprovalsService
    tool_manager: Any | None = None  # C1 ToolManagerProtocol
    tool_adapters: tuple[Any, ...] = ()  # C1 ToolAdapters, for the plan catalogue
    conversation_resolver: ConversationResolver | None = None
    turn_executor: TurnExecutor | None = None


def _require(injected: Any, *, setting: str, value: str) -> Any:
    if injected is None:
        raise SeamUnavailable(
            f"{setting}={value!r} selects an injected implementation, but none was "
            "passed to create_app(seams=…). Production code never imports a test "
            "double, so this is a boot failure rather than a fallback."
        )
    return injected


def _unbuilt(*, setting: str, stream: str, module: str) -> SeamUnavailable:
    return SeamUnavailable(
        f"{setting}='real' selects {module}, which Stream {stream} has not landed "
        "yet. Refusing to boot rather than falling back to a fake."
    )


def resolve_provider(settings: Any, seams: Seams) -> Any:
    """C2 — the model provider lane (transport wiring only; router policy is
    upstream of it and invisible here).

    `gateway` and `direct` are both REAL now: `providers/wiring.py` reads
    `config/models.yaml`, runs the ADR-033 named-host validator over the gateway
    base URL and builds Stream B's provider registry. What comes back satisfies
    C2 §2's `LLMProvider`, so the orchestrator is unchanged and cannot tell the
    lanes apart — which is the property ADR-033 exists to keep.
    """
    lane = settings.sunil_llm_provider_lane
    if lane == "fake":
        return _require(seams.provider, setting="SUNIL_LLM_PROVIDER_LANE", value=lane)
    if seams.provider is not None:
        return seams.provider
    from sunil.providers.wiring import build_provider  # noqa: PLC0415 - see module docstring

    return build_provider(settings)


def resolve_memory_provider(settings: Any, seams: Seams) -> Any:
    """C3 — the long-term memory provider behind `core/memory/service.py`."""
    selected = settings.sunil_memory_provider
    if selected == "fake":
        return _require(seams.memory_provider, setting="SUNIL_MEMORY_PROVIDER", value=selected)
    if seams.memory_provider is not None:
        return seams.memory_provider
    raise _unbuilt(
        setting="SUNIL_MEMORY_PROVIDER", stream="C", module="memory_providers/mem0_provider.py"
    )


def resolve_approvals(settings: Any, seams: Seams, *, engine: Any = None) -> Any:
    """C4 — park/consume. The Tool Manager is its only caller (C4 §1).

    The real resolution is `DatabaseApprovalsService` on the APPLICATION's engine,
    never one of its own: the mounted queue reads the `approvals` table through
    `core/approvals/read_model.py` on `app.state.ops_engine`, and a service
    holding a second engine would let the chokepoint park into one database while
    the owner's dashboard polled another.

    `notifier`, `tasks` and `scheduler` are C4 §3 collaborators the spine does not
    have yet (the continuation scheduler is ADR-031's resume path, wave 3): each
    absent one degrades a named after-effect, which `routes/approvals.py`
    already logs as a WARNING rather than a 500 — a decision the owner made must
    not fail because a collaborator is missing.
    """
    selected = settings.sunil_approvals_service
    if selected == "fake":
        return _require(seams.approvals, setting="SUNIL_APPROVALS_SERVICE", value=selected)
    if seams.approvals is not None:
        return seams.approvals
    if engine is None:
        raise SeamUnavailable(
            "SUNIL_APPROVALS_SERVICE='real' selects core/approvals/service.py, which "
            "is a database service, but no engine was available at wiring time. "
            "Refusing to boot rather than serving an approvals queue backed by "
            "nothing."
        )
    from sunil.core.approvals.config import ApprovalsConfig  # noqa: PLC0415
    from sunil.core.approvals.notify import notifier_for  # noqa: PLC0415
    from sunil.core.approvals.service import DatabaseApprovalsService  # noqa: PLC0415

    webhook = settings.sunil_approval_notify_webhook_url
    return DatabaseApprovalsService(
        engine=engine,
        config=ApprovalsConfig(
            ttl_hours=settings.sunil_approval_ttl_hours,
            consume_grace_hours=settings.sunil_approval_consume_grace_hours,
            notify_webhook_url=webhook,
        ),
        notifier=notifier_for(webhook),
    )


def resolve_tool_manager(
    settings: Any,
    seams: Seams,
    *,
    approvals: Any = None,
    sessionmaker: Any = None,
    registry: Any = None,
) -> Any:
    """C1 — the single execution chokepoint. The spine never constructs one: it
    is `core/tool_framework/manager.py`, Stream A's file, and a second
    implementation of the chokepoint is a second path to a privileged call.

    The real resolution is a FACTORY, not a manager: C1's audit hook is bound to
    one plan execution (ADR-004 Amendment 1), so the orchestrator mints a hook per
    plan and this factory builds the chokepoint around it. `main.py` already
    understands both shapes.

    Three things are decided here, once, at boot:

    * the registry — `config/tools.yaml`'s adapters, minus any that could not be
      built (C1 §5: absent from the registry, never half-present);
    * the permission hook — the REAL `PermissionEngineHook` over
      `config/permissions.yaml`, whose default-deny is structural;
    * whether the C-1 transactional seam is available. It needs a database C4
      service and an audit hook that can write on its connection; when either is
      missing the manager is built without it rather than with a collaborator
      that cannot honour C1 §2.1 step 4. That decision is made HERE so the
      request path never sniffs a seam for capabilities.
    """
    selected = settings.sunil_tool_manager
    if selected == "fake":
        return _require(seams.tool_manager, setting="SUNIL_TOOL_MANAGER", value=selected)
    if seams.tool_manager is not None:
        return seams.tool_manager

    from sunil.core.permissions.engine import PermissionEngineHook  # noqa: PLC0415
    from sunil.core.tool_framework.manager import ToolManager  # noqa: PLC0415
    from sunil.core.tool_framework.transaction import TransactionalApprovals  # noqa: PLC0415

    if registry is None:
        registry = build_tool_registry(settings)
    if approvals is None or sessionmaker is None:
        raise SeamUnavailable(
            "SUNIL_TOOL_MANAGER='real' needs the resolved C4 service and the "
            "application's sessionmaker: the chokepoint parks through one and "
            "audits through the other, and a manager missing either would execute "
            "privileged calls with no trail."
        )
    permission_hook = PermissionEngineHook(registry.permissions)
    adapters = list(registry.adapters)

    def factory(audit_hook: Any) -> ToolManager:
        transaction = None
        if hasattr(approvals, "engine") and callable(getattr(audit_hook, "attempt_on", None)):
            transaction = TransactionalApprovals(approvals=approvals, audit=audit_hook)
        return ToolManager(
            adapters, permission_hook, approvals, audit_hook, transaction=transaction
        )

    return factory


# --------------------------------------------------------------------------- #
# The real tool registry — ADR-034's "callable IFF configured AND granted"
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class ToolRegistry:
    """What `config/tools.yaml` + `config/permissions.yaml` produced at boot.

    `skipped` is not diagnostics: it is the list of tools this process CANNOT
    offer, each with the reason, and it is logged as a WARNING. C1 §5's rule is
    that a tool which cannot start is *absent from the registry, never
    half-present* — so absence is correct, and silence about it is not.
    """

    adapters: tuple[Any, ...]
    permissions: Any
    skipped: tuple[tuple[str, str], ...] = ()

    @property
    def tool_names(self) -> set[str]:
        return {adapter.name for adapter in self.adapters}


def build_tool_registry(settings: Any) -> ToolRegistry:
    """Load the tool and permission configs and construct every adapter that can
    be constructed.

    Order is deliberate:

    1. load both files — a malformed one is a boot failure (`ToolsConfigError` /
       `PermissionsConfigError`), because a half-understood permission-adjacent
       config is worse than none;
    2. cross-validate them — a grant for a tool or operation nothing exposes is a
       config bug (ADR-034), and the alternative is a default-deny at the call
       site that looks like a permission decision rather than a typo;
    3. build adapters, skipping (loudly) any whose construction fails. A missing
       `GITHUB_TOKEN` is an operator state, not a code bug: refusing to boot
       would take the whole assistant down because one tool has no credential.
    """
    from pathlib import Path  # noqa: PLC0415

    from sunil.core.permissions.registry import load_permissions  # noqa: PLC0415
    from sunil.core.tool_framework.tools_config import (  # noqa: PLC0415
        cross_validate_permissions,
        load_tools_config,
    )
    from sunil.core.tool_framework.wiring import build_adapters  # noqa: PLC0415

    config_dir = Path(settings.sunil_config_dir)
    tools = load_tools_config(config_dir / "tools.yaml")
    permissions = load_permissions(config_dir / "permissions.yaml")
    cross_validate_permissions(tools, permissions)

    adapters, skipped = build_adapters(tools, settings=settings)
    logger = get_logger("sunil.api.wiring")
    for server_id, reason in skipped:
        logger.warning(
            "tool_unavailable",
            tool=server_id,
            reason=reason,
            consequence="the tool is absent from this process's registry (C1 §5): "
            "it cannot be planned and cannot be executed",
        )
    return ToolRegistry(
        adapters=tuple(adapters), permissions=permissions, skipped=tuple(skipped)
    )


def warn_on_ungrantable_catalogue(registries: Any, *, catalogue_tools: set[str]) -> None:
    """Wave-1 ruling R1's follow-up: warn when an `agents.yaml` grant names a tool
    the wired catalogue does not offer.

    `load_registries` cross-validates nothing in the grants→tools direction, so
    an operator typo (`github` → `githbu`) produces a tool that can never be
    planned and never explains why — the plan validator simply rejects every step
    naming it, at request time, as if the model had hallucinated.

    A WARNING and never a refusal, exactly as the ruling says: `config/agents.yaml`
    legitimately grants `fake_tool` today (structurally inert — a grant can only
    NARROW the adapter-built catalogue, never add to it), and failing here would
    make a documented, safe state unbootable.
    """
    logger = get_logger("sunil.api.wiring")
    for agent_id, agent in getattr(registries, "agents", {}).items():
        granted = set(getattr(agent, "tools", {}) or {})
        missing = sorted(granted - catalogue_tools)
        if missing:
            logger.warning(
                "granted_tool_not_in_catalogue",
                agent=agent_id,
                granted_but_unwired=missing,
                wired_catalogue=sorted(catalogue_tools),
                consequence="these grants can never be planned — a plan step naming "
                "one is rejected at validation (layer 4). Expected for a test-only "
                "grant; a typo otherwise (wave-1 ruling R1)",
            )
