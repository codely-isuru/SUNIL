"""The transcription pin — R16 parcel step 0's capture, replayed.

`fixtures/github_mcp_server_v1_12_2.json` is a VERBATIM recording of the
`initialize` and `tools/list` responses of the official
`github/github-mcp-server`, digest `sha256:508a0857…`, booted on Docker stdio
with a scoped token on 2026-09-16 (`docs/tasks/S3-github.md` §0 carries the
capture and the verdict).

R16 made this recording the gate: "boot the candidate, capture `tools/list`
verbatim into the task file, transcribe it into the config comment **and pin it
in a test**". This is that test, built on the Stream E `n8n_2_38_5_mcp.json`
pattern — replay through the REAL `McpToolAdapter`, the REAL ADR-034 drift check
and the REAL binding resolution, with the operations loaded from the
REPOSITORY's own `config/tools.yaml`. So CI proves the shape of the server SUNIL
will actually meet, rather than the shape a hand-written double agrees with
itself about.

What a recording cannot prove is that the live server still answers this way.
That is what the startup drift check is for, and it runs against the live server
on every boot.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from sunil.core.tool_framework.base import AdapterKind, ToolAdapterStartupError
from sunil.core.tool_framework.tools_config import load_tools_config
from sunil.tools.mcp.adapter import McpToolAdapter
from sunil.tools.mcp.protocol import MCP_PROTOCOL_VERSION

REPO_ROOT = Path(__file__).resolve().parents[5]
CAPTURE = json.loads(
    (Path(__file__).parent / "fixtures" / "github_mcp_server_v1_12_2.json").read_text(
        encoding="utf-8"
    )
)
ADVERTISED: dict[str, dict[str, Any]] = {
    tool["name"]: tool for tool in CAPTURE["tools_list"]["result"]["tools"]
}

#: Every tool the capture advertised, transcribed. Asserted as a WHOLE SET: a
#: fixture refreshed against a newer image that quietly dropped a bound verb —
#: which is exactly what happened to `update_issue` between 0.6.2 and v1.12.2 —
#: must trip here, where the diff is readable, and not at 3am in a drift check.
CAPTURED_TOOL_NAMES = {
    "add_comment_to_pending_review", "add_issue_comment",
    "add_reply_to_pull_request_comment", "assign_copilot_to_issue",
    "create_branch", "create_or_update_file", "create_pull_request",
    "create_repository", "delete_file", "fork_repository", "get_commit",
    "get_file_contents", "get_label", "get_latest_release", "get_me",
    "get_release_by_tag", "get_tag", "get_team_members", "get_teams",
    "issue_read", "issue_write", "list_branches", "list_commits",
    "list_issue_fields", "list_issue_types", "list_issues",
    "list_pull_requests", "list_releases", "list_repository_collaborators",
    "list_tags", "merge_pull_request", "pull_request_read",
    "pull_request_review_write", "push_files", "request_copilot_review",
    "search_code", "search_commits", "search_issues", "search_pull_requests",
    "search_repositories", "search_users", "sub_issue_write",
    "update_issue_comment", "update_pull_request", "update_pull_request_branch",
}


class _RecordedServer:
    """Replays the captured handshake, then answers `tools/call` from a script."""

    def __init__(self, *, drop: set[str] | None = None, results: dict | None = None) -> None:
        self._drop = drop or set()
        self._results = results or {}
        self.calls: list[dict[str, Any]] = []

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def notify(self, method: str, params: dict[str, Any]) -> None: ...

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return CAPTURE["initialize"]["result"]
        if method == "tools/list":
            return {
                "tools": [
                    tool
                    for tool in CAPTURE["tools_list"]["result"]["tools"]
                    if tool["name"] not in self._drop
                ]
            }
        assert method == "tools/call"
        self.calls.append(params)
        return self._results.get(params["name"], {"content": []})


def _adapter(server: _RecordedServer) -> McpToolAdapter:
    """Built from the REPOSITORY's own block — so this test fails if
    `config/tools.yaml` ever binds an operation to a verb the captured server
    does not advertise, which is exactly what the live drift check would do."""
    block = load_tools_config(REPO_ROOT / "config" / "tools.yaml").tools["github_mcp"]
    return McpToolAdapter(
        server_id="github_mcp",
        kind=AdapterKind.MCP_STDIO,
        operations=block.operations,
        transport=server,
        project_repos={"sunil": ("codely-isuru", "SUNIL")},
    )


def test_the_capture_is_the_artefact_the_config_pins() -> None:
    """Provenance. The fixture must be the image `config/tools.yaml` spawns —
    a recording of some OTHER build proves nothing about this pin."""
    command = " ".join(
        load_tools_config(REPO_ROOT / "config" / "tools.yaml").tools["github_mcp"].command or ()
    )

    assert CAPTURE["image"] in command
    assert "@sha256:" in CAPTURE["image"]
    assert CAPTURE["initialize"]["result"]["serverInfo"]["version"] == "v1.12.2"


def test_the_captured_tools_list_is_transcribed_whole() -> None:
    assert set(ADVERTISED) == CAPTURED_TOOL_NAMES
    assert len(ADVERTISED) == 45


def test_the_captured_server_speaks_the_protocol_revision_sunil_pins() -> None:
    assert CAPTURE["initialize"]["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION


def test_r16s_expected_binding_for_issues_close_is_falsified_by_the_capture() -> None:
    """The finding, pinned so it cannot quietly un-happen. R16 part 2 expected
    `update_issue`; v1.12.2 has no such tool — issue create and update were
    consolidated into `issue_write(method=…)`. SUNIL's operation name did not
    move, which is the naming law's entire point."""
    assert "update_issue" not in ADVERTISED
    assert "issue_write" in ADVERTISED
    schema = ADVERTISED["issue_write"]["inputSchema"]
    assert "update" in schema["properties"]["method"]["enum"]
    assert "closed" in schema["properties"]["state"]["enum"]


def test_no_advertised_tool_merges_a_branch_into_a_branch() -> None:
    """R16 part 3's premise, measured rather than assumed: `merge_pull_request`
    is the ONLY merge the server has, and it takes a PR number. That is why
    `merge_main` is a composition — the alternative does not exist."""
    merges = {name for name in ADVERTISED if "merge" in name}

    assert merges == {"merge_pull_request"}
    required = ADVERTISED["merge_pull_request"]["inputSchema"]["required"]
    assert "pullNumber" in required


def test_push_files_is_still_not_a_branch_push() -> None:
    """R16 part 4's finding, re-confirmed on the NEW server: it is an API
    content-commit taking file contents, not a push of commits that exist only
    in the OpenHands sandbox. `push_branch` stays dormant."""
    required = set(ADVERTISED["push_files"]["inputSchema"]["required"])

    assert "files" in required
    assert load_tools_config(REPO_ROOT / "config" / "tools.yaml").tools[
        "github_mcp"
    ].operations.keys() == {"issues_list", "issues_close", "merge_main"}


async def test_every_configured_binding_survives_the_drift_check() -> None:
    """The whole gate in one assertion: the repository's bindings against the
    captured advertisement, through the real `start()`."""
    await _adapter(_RecordedServer()).start()  # raises ToolAdapterStartupError on drift


@pytest.mark.parametrize(
    "dropped", ["list_issues", "issue_write", "create_pull_request", "merge_pull_request"]
)
async def test_dropping_any_one_bound_verb_takes_the_whole_tool_out(dropped: str) -> None:
    """ADR-034's fail-closed consequence, including for BOTH halves of the
    composition (R16 part 3: "the drift check verifies BOTH bound tools"). A
    server that could open a PR but not merge it must not start at all."""
    with pytest.raises(ToolAdapterStartupError) as caught:
        await _adapter(_RecordedServer(drop={dropped})).start()

    assert dropped in str(caught.value)


async def test_issues_close_goes_out_as_issue_write_with_the_fixed_arguments() -> None:
    """End to end over the recorded handshake: SUNIL's governed name in, the
    vendor's verb out, and the two constants a plan cannot supply."""
    server = _RecordedServer()
    adapter = _adapter(server)
    await adapter.start()

    operation = adapter.operations["issues_close"]
    result = await operation.handler(
        operation.params_model(owner="codely-isuru", repo="SUNIL", issue_number=42)
    )

    assert result.ok is True
    assert server.calls[0]["name"] == "issue_write"
    assert server.calls[0]["arguments"] == {
        "owner": "codely-isuru",
        "repo": "SUNIL",
        "issue_number": 42,
        "method": "update",
        "state": "closed",
    }


async def test_merge_main_composes_over_the_recorded_server() -> None:
    server = _RecordedServer(
        results={
            "create_pull_request": {
                "content": [{"type": "text", "text": json.dumps({"number": 11})}]
            },
            "merge_pull_request": {
                "content": [{"type": "text", "text": json.dumps({"merged": True})}]
            },
        }
    )
    adapter = _adapter(server)
    await adapter.start()

    operation = adapter.operations["merge_main"]
    result = await operation.handler(
        operation.params_model(project_key="sunil", branch="feat/x", base_branch="main")
    )

    assert result.ok is True
    assert [call["name"] for call in server.calls] == [
        "create_pull_request",
        "merge_pull_request",
    ]
    assert server.calls[1]["arguments"]["pullNumber"] == 11


def test_the_capture_carries_no_credential() -> None:
    """The fixture is committed evidence. The token it was captured with must
    not be in it — nor any obvious credential shape."""
    raw = (Path(__file__).parent / "fixtures" / "github_mcp_server_v1_12_2.json").read_text(
        encoding="utf-8"
    )

    for marker in ("ghp_", "github_pat_", "gho_", "Bearer "):
        assert marker not in raw
