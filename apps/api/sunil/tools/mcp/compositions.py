"""Bounded compositions — ONE governed operation, more than one server tool.

ADR-034 Amendment 1 (ruling R16 part 3). A composition exists for exactly one
reason: the governed operation an owner consents to has no single tool behind it.
`github_mcp.merge_main` is the case that forced it — the 2026-09-16 capture of
`github/github-mcp-server` v1.12.2 found 45 advertised tools and **no branch
merge among them** (`docs/tasks/S3-github.md` §0). The honest executable shape is
`create_pull_request(branch → base)` then `merge_pull_request(number)`.

R16's constraints, which this module exists to hold:

* **ONE approval binding**, exactly `{project_key, branch, base_branch}`. The
  approval card, the `args_hash` and the audit row see the governed operation and
  its three validated arguments — never the intermediate call.
* **The PR number is DERIVED STATE.** It is minted inside the approved execution
  from step 1's own result. It is not a plan input, it is not a field of any
  params model, and there is no code path by which a plan can choose it.
* **Both bound tools are drift-checked** at startup (`adapter._drift_check`), so
  a composition that could start but not finish does not exist: if
  `merge_pull_request` were unadvertised the WHOLE tool would leave the registry
  rather than open a PR it cannot merge.
* **A composition reaches the wire only through `adapter.call_server_tool`**,
  which refuses any name outside the operation's bindings. A composition cannot
  acquire a verb the drift check never verified.

Why CODE and not configuration: `wiring._native()`'s reason, unchanged — "native
tools are CODE, not configuration". Deriving a number from one call's result and
feeding it to the next is logic, and logic expressed as YAML is logic nobody
reviews. Config names WHICH composition; the composition declares which server
tools it needs; a mismatch is a startup refusal.
"""

from __future__ import annotations

import json
from typing import Any, Awaitable, Callable, Protocol

from pydantic import BaseModel

from sunil.tools.mcp.config import McpOperationConfig


class CompositionError(Exception):
    """A composition could not be resolved, or could not complete.

    Surfaced by the adapter as ``upstream_error`` — the same closed-set value a
    single failed ``tools/call`` produces (C1 §4), because from the plan's point
    of view "the write did not happen" is the same fact either way.
    """


#: What a composition is handed to reach the wire: the adapter's own
#: `call_server_tool`, already bound-checked.
CallServerTool = Callable[[str, dict[str, Any]], Awaitable[Any]]


class Composition(Protocol):
    """The seam. Stateless: one instance per configured operation, resolved at
    adapter construction so a bad binding fails before any call."""

    required_server_tools: tuple[str, ...]

    async def execute(
        self, params: BaseModel, *, call: CallServerTool, context: "CompositionContext"
    ) -> Any: ...


class CompositionContext:
    """The non-plan facts a composition may read.

    Today that is the `config/projects.yaml` repo mapping, and it is here rather
    than in the params model for M1's T-16 reason, ported with the native GitHub
    adapter: **a plan names a project, never a repository**. `MergeMainParams`
    therefore has no `owner`/`repo`/`url` field, and there is no way for a plan to
    choose which repository SUNIL writes to.
    """

    def __init__(self, *, project_repos: dict[str, tuple[str, str]] | None = None) -> None:
        self._project_repos = dict(project_repos or {})

    def repo_for(self, project_key: str) -> tuple[str, str]:
        try:
            return self._project_repos[project_key]
        except KeyError:
            raise CompositionError(
                f"project {project_key!r} declares no `repo: owner/name` in "
                "config/projects.yaml, so there is no repository to act on (M1 T-16: "
                "the repo mapping is config, never a plan parameter)"
            ) from None


def _api_object(payload: Any) -> dict[str, Any]:
    """The GitHub API object out of an MCP tool result.

    The official server frames its JSON in a text content block. Parsed here and
    NOT sanitised: C1 §3's cap and strip are the chokepoint's job (manager step
    7), so this is only the number we need to finish our own operation, read and
    discarded. Nothing from this payload reaches a model through this path.
    """
    if isinstance(payload, dict) and isinstance(payload.get("structuredContent"), dict):
        return payload["structuredContent"]
    content = payload.get("content") if isinstance(payload, dict) else None
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and isinstance(block.get("text"), str):
                try:
                    parsed = json.loads(block["text"])
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    return parsed
    raise CompositionError(
        "the server's reply carried no JSON object where one was required "
        "(ADR-034 decision 4: disagreement with the server is surfaced, never "
        "auto-reconciled)"
    )


class MergeViaPullRequest:
    """`merge_main` = `create_pull_request` then `merge_pull_request`.

    R16: "not a workaround, an upgrade" — the owner's C4 decision now leaves a
    server-side reviewable PR trail instead of a silent fast-forward.
    """

    required_server_tools = ("create_pull_request", "merge_pull_request")

    async def execute(
        self, params: BaseModel, *, call: CallServerTool, context: CompositionContext
    ) -> Any:
        branch = getattr(params, "branch")
        base_branch = getattr(params, "base_branch")
        owner, repo = context.repo_for(getattr(params, "project_key"))

        created = _api_object(
            await call(
                "create_pull_request",
                {
                    "owner": owner,
                    "repo": repo,
                    "title": f"SUNIL: merge {branch} into {base_branch}",
                    "head": branch,
                    "base": base_branch,
                    # The owner approved a merge, not a review request: a draft PR
                    # is unmergeable, so opening one would turn an approved
                    # operation into a silent no-op.
                    "draft": False,
                },
            )
        )
        number = created.get("number")
        if not isinstance(number, int) or isinstance(number, bool) or number < 1:
            raise CompositionError(
                "create_pull_request returned no usable pull-request number, so there is "
                "nothing to merge — refusing to guess one"
            )

        merged = await call(
            "merge_pull_request", {"owner": owner, "repo": repo, "pullNumber": number}
        )
        # Both halves are returned: the audit row and the owner-facing result
        # should show the PR that was opened, not only that something merged.
        return {"pull_request": created, "merge": merged}


#: Name → composition. A frozen code constant for the same reason
#: `GRANTABLE_CREDENTIAL_NAMES` is one: a control that config can widen is not a
#: control. A new composition is a reviewed code change.
COMPOSITIONS: dict[str, type] = {"merge_via_pull_request": MergeViaPullRequest}


def resolve_composition(
    name: str | None, operation: McpOperationConfig, *, server_id: str
) -> Composition:
    """Config's `composition:` → the instance, or a startup refusal.

    The binding check is the point: `server_tool:` in config and
    `required_server_tools` in code must agree EXACTLY, so the tools the drift
    check verifies are precisely the tools the executor will call — neither more
    (an unverified verb) nor fewer (a drift check passing over a call that will
    still happen).
    """
    factory = COMPOSITIONS.get(name or "")
    if factory is None:
        raise CompositionError(
            f"{server_id}.{operation.name}: no composition named {name!r} is implemented "
            f"(known: {sorted(COMPOSITIONS)}). A composition is code, not configuration"
        )
    composition = factory()
    if tuple(operation.server_tools) != tuple(composition.required_server_tools):
        raise CompositionError(
            f"{server_id}.{operation.name}: composition {name!r} executes "
            f"{list(composition.required_server_tools)} but config binds "
            f"{list(operation.server_tools)} — the drift check must verify exactly the "
            "tools the executor calls (ADR-034 Amendment 1)"
        )
    return composition
