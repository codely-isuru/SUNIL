"""`infra/n8n/workflows/*.json` — the workflows as code.

These files are imported into a live n8n by `scripts/n8n-setup.*`, which means
they are the thing a reviewer reads and n8n is the thing that runs. Three
properties have to hold in the FILE, because by the time they are wrong in the
running instance the evidence is in a container's volume:

1. **No token is ever a literal here.** Both bearers are n8n credentials,
   referenced by a placeholder id the setup script substitutes.
2. **The MCP Server Trigger authenticates.** `authentication: "none"` is the
   node's DEFAULT, and it publishes the endpoint to anything that can reach the
   port. This is the file-side half of the evidence in
   `docs/tasks/S2-E-n8n.md` §4.
3. **Every scheduled workflow calls the governed door** — `POST /api/v1/chat`
   on the ADR-035 service lane, and nothing else. n8n supplies the clock, never
   the judgement (ADR-030 §5), and it must never reach SUNIL's database.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[5]
WORKFLOW_DIR = REPO_ROOT / "infra" / "n8n" / "workflows"
WORKFLOW_FILES = sorted(WORKFLOW_DIR.glob("*.json"))

MCP_TRIGGER_TYPE = "@n8n/n8n-nodes-langchain.mcpTrigger"
SCHEDULE_TRIGGER_TYPE = "n8n-nodes-base.scheduleTrigger"
HTTP_TYPE = "n8n-nodes-base.httpRequest"
CHAT_URL_PATH = "/api/v1/chat"

#: The placeholders `scripts/n8n-setup.*` substitutes at import time.
CREDENTIAL_PLACEHOLDERS = {
    "__SUNIL_SERVICE_TOKEN_CREDENTIAL_ID__",
    "__SUNIL_MCP_BEARER_CREDENTIAL_ID__",
}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _nodes_of(document: dict, node_type: str) -> list[dict]:
    return [node for node in document["nodes"] if node["type"] == node_type]


def test_the_export_directory_is_not_empty() -> None:
    """Guards every parametrised test below from passing vacuously."""
    assert len(WORKFLOW_FILES) == 4


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_every_export_is_importable_shaped(path: Path) -> None:
    document = _load(path)

    assert set(document) >= {"name", "nodes", "connections", "settings"}
    assert document["nodes"], "a workflow with no nodes imports and does nothing"
    # The timezone is pinned per workflow, not inherited from the container: a
    # brief that moves an hour on a DST boundary is a bug nobody reports.
    assert document["settings"]["timezone"] == "Australia/Melbourne"


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_workflow_names_are_ascii(path: Path) -> None:
    """The name is the IDENTITY `scripts/n8n-setup.*` matches on to decide
    create-vs-update, and it makes that round trip through a shell.

    Learned the hard way: an em dash in the name came back mangled from Git Bash
    on Windows, the lookup missed, and a re-run created a SECOND copy of every
    workflow — which for the MCP server meant two workflows claiming one webhook
    path and neither of them activating. ASCII names, and this test.
    """
    name = _load(path)["name"]

    assert name.isascii(), f"{name!r} is not ASCII; the setup script matches on it"
    assert name.startswith("SUNIL - ")


@pytest.mark.parametrize("path", WORKFLOW_FILES, ids=lambda p: p.name)
def test_no_export_carries_a_credential_value(path: Path) -> None:
    """Only credential NAMES and placeholder ids — never a token.

    The check is on the raw text rather than on parsed nodes, because a secret
    pasted into a node's `notes`, or into a Code node's body, would be just as
    committed and would not appear under `credentials`.
    """
    text = path.read_text(encoding="utf-8")
    document = _load(path)

    for node in document["nodes"]:
        for credential in (node.get("credentials") or {}).values():
            assert credential["id"] in CREDENTIAL_PLACEHOLDERS, (
                f"{node['name']} references credential id {credential['id']!r}; "
                "an export must carry the placeholder, not an instance's real id"
            )
    for marker in ("Bearer ", "authorization", "Authorization"):
        assert marker not in text, (
            f"{path.name} mentions {marker!r} — the bearer belongs in n8n's "
            "encrypted vault, reached by credential reference"
        )


def test_the_mcp_server_trigger_requires_a_bearer() -> None:
    """THE security assertion, in the file that decides it.

    n8n 2.38.5's MCP Server Trigger defaults to `authentication: "none"`, which
    serves `initialize`, `tools/list` and `tools/call` to any unauthenticated
    caller that can reach the port. It is one dropdown in a browser between the
    governed state and the ungoverned one, and that dropdown is not reviewable —
    this file is.
    """
    document = _load(WORKFLOW_DIR / "sunil-mcp-server.json")
    triggers = _nodes_of(document, MCP_TRIGGER_TYPE)

    assert len(triggers) == 1
    trigger = triggers[0]
    assert trigger["parameters"]["authentication"] == "bearerAuth"
    assert trigger["credentials"]["httpBearerAuth"]["name"] == "SUNIL MCP bearer"
    # Pinned: the node's own version decides the endpoint shape (< 2 splits into
    # /sse + /messages, which is not what SUNIL's streamable-HTTP client speaks).
    assert trigger["typeVersion"] >= 2


def test_the_mcp_server_advertises_exactly_the_configured_operations() -> None:
    """The workflow side of ADR-034's drift check.

    An `ai_tool` node whose name is not an operation in `config/tools.yaml` is
    ignored by SUNIL ("it does not exist"), but a CONFIGURED operation with no
    node behind it takes the entire tool out of the registry at startup. This
    catches the second case in the repository rather than at boot.
    """
    from sunil.core.tool_framework.tools_config import load_tools_config

    document = _load(WORKFLOW_DIR / "sunil-mcp-server.json")
    advertised = {
        node["name"]
        for node in document["nodes"]
        if node["type"] != MCP_TRIGGER_TYPE
    }
    configured = set(
        load_tools_config(REPO_ROOT / "config" / "tools.yaml").tools["n8n_mcp"].operations
    )

    assert configured <= advertised, (
        f"config/tools.yaml declares {sorted(configured - advertised)}, which this "
        "workflow does not publish — the adapter would refuse to start"
    )


SCHEDULED = [p for p in WORKFLOW_FILES if p.name != "sunil-mcp-server.json"]


@pytest.mark.parametrize("path", SCHEDULED, ids=lambda p: p.name)
def test_every_scheduled_workflow_triggers_a_turn_and_nothing_else(path: Path) -> None:
    document = _load(path)

    schedules = _nodes_of(document, SCHEDULE_TRIGGER_TYPE)
    assert len(schedules) == 1
    assert schedules[0]["parameters"]["rule"]["interval"][0]["field"] == "cronExpression"

    posts = _nodes_of(document, HTTP_TYPE)
    assert len(posts) == 1, "one outbound call per scheduled workflow: the turn"
    post = posts[0]
    assert post["parameters"]["method"] == "POST"
    assert post["parameters"]["url"].endswith(CHAT_URL_PATH)
    assert post["parameters"]["genericAuthType"] == "httpBearerAuth"
    assert post["credentials"]["httpBearerAuth"]["name"] == "SUNIL service token"


@pytest.mark.parametrize("path", SCHEDULED, ids=lambda p: p.name)
def test_an_unreachable_api_does_not_make_a_schedule_fail_loudly(path: Path) -> None:
    """SUNIL's API may legitimately be down when a cron fires. The workflow must
    record that and finish, not leave a red execution and a retry storm."""
    post = _nodes_of(_load(path), HTTP_TYPE)[0]

    assert post["onError"] == "continueRegularOutput"
    assert post["alwaysOutputData"] is True
    assert post["retryOnFail"] is True
    assert post["parameters"]["options"]["response"]["response"]["neverError"] is True
    assert post["parameters"]["options"]["timeout"] > 0


@pytest.mark.parametrize("path", SCHEDULED, ids=lambda p: p.name)
def test_every_scheduled_turn_labels_its_channel(path: Path) -> None:
    """ADR-035: the label records WHICH workflow called, and an audit reader
    trusts it — so it is sent on the header the bearer lane reads AND in the
    body, and the two must agree."""
    document = _load(path)
    post = _nodes_of(document, HTTP_TYPE)[0]

    headers = {
        entry["name"]: entry["value"]
        for entry in post["parameters"]["headerParameters"]["parameters"]
    }
    label = headers["X-SUNIL-Channel-Label"]

    assert label.startswith("n8n:")
    assert f'channel_label: "{label}"' in post["parameters"]["jsonBody"]
