"""`sunil.tools.github.adapter.GitHubAdapter` — M1's one tool.

Every test here fakes the HTTP boundary with `httpx.MockTransport` — no
network call, no real token, ever (`docs/M1_BUILD_PLAN.md` §3 T8's own
"Watch"; the Security Reviewer's requirement that the adapter's external
boundary be fakeable).
"""

from __future__ import annotations

import httpx
import pytest
from pydantic import ValidationError
from sunil.core.registry.projects import GithubCoordinates, ProjectDefinition, ProjectRegistry
from sunil.tools.github.adapter import GitHubAdapter, GitHubListRecentActivityParams


def _project_registry() -> ProjectRegistry:
    return ProjectRegistry(
        {
            "sample_project": ProjectDefinition(
                key="sample_project",
                display_name="Sample Project",
                github=GithubCoordinates(owner="sample-owner", repo="sample-repo"),
            )
        }
    )


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://fake.test")


# ---------------------------------------------------------------------------
# T-16 / ADR-000 Q7 — repo coordinates never come from the model.
# ---------------------------------------------------------------------------


def test_params_model_forbids_owner_repo_and_other_repo_coordinate_fields() -> None:
    params_model = GitHubAdapter.operations["list_recent_activity"].params_model
    fields = set(params_model.model_fields)

    forbidden = {"owner", "repo", "url", "base_url", "host", "full_name", "endpoint"}
    assert not (fields & forbidden)
    assert "project_key" in fields

    with pytest.raises(ValidationError):
        params_model(project_key="sample_project", owner="attacker", repo="evil")


def test_operations_is_inspectable_on_the_class_without_an_instance() -> None:
    """T19's security suite reads `GitHubAdapter.operations[...]` directly
    off the class — this must not require constructing an adapter."""
    op = GitHubAdapter.operations["list_recent_activity"]

    assert op.params_model is GitHubListRecentActivityParams
    assert op.read_only is True


async def test_owner_and_repo_are_resolved_from_the_project_registry_not_from_params() -> None:
    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if request.url.path.endswith("/issues"):
            return httpx.Response(200, json=[])
        return httpx.Response(200, json=[])

    adapter = GitHubAdapter(
        projects=_project_registry(), token="fake-test-token", client=_mock_client(handler)
    )

    result = await adapter.operations["list_recent_activity"].handler(
        GitHubListRecentActivityParams(project_key="sample_project")
    )

    assert result.ok is True
    assert any("/repos/sample-owner/sample-repo/commits" in p for p in seen_paths)
    assert any("/repos/sample-owner/sample-repo/pulls" in p for p in seen_paths)
    assert any("/repos/sample-owner/sample-repo/issues" in p for p in seen_paths)


async def test_unknown_project_key_is_a_normalised_failure_not_an_exception() -> None:
    adapter = GitHubAdapter(
        projects=_project_registry(),
        token="fake-test-token",
        client=_mock_client(lambda r: httpx.Response(200, json=[])),
    )

    result = await adapter.operations["list_recent_activity"].handler(
        GitHubListRecentActivityParams(project_key="no_such_project")
    )

    assert result.ok is False
    assert result.error_kind == "unknown_project"


async def test_the_authorization_header_carries_a_bearer_token_never_query_string() -> None:
    seen_headers: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_headers.append(dict(request.headers))
        return httpx.Response(200, json=[])

    adapter = GitHubAdapter(
        projects=_project_registry(),
        token="fake-test-token-value",
        client=_mock_client(handler),
    )

    await adapter.operations["list_recent_activity"].handler(
        GitHubListRecentActivityParams(project_key="sample_project")
    )

    assert seen_headers, "no request was made"
    for headers in seen_headers:
        assert headers.get("authorization") == "Bearer fake-test-token-value"
        assert headers.get("accept") == "application/vnd.github+json"
        assert headers.get("x-github-api-version") == "2022-11-28"


async def test_a_rate_limited_response_maps_to_the_named_error_kind() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, headers={"x-ratelimit-remaining": "0"}, json={})

    adapter = GitHubAdapter(
        projects=_project_registry(), token="fake-test-token", client=_mock_client(handler)
    )

    result = await adapter.operations["list_recent_activity"].handler(
        GitHubListRecentActivityParams(project_key="sample_project")
    )

    assert result.ok is False
    assert result.error_kind == "rate_limited"


async def test_a_generic_github_error_response_is_normalised() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "internal error"})

    adapter = GitHubAdapter(
        projects=_project_registry(), token="fake-test-token", client=_mock_client(handler)
    )

    result = await adapter.operations["list_recent_activity"].handler(
        GitHubListRecentActivityParams(project_key="sample_project")
    )

    assert result.ok is False
    assert result.error_kind == "github_api_error"


async def test_a_successful_call_returns_only_projected_data_never_the_raw_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/commits"):
            return httpx.Response(
                200,
                json=[
                    {
                        "sha": "0123456789abcdef0123456789abcdef01234567",
                        "commit": {"message": "fix", "author": {"date": "2026-08-13T00:00:00Z"}},
                        "author": {"login": "bot"},
                        "html_url": "https://github.com/o/r/commit/0123456",
                    }
                ],
            )
        if request.url.path.endswith("/pulls"):
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 1,
                        "title": "t",
                        "body": "SECRET-BODY-MUST-NOT-SURVIVE",
                        "user": {"login": "u", "email": "u@example.com"},
                        "created_at": "c",
                        "updated_at": "u",
                        "draft": False,
                    }
                ],
            )
        return httpx.Response(200, json=[])

    adapter = GitHubAdapter(
        projects=_project_registry(), token="fake-test-token", client=_mock_client(handler)
    )

    result = await adapter.operations["list_recent_activity"].handler(
        GitHubListRecentActivityParams(project_key="sample_project")
    )

    assert result.ok is True
    flat = str(result.data)
    assert "SECRET-BODY-MUST-NOT-SURVIVE" not in flat
    assert "html_url" not in flat
    assert "email" not in flat


async def test_a_network_error_is_normalised_never_propagated() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    adapter = GitHubAdapter(
        projects=_project_registry(), token="fake-test-token", client=_mock_client(handler)
    )

    result = await adapter.operations["list_recent_activity"].handler(
        GitHubListRecentActivityParams(project_key="sample_project")
    )

    assert result.ok is False
    assert result.error_kind == "network_error"


def test_build_github_adapter_reads_the_base_url_from_settings() -> None:
    from sunil.tools.github.adapter import build_github_adapter

    class _FakeSecretStr:
        def get_secret_value(self) -> str:
            return "fake-token-from-settings"

    class _FakeSettings:
        github_token = _FakeSecretStr()
        github_api_base_url = "https://fake-configured-host.test"

    adapter = build_github_adapter(settings=_FakeSettings(), projects=_project_registry())

    assert adapter._base_url == "https://fake-configured-host.test"  # noqa: SLF001 - white-box
