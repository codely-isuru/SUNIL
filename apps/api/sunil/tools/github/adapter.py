"""The GitHub tool adapter — M1's one tool (`ARCHITECTURE_V1.md` §9.3,
§10, FR-101–105).

Three concurrent read-only `httpx` GETs (commits, open PRs, open issues),
projected through `projection.py` before ever being returned as
`ToolResult.data` — no raw GitHub payload is ever handed back to a
caller. **`owner`/`repo` are resolved from `config/projects.yaml` by this
adapter; they never come from the model or the plan** (T-16, ADR-000
Q7) — the operation's only parameter is `project_key`, and
`GitHubListRecentActivityParams` is `extra="forbid"`, so a params dict
carrying `owner`/`repo`/`url`/`host`/... raises rather than being
silently accepted and ignored.

**The external HTTP boundary is injectable** (`client` constructor
parameter) specifically so unit and security tests can fake GitHub's
responses with `httpx.MockTransport` — no real network call, no real
token, ever required to exercise this adapter or prove ET-12's
projection guarantees end to end.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
from pydantic import BaseModel, ConfigDict

from sunil.core.registry.errors import UnknownProjectError
from sunil.core.registry.projects import ProjectRegistry
from sunil.core.tool_framework.base import ToolOperation, ToolResult
from sunil.tools.github.projection import project_recent_activity

_DEFAULT_BASE_URL = "https://api.github.com"
_DEFAULT_TIMEOUT_S = 15.0
_PER_PAGE = 20


class GitHubListRecentActivityParams(BaseModel):
    """The operation's *only* parameter. `extra="forbid"` is what makes
    "no owner/repo/url ever comes from the model" enforceable rather than
    a hopeful docstring — a params dict carrying any of those raises
    `ValidationError` (a `ValueError` subclass) at step 3 of
    `ToolManager.execute()`, before the adapter is ever reached.
    """

    model_config = ConfigDict(extra="forbid")

    project_key: str


def _class_level_handler_placeholder(_: BaseModel) -> Any:
    """Never actually called. `GitHubAdapter.operations` is a class
    attribute so its `params_model` is inspectable without constructing
    an adapter (T19's security suite does exactly this); the *bound*,
    callable handler only exists on an instance — see `__init__`, which
    replaces this placeholder with `self._list_recent_activity`."""
    raise RuntimeError(
        "GitHubAdapter.operations is the class-level, inspection-only view — "
        "construct a GitHubAdapter instance to get an executable handler."
    )


class GitHubAdapter:
    """M1's one `ToolAdapter`. Construct one with the registries and
    credentials it needs; `operations` on the *instance* carries a bound,
    executable handler, while `GitHubAdapter.operations` on the *class*
    stays a static, inspectable view (params model, timeout, read-only
    flag) that does not require an instance to examine.
    """

    name = "github"

    operations: dict[str, ToolOperation] = {
        "list_recent_activity": ToolOperation(
            name="list_recent_activity",
            params_model=GitHubListRecentActivityParams,
            read_only=True,
            timeout_s=_DEFAULT_TIMEOUT_S,
            handler=_class_level_handler_placeholder,
        )
    }

    def __init__(
        self,
        *,
        projects: ProjectRegistry,
        token: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._projects = projects
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
        # Injected for tests (a `httpx.MockTransport`-backed client); left
        # `None` for real use, where a fresh client is opened per call
        # against `self._base_url` (which itself may be overridden by
        # `Settings.github_api_base_url` — see the module docstring on
        # that setting for the pending Architect ruling on gating it).
        self._injected_client = client

        self.operations: dict[str, ToolOperation] = {
            "list_recent_activity": ToolOperation(
                name="list_recent_activity",
                params_model=GitHubListRecentActivityParams,
                read_only=True,
                timeout_s=timeout_s,
                handler=self._list_recent_activity,
            )
        }

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    async def _list_recent_activity(self, params: GitHubListRecentActivityParams) -> ToolResult:
        try:
            project = self._projects.get(params.project_key)
        except UnknownProjectError as exc:
            return ToolResult(
                ok=False, data=None, error_kind="unknown_project", error_message=str(exc)
            )

        owner, repo = project.github.owner, project.github.repo
        client = self._injected_client or httpx.AsyncClient(
            base_url=self._base_url, timeout=self._timeout_s
        )
        owns_client = self._injected_client is None
        try:
            commits_resp, pulls_resp, issues_resp = await asyncio.gather(
                client.get(
                    f"/repos/{owner}/{repo}/commits",
                    params={"per_page": _PER_PAGE},
                    headers=self._headers(),
                ),
                client.get(
                    f"/repos/{owner}/{repo}/pulls",
                    params={"state": "open", "per_page": _PER_PAGE},
                    headers=self._headers(),
                ),
                client.get(
                    f"/repos/{owner}/{repo}/issues",
                    params={"state": "open", "per_page": _PER_PAGE},
                    headers=self._headers(),
                ),
            )
        except httpx.HTTPError as exc:
            return ToolResult(
                ok=False, data=None, error_kind="network_error", error_message=str(exc)
            )
        finally:
            if owns_client:
                await client.aclose()

        for response, name in (
            (commits_resp, "commits"),
            (pulls_resp, "pulls"),
            (issues_resp, "issues"),
        ):
            error = _check_github_response(response, name)
            if error is not None:
                return error

        projected = project_recent_activity(
            {
                "commits": commits_resp.json(),
                "pulls": pulls_resp.json(),
                "issues": issues_resp.json(),
            }
        )
        return ToolResult(ok=True, data=projected, error_kind=None, error_message=None)


def _check_github_response(response: httpx.Response, name: str) -> ToolResult | None:
    """`None` if the response is usable; a failure `ToolResult` otherwise.
    Rate-limit exhaustion (T-20) gets its own `error_kind` because it maps
    to the Designer's own copy (`M1_CHAT_SPEC.md` §5.7), distinct from a
    generic GitHub API error."""
    if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
        return ToolResult(
            ok=False,
            data=None,
            error_kind="rate_limited",
            error_message=f"GitHub rate limit exceeded fetching {name}",
        )
    if response.status_code >= 400:
        return ToolResult(
            ok=False,
            data=None,
            error_kind="github_api_error",
            error_message=f"{name}: GitHub returned HTTP {response.status_code}",
        )
    return None


def build_github_adapter(*, settings: Any, projects: ProjectRegistry) -> GitHubAdapter:
    """Construct the real, network-facing adapter from process settings.

    Kept generic over `settings: Any` (matching `sunil.redaction`'s own
    pattern) so this module has no import-time dependency on
    `sunil.settings` — whoever wires the Tool Manager (T10/T11b) calls
    this once at startup with the live `Settings` instance.
    """
    return GitHubAdapter(
        projects=projects,
        token=settings.github_token.get_secret_value(),
        base_url=settings.github_api_base_url,
    )
