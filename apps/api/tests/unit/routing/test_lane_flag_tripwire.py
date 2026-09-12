"""ADR-033 tripwire — the lane flag is readable ONLY by provider registration.

ADR-033's kill switch is **population-scoped**: ``SUNIL_LLM_PROVIDER_LANE``
selects transport wiring at startup and "is readable only by provider
registration; the Model Router's capability/privacy policy runs before provider
selection and cannot see the lane flag — so flipping the lane can never widen
which workloads reach a cloud provider (central-memory lesson 2026-08-17: the
excluded population's decision must not take the mode as input)".

C2 §3 repeats it: "it is not readable by the router (structural — see §2)".

The Security review of the Stream B design asked for this to be MECHANICAL
rather than a promise in a docstring, because "structural" is a property a
future one-line change can quietly delete. These tests are that mechanism, in
three layers of increasing strength:

1. no module under ``sunil/core/routing`` mentions the env var at all;
2. no module under ``sunil/core/routing`` reads the process environment at all
   (``os.environ``/``getenv``/``dotenv``) — the var could otherwise be reached
   under a computed name;
3. importing ``sunil.core.routing`` pulls in NO module that reads the flag, so
   the policy layer cannot reach it transitively either (the import graph, not
   just the source text).

Layer 3 is the one that catches the realistic regression: someone adds
``from sunil.providers.registry import build_provider_registry`` to
``router.py`` for convenience, the source text stays clean, and the lane
becomes an input to policy through a call chain.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

import sunil.core.routing as routing_package
from sunil.core.routing import catalogue, errors, pricing, retry, router

LANE_FLAG = "SUNIL_LLM_PROVIDER_LANE"

#: The modules that ARE allowed to read the flag (ADR-033: provider
#: registration). Anything else reading it is the regression.
LANE_READERS = ("sunil/providers/registry.py",)

#: Source markers for "this module can read the process environment".
#:
#: ``from os import environ`` is here because of the Security wave-1 LOW
#: hardening: every other marker in this tuple is dodged by that one import line
#: (``environ["SUNIL_LLM_PROVIDER_LANE"]`` contains none of "os.environ",
#: "getenv(", "dotenv" or "environb"), and the dodge is the kind a refactor makes
#: by accident rather than by design. A guard with a known hole is a guard that
#: reports success for the case it was written to catch.
ENV_READ_MARKERS = (
    "os.environ",
    "os.getenv",
    "getenv(",
    "dotenv",
    "environb",
    "from os import environ",
)


def routing_dir() -> Path:
    return Path(routing_package.__file__).resolve().parent


def routing_sources() -> list[Path]:
    files = sorted(routing_dir().glob("*.py"))
    assert files, "no modules found under sunil/core/routing — the tripwire is vacuous"
    return files


def test_the_tripwire_has_something_to_guard() -> None:
    """A guard over an empty directory passes forever while proving nothing."""
    names = {path.name for path in routing_sources()}

    assert {"router.py", "retry.py", "catalogue.py", "pricing.py"} <= names


@pytest.mark.parametrize("source", routing_sources(), ids=lambda p: p.name)
def test_no_routing_module_mentions_the_lane_flag(source: Path) -> None:
    text = source.read_text(encoding="utf-8")

    offenders = [
        f"{source.name}:{number}"
        for number, line in enumerate(text.splitlines(), start=1)
        if LANE_FLAG in line and not line.lstrip().startswith("#")
    ]

    assert offenders == [], (
        f"ADR-033: {offenders} name {LANE_FLAG}. The router's capability/privacy "
        "policy must not be able to see the transport lane — move the read into "
        "providers/registry.py, the only module allowed to have it."
    )


@pytest.mark.parametrize("source", routing_sources(), ids=lambda p: p.name)
def test_no_routing_module_reads_the_process_environment_at_all(source: Path) -> None:
    """Stronger than a string match: a module that can read ANY env var can read
    this one under a computed name (``os.environ["SUNIL_LLM_" + suffix]``)."""
    text = source.read_text(encoding="utf-8")
    code = "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )

    found = [marker for marker in ENV_READ_MARKERS if marker in code]

    assert found == [], (
        f"{source.name} reads the process environment ({found}). Routing policy "
        "takes its inputs from config/models.yaml and its constructor only "
        "(M1 law: settings.py is the single env seam; ADR-033: the lane flag is "
        "readable by provider registration alone)."
    )


def test_no_routing_module_imports_a_lane_reader() -> None:
    """Layer 3 — the import GRAPH. Parsed with ``ast`` so a
    ``from sunil.providers.registry import ...`` inside a function body (the
    lazy-import dodge) is caught too."""
    # `sunil.settings` joins the two provider modules here (Security wave-1 LOW
    # hardening). It is the M1 law's single env seam and it carries
    # `sunil_llm_provider_lane` as a typed field, so a routing module importing
    # it reaches the lane flag by attribute access — no `os.environ` anywhere in
    # the source, layer 2 clean, and policy taking transport as an input again.
    forbidden = {"sunil.providers.registry", "sunil.providers.gateway", "sunil.settings"}
    offenders: list[str] = []

    for source in routing_sources():
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                # The MODULE plus each imported name (security residual R-6a).
                # Matching `node.module` alone is dodged by `from sunil import
                # settings`: the module is `sunil`, which is on nobody's
                # forbidden list, while the bound name is the lane-carrying
                # module itself — `settings.sunil_llm_provider_lane` from there,
                # layer 2 clean, tripwire green. Both forms are checked because
                # `from sunil.providers import registry` needs the join and
                # `from sunil.settings import Settings` needs the module.
                names = [node.module or ""]
                names += [
                    f"{node.module}.{alias.name}" if node.module else alias.name
                    for alias in node.names
                ]
            else:
                continue
            for name in names:
                if any(name == bad or name.startswith(f"{bad}.") for bad in forbidden):
                    offenders.append(f"{source.name}:{node.lineno} imports {name}")

    assert offenders == [], (
        f"ADR-033/C2 §3: {offenders}. Routing depends on providers/base.py (the "
        "protocol) and on the ProviderLookup protocol — never on the module that "
        "wires the lane, or the lane becomes an input to policy by call chain."
    )


def test_importing_the_routing_package_never_loads_a_lane_reader() -> None:
    """The runtime proof of the same property, independent of source parsing: a
    fresh import of every routing module must leave the lane-reading modules
    unimported."""
    for module in list(sys.modules):
        if module.startswith("sunil.providers.registry") or module.startswith(
            "sunil.providers.gateway"
        ):
            del sys.modules[module]

    for module in list(sys.modules):
        if module.startswith("sunil.core.routing"):
            del sys.modules[module]

    __import__("sunil.core.routing.router")
    __import__("sunil.core.routing.retry")
    __import__("sunil.core.routing.catalogue")
    __import__("sunil.core.routing.pricing")

    leaked = [
        module
        for module in sys.modules
        if module in ("sunil.providers.registry", "sunil.providers.gateway")
    ]

    assert leaked == [], f"importing routing loaded {leaked}"


def test_the_declared_lane_reader_actually_reads_the_flag() -> None:
    """The counterpart assertion, so the tripwire cannot pass by the flag having
    silently disappeared from the codebase entirely (a guard whose subject no
    longer exists is not a guard)."""
    api_root = routing_dir().parents[2]  # …/apps/api
    readers = [api_root / relative for relative in LANE_READERS]

    for reader in readers:
        assert reader.is_file(), f"{reader} does not exist"

    assert any(
        LANE_FLAG in reader.read_text(encoding="utf-8") for reader in readers
    ), f"{LANE_FLAG} is read nowhere — has the ADR-033 kill switch been dropped?"


def test_the_routing_modules_expose_no_lane_switch_of_their_own() -> None:
    """Belt and braces on the same rule at the API level: no routing symbol is
    named after the lane, so no caller can pass the lane INTO policy either."""
    for module in (router, retry, catalogue, pricing, errors):
        named = [name for name in vars(module) if "lane" in name.lower()]
        assert named == [], f"{module.__name__} exposes lane-shaped symbols: {named}"
