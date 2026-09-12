"""The native GitHub tool — three concurrent read-only GETs, projected.

Ported from M1 (`main:apps/api/sunil/tools/github/adapter.py`) with exactly the
changes V2's contract forces, each named:

* **C1 §4's closed error set.** M1 invented ``unknown_project``,
  ``github_api_error``, ``rate_limited`` and ``network_error``; C1 §4 is closed,
  and the orchestrator branches on ``error_kind`` only. So: an unknown project
  key is ``invalid_params`` (it IS a bad parameter — the one parameter this
  operation has), an HTTP error or an exhausted rate limit is ``upstream_error``
  (reached and failed, not auto-retried), and a connection failure is
  ``transport_error`` (the one kind policy may retry). The human detail M1
  carried in its kinds survives in ``error_message``.
* **``ToolResultMeta``** on every result (``NATIVE``, ``server_id=None``).
* **Lifecycle.** C1 §2 adds ``start``/``stop``; for a native adapter both are
  no-ops, which is the whole point of the addition.
* **Project resolution** takes a plain ``Mapping[str, tuple[owner, repo]]``
  rather than M1's ``ProjectRegistry``. ``config/projects.yaml`` and its loader
  belong to the spine lane, and this adapter only needs the mapping — so the
  wiring code resolves it once and hands it down, and this module stays
  loadable in a worktree where ``core/registry`` does not exist yet.

Unchanged, because it is the reason the tool is safe: **``owner``/``repo`` are
resolved from SUNIL config and NEVER come from the model or the plan** (M1's
T-16, ADR-000 Q7). The operation's only parameter is ``project_key``, and
``GitHubListRecentActivityParams`` is ``extra="forbid"``, so a params dict
carrying ``owner``/``repo``/``url``/``host`` is rejected at C1 step 2 — before
this adapter is ever reached. No raw GitHub payload is ever returned:
``ToolResult.data`` is always ``projection.project_recent_activity``'s output.

The HTTP boundary is injectable (``client``) exactly as in M1, so the unit
tests drive it with ``httpx.MockTransport`` — no network, no token, ever.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict

from sunil.core.tool_framework.base import (
    AdapterKind,
    ToolErrorKind,
    ToolOperation,
    ToolResult,
    ToolResultMeta,
)
from sunil.tools.github.projection import project_recent_activity

_DEFAULT_BASE_URL = "https://api.github.com"
_DEFAULT_TIMEOUT_S = 15.0
_PER_PAGE = 20


class GitHubListRecentActivityParams(BaseModel):
    """The operation's *only* parameter (M1's T-16, ported verbatim)."""

    model_config = ConfigDict(extra="forbid")

    project_key: str


class GitHubAdapter:
    """C1 §2 ``ToolAdapter``, ``kind=NATIVE``.

    Not inheriting the protocol (the fakes-build F2 lesson): an inherited
    ``Protocol`` would give this class ``None``-returning bodies for anything it
    forgot. The unit test holds the annotated witness instead.
    """

    def __init__(
        self,
        *,
        projects: Mapping[str, tuple[str, str]],
        token: str,
        base_url: str = _DEFAULT_BASE_URL,
        timeout_s: float = _DEFAULT_TIMEOUT_S,
        client: Any | None = None,
    ) -> None:
        self.name = "github"
        self.kind = AdapterKind.NATIVE
        self._projects = dict(projects)
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._timeout_s = timeout_s
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

    # -- lifecycle (C1 §2: NATIVE adapters are no-ops) ---------------------- #
    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    # -- operations --------------------------------------------------------- #
    async def _list_recent_activity(
        self, params: GitHubListRecentActivityParams
    ) -> ToolResult:
        import httpx  # noqa: PLC0415 - lazy: only the network lane needs httpx

        started = time.monotonic()
        resolved = self._projects.get(params.project_key)
        if resolved is None:
            return self._error(
                ToolErrorKind.INVALID_PARAMS,
                f"unknown project_key {params.project_key!r}",
                started,
            )
        owner, repo = resolved

        client = self._injected_client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=self._timeout_s,
            # ADR-017, ported: a redirected base would send
            # `Authorization: Bearer <PAT>` onward to whoever issued the
            # redirect. Stated explicitly so it stays a decision.
            follow_redirects=False,
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
            # Never `str(exc)`: httpx puts the failing REQUEST in some error
            # messages, and this request carries a bearer token.
            return self._error(
                ToolErrorKind.TRANSPORT_ERROR,
                f"could not reach the GitHub API ({type(exc).__name__})",
                started,
            )
        finally:
            if owns_client:
                await client.aclose()

        for response, name in (
            (commits_resp, "commits"),
            (pulls_resp, "pulls"),
            (issues_resp, "issues"),
        ):
            message = _response_failure(response, name)
            if message is not None:
                return self._error(ToolErrorKind.UPSTREAM_ERROR, message, started)

        projected = project_recent_activity(
            {
                "commits": commits_resp.json(),
                "pulls": pulls_resp.json(),
                "issues": issues_resp.json(),
            }
        )
        return ToolResult(
            ok=True,
            data=projected,
            error_kind=None,
            error_message=None,
            meta=self._meta(started),
        )

    # -- internals ---------------------------------------------------------- #
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _error(self, kind: ToolErrorKind, message: str, started: float) -> ToolResult:
        return ToolResult(
            ok=False,
            data=None,
            error_kind=kind.value,
            error_message=message,
            meta=self._meta(started),
        )

    def _meta(self, started: float) -> ToolResultMeta:
        return ToolResultMeta(
            adapter_kind=AdapterKind.NATIVE,
            server_id=None,  # C1 §2: None for NATIVE
            duration_ms=int((time.monotonic() - started) * 1000),
        )


def _response_failure(response: Any, name: str) -> str | None:
    """``None`` if the response is usable; an ``upstream_error`` message
    otherwise. Rate-limit exhaustion keeps its own WORDING (M1's T-20, because
    the Designer's copy depends on it) under C1 §4's kind."""
    if response.status_code == 403 and response.headers.get("x-ratelimit-remaining") == "0":
        return f"GitHub rate limit exceeded fetching {name}"
    if response.status_code >= 400:
        return f"{name}: GitHub returned HTTP {response.status_code}"
    return None


def build_github_adapter(
    *, settings: Any, projects: Mapping[str, tuple[str, str]]
) -> GitHubAdapter:
    """The one place wiring obtains a real, network-facing GitHub adapter.

    Kept generic over ``settings: Any`` (M1's own pattern) so this module has no
    import-time dependency on ``sunil.settings`` — which, in this lane's
    timeline, does not exist yet.
    """
    return GitHubAdapter(
        projects=projects,
        token=settings.github_token.get_secret_value(),
        base_url=getattr(settings, "github_api_base_url", _DEFAULT_BASE_URL),
    )
