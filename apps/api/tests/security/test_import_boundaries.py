"""DC-10 — import boundaries, as AST walks rather than lint configuration.

`THREAT_MODEL.md` DC-10 and T-10 make these rules the mechanised half of
NFR-002 ("tool calls pass through controlled adapters"). They are AST tests,
not `ruff` config, so that no lane has to edit `pyproject.toml` to add one
(`M1_BUILD_PLAN.md` §5 T19) and so the failure message names the offending
file and line.

T-10's own status is **Partial** precisely "until T19 lands". These tests are
what closes it.
"""

from __future__ import annotations

import ast
import pathlib

import pytest
from security_helpers import REPO_ROOT, SUNIL_PKG, require_dir


def _python_files() -> list[pathlib.Path]:
    return sorted(p for p in SUNIL_PKG.rglob("*.py") if "__pycache__" not in p.parts)


def _imported_modules(path: pathlib.Path) -> set[tuple[str, int]]:
    """Every module name imported by `path`, with the line number."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[tuple[str, int]] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add((alias.name, node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import — resolve against the package
                parts = path.relative_to(SUNIL_PKG.parent).with_suffix("").parts
                base = parts[: len(parts) - node.level]
                module = ".".join((*base, node.module)) if node.module else ".".join(base)
            else:
                module = node.module or ""
            found.add((module, node.lineno))
            for alias in node.names:
                found.add((f"{module}.{alias.name}", node.lineno))
    return found


def _rel(path: pathlib.Path) -> str:
    return str(path.relative_to(REPO_ROOT)).replace("\\", "/")


def _violations(*, forbidden_prefixes: tuple[str, ...], allowed_dirs: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for path in _python_files():
        rel = _rel(path)
        if any(rel.startswith(f"apps/api/sunil/{d}") for d in allowed_dirs):
            continue
        for module, lineno in _imported_modules(path):
            if any(module == p or module.startswith(f"{p}.") for p in forbidden_prefixes):
                out.append(f"{rel}:{lineno} imports `{module}`")
    return sorted(out)


def test_only_providers_may_import_a_vendor_sdk() -> None:
    """FR-040's own acceptance criterion, and ADR-003's whole point: swapping
    a provider must never require touching an agent. `sunil/providers/` is the
    only package permitted to know Anthropic exists."""
    require_dir(SUNIL_PKG / "providers", "T6 (provider interface + Anthropic adapter)")
    bad = _violations(forbidden_prefixes=("anthropic", "openai"), allowed_dirs=("providers/",))
    assert not bad, "vendor SDK imported outside sunil/providers/:\n  " + "\n  ".join(bad)


def test_only_the_tool_framework_may_import_a_tool_adapter() -> None:
    """T-10: 'a determined engineer can still import an adapter module',
    bypassing the permission engine entirely. This is the rule that closes it."""
    require_dir(SUNIL_PKG / "tools", "T8 (tool framework + GitHub adapter)")
    require_dir(SUNIL_PKG / "core" / "tool_framework", "T8")
    bad = _violations(
        forbidden_prefixes=("sunil.tools",),
        allowed_dirs=("core/tool_framework/", "tools/"),
    )
    assert not bad, (
        "a tool adapter is imported outside sunil/core/tool_framework/ — every one of these "
        "reaches an external system without passing the permission engine:\n  " + "\n  ".join(bad)
    )


def test_core_never_imports_the_api_layer() -> None:
    """ARCHITECTURE_V1.md §3.1 and sunil/core/__init__.py's own docstring: the
    orchestrator is called from an HTTP route today and from M10's scheduler
    later, so it must not be coupled to a `Request`."""
    require_dir(SUNIL_PKG / "api", "T5 (API skeleton)")
    bad = [
        v
        for v in _violations(forbidden_prefixes=("sunil.api",), allowed_dirs=("api/",))
        if v.startswith("apps/api/sunil/core/")
    ]
    assert not bad, "sunil/core imported sunil.api:\n  " + "\n  ".join(bad)


def test_only_settings_reads_the_process_environment() -> None:
    """`sunil/settings.py` lines 8-10 state this rule outright: "No other module
    should call `os.environ` / `os.getenv` directly." A stated rule with no
    mechanism is a claim; this is the mechanism.

    Runs green today over the eight files that exist, and gets stronger with
    every file that lands."""
    bad: list[str] = []
    for path in _python_files():
        rel = _rel(path)
        if rel.endswith("sunil/settings.py"):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {"environ", "getenv"}:
                value = node.value
                if isinstance(value, ast.Name) and value.id == "os":
                    bad.append(f"{rel}:{node.lineno} uses os.{node.attr}")
    assert not bad, (
        "configuration must be read in exactly one place (sunil/settings.py):\n  "
        + "\n  ".join(sorted(bad))
    )


def test_agents_never_unwrap_a_secret() -> None:
    """NFR-007 / ARCHITECTURE_V1.md §10.1: `AgentContext` exposes exactly
    `call_tool`, `ask_model`, `memory`, `trace` — "no DB session, no HTTP
    client, no secrets". An agent calling `.get_secret_value()` has left that
    envelope regardless of what its context object offers."""
    require_dir(SUNIL_PKG / "agents", "T10 (agent framework + Project Manager)")
    bad: list[str] = []
    allowed = ("providers/", "tools/", "db/", "api/", "settings.py", "redaction.py")
    for path in _python_files():
        rel = _rel(path)
        if any(rel.startswith(f"apps/api/sunil/{a}") or rel.endswith(a) for a in allowed):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "get_secret_value":
                bad.append(f"{rel}:{node.lineno} unwraps a SecretStr")
    assert not bad, "a secret is unwrapped outside its point of use:\n  " + "\n  ".join(sorted(bad))


@pytest.mark.parametrize(
    "rule",
    [
        "only sunil/providers/ imports a vendor SDK",
        "only sunil/core/tool_framework/ imports sunil.tools.*",
        "sunil/core/ never imports sunil.api",
    ],
)
def test_dc10_rules_are_all_covered(rule: str) -> None:
    """DC-10 names exactly three rules. This asserts none is quietly dropped
    from this file — deleting a boundary test must show up as a deletion."""
    covered = {
        "only sunil/providers/ imports a vendor SDK": test_only_providers_may_import_a_vendor_sdk,
        "only sunil/core/tool_framework/ imports sunil.tools.*": (
            test_only_the_tool_framework_may_import_a_tool_adapter
        ),
        "sunil/core/ never imports sunil.api": test_core_never_imports_the_api_layer,
    }
    assert callable(covered[rule])
