"""`github_mcp.merge_main` — R16 part 3's bounded composition.

The capture (`docs/tasks/S3-github.md` §0) settled the question empirically: of
the 45 tools the official server advertises, **not one merges a branch into
another branch**. `merge_pull_request` is the only merge and it takes a PR
number. So the composition is not a workaround and not even a fallback — it is
the only executable shape, and R16 ruled its governance:

* **ONE** governed operation, **ONE** permission row, **ONE** approval binding —
  exactly `{project_key, branch, base_branch}`, the fields of `MergeMainParams`
  and nothing else;
* the PR number is **derived state minted inside the approved execution** — it
  comes out of step 1's own result, is never a plan input, and is never a field
  of any params model;
* `owner`/`repo` come from `config/projects.yaml` (M1's T-16 rule), never from
  the plan;
* both bound tools are drift-checked (that pin lives in
  `test_mcp_server_tool_bindings.py` and in the recorded-handshake module).

The failure shape matters as much as the success shape: if step 1 fails, step 2
must never run, and the operation must report `upstream_error` rather than
raising — because step 2 is the ONLY thing that merges, a half-done merge is not
representable.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from sunil.core.tool_framework.base import AdapterKind, ToolErrorKind
from sunil.tools.mcp.adapter import McpToolAdapter
from sunil.tools.mcp.config import McpOperationConfig
from sunil.tools.mcp.params import MergeMainParams
from sunil.tools.mcp.protocol import MCP_PROTOCOL_VERSION, McpServerError

PROJECT_REPOS = {"sunil": ("codely-isuru", "SUNIL")}

MERGE_MAIN = McpOperationConfig(
    name="merge_main",
    params_model=MergeMainParams,
    read_only=False,
    timeout_s=30,
    server_tools=("create_pull_request", "merge_pull_request"),
    composition="merge_via_pull_request",
)


def _text_content(payload: dict[str, Any]) -> dict[str, Any]:
    """The shape the official server returns: the API object as JSON in a text
    content block (this is how the capture's own tool results are framed)."""
    return {"content": [{"type": "text", "text": json.dumps(payload)}]}


class _FakeGitHubServer:
    def __init__(self, *, pr_number: int = 7, create_fails: bool = False) -> None:
        self.calls: list[dict[str, Any]] = []
        self._pr_number = pr_number
        self._create_fails = create_fails

    async def open(self) -> None: ...

    async def close(self) -> None: ...

    async def notify(self, method: str, params: dict[str, Any]) -> None: ...

    async def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if method == "initialize":
            return {"protocolVersion": MCP_PROTOCOL_VERSION}
        if method == "tools/list":
            return {
                "tools": [
                    {"name": "create_pull_request"},
                    {"name": "merge_pull_request"},
                ]
            }
        assert method == "tools/call"
        self.calls.append(params)
        if params["name"] == "create_pull_request":
            if self._create_fails:
                raise McpServerError("422 Validation Failed: No commits between main and feat")
            return _text_content({"number": self._pr_number, "html_url": "https://x/pull/7"})
        return _text_content({"merged": True, "sha": "deadbeef"})


async def _started(server: _FakeGitHubServer) -> McpToolAdapter:
    adapter = McpToolAdapter(
        server_id="github_mcp",
        kind=AdapterKind.MCP_STDIO,
        operations={"merge_main": MERGE_MAIN},
        transport=server,
        project_repos=PROJECT_REPOS,
    )
    await adapter.start()
    return adapter


async def test_merge_main_opens_a_pull_request_then_merges_the_number_it_minted() -> None:
    server = _FakeGitHubServer(pr_number=7)
    adapter = await _started(server)

    result = await adapter.operations["merge_main"].handler(
        MergeMainParams(project_key="sunil", branch="feat/x", base_branch="main")
    )

    assert result.ok is True
    assert [call["name"] for call in server.calls] == [
        "create_pull_request",
        "merge_pull_request",
    ]
    created = server.calls[0]["arguments"]
    assert created["owner"] == "codely-isuru"
    assert created["repo"] == "SUNIL"
    assert created["head"] == "feat/x"
    assert created["base"] == "main"
    merged = server.calls[1]["arguments"]
    assert merged == {
        "owner": "codely-isuru",
        "repo": "SUNIL",
        "pullNumber": 7,
    }


async def test_the_pr_number_comes_from_step_ones_result_not_from_the_plan() -> None:
    """Derived state, minted inside the approved execution. A different server
    reply must produce a different merge target with the SAME approved args."""
    server = _FakeGitHubServer(pr_number=1234)
    adapter = await _started(server)

    await adapter.operations["merge_main"].handler(
        MergeMainParams(project_key="sunil", branch="feat/x", base_branch="main")
    )

    assert server.calls[1]["arguments"]["pullNumber"] == 1234
    # And it is reachable through no params model — the approval binds 3 fields.
    assert set(MergeMainParams.model_fields) == {"project_key", "branch", "base_branch"}
    assert "pull" not in " ".join(MergeMainParams.model_fields)


async def test_a_failed_pull_request_never_reaches_the_merge_call() -> None:
    server = _FakeGitHubServer(create_fails=True)
    adapter = await _started(server)

    result = await adapter.operations["merge_main"].handler(
        MergeMainParams(project_key="sunil", branch="feat/x", base_branch="main")
    )

    assert result.ok is False
    assert result.error_kind == ToolErrorKind.UPSTREAM_ERROR.value
    assert [call["name"] for call in server.calls] == ["create_pull_request"]


async def test_an_unknown_project_key_fails_the_call_and_reaches_no_server_tool() -> None:
    """`project_key` is validated against `config/projects.yaml` by the plan
    validator, but the adapter must not depend on that: the repo mapping is the
    thing that stops a plan choosing which repository SUNIL writes to."""
    server = _FakeGitHubServer()
    adapter = await _started(server)

    result = await adapter.operations["merge_main"].handler(
        MergeMainParams(project_key="not-a-project", branch="feat/x", base_branch="main")
    )

    assert result.ok is False
    assert result.error_kind == ToolErrorKind.UPSTREAM_ERROR.value
    assert server.calls == []


async def test_a_composition_cannot_call_a_tool_the_drift_check_never_verified() -> None:
    """The composition executor reaches the wire only through
    `call_server_tool`, which refuses any name outside this adapter's bindings —
    so a future composition cannot quietly acquire an unchecked verb."""
    server = _FakeGitHubServer()
    adapter = await _started(server)

    with pytest.raises(Exception) as caught:
        await adapter.call_server_tool("delete_file", {"path": "x"})

    assert "delete_file" in str(caught.value)
    assert server.calls == []


def test_the_composition_refuses_a_binding_it_cannot_execute() -> None:
    """Config chooses WHICH composition; the composition declares which server
    tools it needs. A `server_tool:` list that does not match is a startup
    refusal, not a call-time surprise."""
    from sunil.tools.mcp.compositions import CompositionError, resolve_composition

    wrong = McpOperationConfig(
        name="merge_main",
        params_model=MergeMainParams,
        read_only=False,
        timeout_s=30,
        server_tools=("merge_pull_request",),  # missing create_pull_request
        composition="merge_via_pull_request",
    )

    with pytest.raises(CompositionError):
        resolve_composition("merge_via_pull_request", wrong, server_id="github_mcp")


def test_an_unknown_composition_name_is_refused() -> None:
    from sunil.tools.mcp.compositions import CompositionError, resolve_composition

    with pytest.raises(CompositionError):
        resolve_composition("merge_by_magic", MERGE_MAIN, server_id="github_mcp")
