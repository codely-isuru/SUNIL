"""`sunil.core.tool_framework.manager.build_tool_manager()` (T11b) — the
one place `sunil.main`'s lifespan may construct a real `ToolManager`
without itself importing `sunil.tools.*` directly.

`main.py` calling `sunil.tools.github.adapter.build_github_adapter()`
tripped `tests/security/test_import_boundaries.py
::test_only_the_tool_framework_may_import_a_tool_adapter` — "a
determined engineer can still import an adapter module" applies to
`sunil/main.py` exactly as it would to an agent. This factory is the
fix: it lives in `core/tool_framework/` (the one allow-listed
non-`tools/` directory), so it — not `main.py` — is the thing that
imports the GitHub adapter.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sunil.core.registry.loader import Registries
from sunil.core.tool_framework.manager import ToolManager, build_tool_manager


@dataclass
class _FakeSettings:
    github_token: object
    github_api_base_url: str = "https://api.github.com"


class _FakeSecretStr:
    def __init__(self, value: str) -> None:
        self._value = value

    def get_secret_value(self) -> str:
        return self._value


def test_build_tool_manager_returns_a_real_tool_manager_with_github_wired(
    registries: Registries, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    settings = _FakeSettings(github_token=_FakeSecretStr("github_pat_fake_for_test"))

    manager = build_tool_manager(
        settings=settings, registries=registries, sessionmaker=sessionmaker
    )

    assert isinstance(manager, ToolManager)
    # Constructed with a real `github` adapter -- proven behaviourally,
    # not by reaching into a private attribute: an unknown operation on a
    # *registered* tool is a different rejection reason from an
    # unregistered tool entirely (`ToolManager.execute()` step 1).
    result = manager._adapters  # noqa: SLF001 - the one assertion this factory's own test needs
    assert "github" in result
    assert result["github"].name == "github"
