"""The import law, as a tripwire (ARCHITECTURE_V2 §2).

> **`core/` never imports `sunil.api`**; `providers/`, `tools/`,
> `memory_providers/` never import `core/orchestrator`.

§2 says the law is "re-enforced by a tripwire test"; this is it. Both halves are
architecture, not taste:

* If `core/` may import `sunil.api`, the orchestrator ends up returning the wire
  envelope, and a change to a frozen HTTP contract reaches into the turn engine.
  That is why `core.orchestrator.result.TurnResult` exists and `api/envelope.py`
  maps it.
* If an adapter may import `core/orchestrator`, a vendor integration can call the
  turn engine — the cycle that lets tool output start work, which is precisely
  the path ROADMAP §25 exists to keep closed.

The check is a source scan rather than an import-time probe on purpose: a module
that is merely *importable* without cycling can still carry the dependency, and
the law is about the dependency.
"""

from __future__ import annotations

import ast
from pathlib import Path

SUNIL_ROOT = Path(__file__).resolve().parents[2] / "sunil"


def _imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.add(node.module)
    return modules


def _offenders(package: str, forbidden_prefix: str) -> list[str]:
    found: list[str] = []
    for path in sorted((SUNIL_ROOT / package).rglob("*.py")):
        for module in _imported_modules(path):
            if module == forbidden_prefix or module.startswith(forbidden_prefix + "."):
                found.append(f"{path.relative_to(SUNIL_ROOT)} imports {module}")
    return found


def test_core_never_imports_the_api_layer() -> None:
    assert _offenders("core", "sunil.api") == []


def test_agents_never_import_the_api_layer() -> None:
    """Same law, same reason: an agent that can reach the HTTP layer can shape a
    response without going through the turn's envelope builder."""
    assert _offenders("agents", "sunil.api") == []


def test_adapters_never_import_the_orchestrator() -> None:
    for package in ("providers", "tools", "memory_providers"):
        if not (SUNIL_ROOT / package).is_dir():
            continue  # Streams A/B/C have not landed their package yet
        assert _offenders(package, "sunil.core.orchestrator") == []


def test_the_scan_can_actually_see_imports() -> None:
    """The tripwire's own tripwire: a scan that silently parsed nothing would
    make every assertion above vacuous."""
    modules = _imported_modules(SUNIL_ROOT / "core" / "orchestrator" / "turn.py")

    assert "sunil.core.trace.stages" in modules
