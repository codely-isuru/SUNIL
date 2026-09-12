"""The committed environment template, pinned against the code that reads it.

`.env.example` and the commented `api` service in `infra/docker-compose.yml`
are the two places a value is written for somebody else's machine. Nothing
imports them, so nothing catches them drifting — and in the W2R2 integration
round three streams edited `.env.example` and two named URLs in it that no test
covered. These are the checks that make that drift visible:

* the n8n MCP URL carries the WORKFLOW PATH, on both the host and the
  in-network side (Stream E ran the real endpoint: `/mcp` is a prefix and
  answers 404 — `docs/tasks/S2-E-n8n.md` §7.1);
* both values still satisfy ADR-033's named-host validator, asserted through
  the real `Settings` rather than by eye;
* the template has no duplicate keys (the merge artefact three concurrent
  editors produce) and covers every `Settings` field.

The `Settings` coverage check is the one that grows on its own: a new field with
no template row is a variable a deployment cannot set without reading the source.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from sunil.settings import Settings

REPO_ROOT = Path(__file__).resolve().parents[4]
ENV_EXAMPLE = REPO_ROOT / ".env.example"
COMPOSE = REPO_ROOT / "infra" / "docker-compose.yml"

#: Settings fields deliberately absent from `.env.example`, each with the reason
#: the template itself states. The upstream provider credentials and their base
#: URLs are scoped to the LiteLLM container (`infra/.env.litellm.example`) so the
#: application process never holds an upstream key (ADR-030 Section 2); putting a
#: row for them in the app template is what would invite one into this file.
TEMPLATE_EXEMPT_FIELDS = frozenset(
    {
        "anthropic_api_key",
        "openai_api_key",
        "anthropic_base_url",
        "openai_base_url",
    }
)

_ASSIGNMENT = re.compile(r"^([A-Z][A-Z0-9_]*)=")

REQUIRED = {"session_secret": "unit-test-session-secret"}


def _env_example_keys() -> list[str]:
    return [
        m.group(1)
        for m in (_ASSIGNMENT.match(line) for line in ENV_EXAMPLE.read_text("utf-8").splitlines())
        if m
    ]


def env_example_value(key: str) -> str:
    for line in ENV_EXAMPLE.read_text("utf-8").splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    raise AssertionError(f"{key} is absent from .env.example")


def compose_api_stub_value(key: str) -> str:
    """The value from the COMMENTED `api` service block.

    Read as text on purpose: the block is commented out, so `docker compose
    config` never resolves it and the CI platform gate cannot see it. It is
    still the line an operator uncomments, so it is still worth pinning.
    """
    pattern = re.compile(rf"^\s*#\s*{re.escape(key)}:\s*(\S+)")
    for line in COMPOSE.read_text("utf-8").splitlines():
        found = pattern.match(line)
        if found:
            return found.group(1)
    raise AssertionError(f"{key} is absent from the commented api service block")


def build(**overrides: object) -> Settings:
    return Settings(_env_file=None, **{**REQUIRED, **overrides})  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# The n8n MCP endpoint carries the workflow path (Stream E, S2-E-n8n.md 7.1)
# --------------------------------------------------------------------------- #
def test_the_host_side_n8n_mcp_url_names_the_workflow_path() -> None:
    """`/mcp` is n8n's PREFIX, not an endpoint: the MCP Server Trigger is served
    at its own path and the bare prefix answers 404. Proved against the live
    2.38.5 server in `docs/tasks/S2-E-n8n.md` Sections 3-4."""
    value = env_example_value("SUNIL_N8N_MCP_BASE_URL")

    assert value == "http://localhost:5680/mcp/sunil"


def test_the_in_network_n8n_mcp_url_names_the_same_workflow_path() -> None:
    """The container-side twin. Same path, service name and internal port —
    mixing the two halves is the failure the compose comment warns about."""
    assert compose_api_stub_value("SUNIL_N8N_MCP_BASE_URL") == "http://n8n:5678/mcp/sunil"


def test_both_committed_n8n_urls_still_satisfy_the_adr_033_validator() -> None:
    """The path changed; the egress rule did not. Asserted through the real
    validator, because "it is still loopback" is exactly the kind of claim that
    is true until a URL is edited."""
    for url in (
        env_example_value("SUNIL_N8N_MCP_BASE_URL"),
        compose_api_stub_value("SUNIL_N8N_MCP_BASE_URL"),
    ):
        assert build(sunil_n8n_mcp_base_url=url).sunil_n8n_mcp_base_url == url


# --------------------------------------------------------------------------- #
# Template hygiene
# --------------------------------------------------------------------------- #
def test_the_template_assigns_every_key_exactly_once() -> None:
    """Two lanes appending the same key to one template is a silent
    last-one-wins: dotenv keeps the LAST assignment, so the value a reviewer
    reads at the top is not the value the process gets."""
    keys = _env_example_keys()

    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    assert duplicates == []


def test_every_settings_field_has_a_row_in_the_template() -> None:
    """A field with no template row is settable only by someone reading
    `settings.py` — which is how a seam ships configured one way in code and
    another way on every machine that copied the template."""
    present = {key.lower() for key in _env_example_keys()}

    missing = sorted(set(Settings.model_fields) - present - TEMPLATE_EXEMPT_FIELDS)
    assert missing == []


@pytest.mark.parametrize("field", sorted(TEMPLATE_EXEMPT_FIELDS))
def test_the_exempt_fields_are_really_absent(field: str) -> None:
    """The exemption list must not become a place stale names accumulate: if one
    of these ever gains a template row, this test says so rather than letting
    the coverage check silently stop covering it."""
    assert field.upper() not in _env_example_keys()
