"""Params models for the configured MCP operations — SUNIL's schema, not the
server's.

ADR-034 decision 4: "SUNIL validates against its own ``params_model``
(``extra="forbid"``, C1 step 2) *before* the permission check; the server will
validate again against its schema. Disagreement is an ``upstream_error``,
surfaced — never auto-reconciled."

That is why these models exist at all rather than being generated from the
server's ``inputSchema``: a generated model would make the thing being governed
the author of its own validation, and a server update could widen what SUNIL
accepts without anyone reviewing it. Each model is referenced by
``params_ref:`` from ``config/tools.yaml``, and the loader refuses any model
that is not ``extra="forbid"``.

Bounds are deliberately tight. These values travel into third-party writes, and
the ``args_hash`` an approval binds to is computed over exactly this validated
shape — so "the owner approved closing issue 42" means issue 42 and nothing
else.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class IssuesListParams(BaseModel, extra="forbid"):
    """``github_mcp.issues_list`` — read-only."""

    owner: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
    repo: str = Field(pattern=r"^[A-Za-z0-9._-]{1,100}$")
    state: str = Field(default="open", pattern=r"^(open|closed|all)$")


class IssuesCloseParams(BaseModel, extra="forbid"):
    """``github_mcp.issues_close`` — a WRITE to a third party, granted
    ``ask_user`` (ARCHITECTURE_V2 §6's worked example)."""

    owner: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}$")
    repo: str = Field(pattern=r"^[A-Za-z0-9._-]{1,100}$")
    issue_number: int = Field(ge=1)


class RunWorkflowParams(BaseModel, extra="forbid"):
    """``n8n_mcp.run_workflow`` — triggers an n8n workflow (TB5).

    ``payload`` is a free-form dict because a workflow's inputs are the
    workflow's business; it is still a plan literal validated before the
    permission decision, and it is what the ``args_hash`` covers, so an approval
    cannot be re-spent on a different payload.
    """

    workflow_id: str = Field(min_length=1, max_length=128)
    payload: dict = Field(default_factory=dict)


#: The branch charset, identical to ``agents/developer/agent.py``'s ``_BRANCH_RE``
#: and deliberately so: the agent validates a branch before it builds these
#: arguments, and a params model that admitted MORE than the agent does would be
#: the gap a second caller walks through. Conservative by construction — must
#: start alphanumeric, and nothing a shell or a git refspec reads as syntax
#: (``--upload-pack=...`` is an argument, not a ref).
_BRANCH_PATTERN = r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,119}$"
#: `config/projects.yaml`'s key space (M1's T-16 rule: a plan names a project,
#: never a repository or a URL). The REPOSITORY is resolved from the registry by
#: the wiring code, which is why no model here has an `owner`/`repo`/`url` field.
_PROJECT_KEY_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"


class PushBranchParams(BaseModel, extra="forbid"):
    """``github_mcp.push_branch`` — ADR-030 §4's `allow` row.

    Granted unattended, and narrow enough to deserve it: it pushes the
    developer agent's OWN work branch. `base_branch` is carried because the push
    is meaningful only against the branch the work was cut from, and because the
    `args_hash` a later `merge_main` approval binds to must cover the same three
    values (`docs/tasks/S2-F-openhands.md` §2).

    Nothing here is copied from the execution engine's reply: the agent builds
    all three fields from values it validated itself (control 3). `extra="forbid"`
    is what stops a fourth field — a remote, a token, a force flag — riding along.
    """

    project_key: str = Field(pattern=_PROJECT_KEY_PATTERN)
    branch: str = Field(pattern=_BRANCH_PATTERN)
    base_branch: str = Field(pattern=_BRANCH_PATTERN)


class MergeMainParams(BaseModel, extra="forbid"):
    """``github_mcp.merge_main`` — ADR-030 §4's `ask_user` row.

    Same three fields as the push, on purpose: this is the operation an owner
    reads on the approval card, and "merge THAT branch into THAT base of THAT
    project" is the whole question. Identical shape also means the pair cannot
    drift into an approval that binds different arguments from the write.
    """

    project_key: str = Field(pattern=_PROJECT_KEY_PATTERN)
    branch: str = Field(pattern=_BRANCH_PATTERN)
    base_branch: str = Field(pattern=_BRANCH_PATTERN)


class PostUpdateParams(BaseModel, extra="forbid"):
    """``n8n_mcp.post_update`` — the one governed action the Stream E MCP Server
    Trigger workflow exposes (``infra/n8n/workflows/mcp-server.json``).

    Tight where ``run_workflow`` is loose, and deliberately so: this operation's
    arguments are what an owner reads on the approval card before deciding, so
    they are two named, bounded fields rather than a free-form ``payload``. The
    ``args_hash`` covers exactly this shape — "the owner approved posting THAT
    summary against THAT project" — and ``extra="forbid"`` is what stops a plan
    smuggling a third key past the value the approval binds to.
    """

    #: The same key space as ``config/projects.yaml`` (M1's T-16 rule: a plan
    #: names a project, never a repository or a URL).
    project_key: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    summary: str = Field(min_length=1, max_length=2000)
