"""Stream B's runtime imports must be DECLARED runtime dependencies.

Why this test exists (and why it is not paranoia): the C2 adapters are built on
``httpx`` "no SDKs", and ``ModelCatalogue.load`` parses ``config/models.yaml``
with ``pyyaml``. Neither was in ``[project.dependencies]`` when Stream B's
modules landed — they resolved locally only because this workstation happens to
have both installed. CI installs exactly ``pip install -e ".[dev]"``, and a
production install takes no extras at all, so an undeclared runtime import is a
``ModuleNotFoundError`` at the first gateway call rather than a red test.

The check walks the AST rather than the text so that *lazy* imports (the ones
inside a function body, like ``catalogue.load``'s ``import yaml``) are caught
too — those are precisely the ones that never fail at import time and so hide
from a smoke test.
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest

FIRST_PARTY = {"sunil", "tests"}

# The modules Stream B owns. Scoped deliberately: this test speaks for its own
# stream and must not fail because some other stream's file is mid-flight.
STREAM_B_SOURCES = ("sunil/providers", "sunil/core/routing")


def api_root() -> Path:
    """``apps/api`` — the directory holding ``pyproject.toml``."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file():
            return parent
    raise AssertionError("apps/api/pyproject.toml not found above this test")


def stream_b_modules() -> list[Path]:
    root = api_root()
    files = [
        path
        for source_dir in STREAM_B_SOURCES
        for path in sorted((root / source_dir).rglob("*.py"))
    ]
    assert files, "no Stream B modules found — this test would pass vacuously"
    return files


def top_level_imports(source: Path) -> set[str]:
    """Every top-level module name imported by ``source``, at module scope or
    lazily inside a function."""
    tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            # ``level > 0`` is a relative import — first-party by construction.
            if node.level == 0 and node.module:
                names.add(node.module.split(".")[0])
    return names


def declared_runtime_distributions() -> set[str]:
    """The distribution names in ``[project.dependencies]`` only — extras are
    explicitly NOT counted, because a runtime import satisfied by a dev extra is
    the bug this test is about."""
    pyproject = tomllib.loads(
        (api_root() / "pyproject.toml").read_text(encoding="utf-8")
    )
    requirements = pyproject["project"]["dependencies"]
    names = set()
    for requirement in requirements:
        match = re.match(r"^\s*([A-Za-z0-9._-]+)", requirement)
        assert match, f"cannot parse requirement {requirement!r}"
        names.add(canonical(match.group(1)))
    return names


def canonical(name: str) -> str:
    """PEP 503 normalisation, so ``PyYAML``/``pyyaml`` compare equal."""
    return re.sub(r"[-_.]+", "-", name).lower()


# The import name a distribution provides, where the two differ.
IMPORT_TO_DISTRIBUTION = {"yaml": "pyyaml"}


@pytest.mark.parametrize("source", stream_b_modules(), ids=lambda p: p.name)
def test_every_third_party_import_is_a_declared_runtime_dependency(
    source: Path,
) -> None:
    declared = declared_runtime_distributions()
    undeclared = sorted(
        name
        for name in top_level_imports(source)
        if name not in sys.stdlib_module_names
        and name not in FIRST_PARTY
        and canonical(IMPORT_TO_DISTRIBUTION.get(name, name)) not in declared
    )

    assert undeclared == [], (
        f"{source.relative_to(api_root())} imports {undeclared}, which "
        f"[project.dependencies] does not declare (declared: {sorted(declared)}). "
        "CI installs '.[dev]' and production installs no extras, so this is a "
        "ModuleNotFoundError at the first call, not a test failure."
    )
