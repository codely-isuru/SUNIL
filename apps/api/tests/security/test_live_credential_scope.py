"""T-17 — PAT over-scope. The only test in this suite that needs a real
credential, and therefore the only one marked `live`.

THREAT_MODEL.md T-17 records this as **Mitigated**, with the note
"provisioning is the owner action at Gate 2". Provisioning is not
verification: nothing in M1 checks that the token the owner actually pasted is
the read-only, single-repository token the threat model assumes. Until this
runs, T-17 status is an assumption about a human action.

Deselected by CI (`-m "not live"`, M1_BUILD_PLAN.md section 5 T21) because CI
must never hold a credential. Run it once, by hand, after the owner supplies
the token:

    cd apps/api && python -m pytest tests/security -m live -q

Every assertion is read-only. Nothing here writes to GitHub.
"""

from __future__ import annotations

import os

import httpx
import pytest

pytestmark = pytest.mark.live

API = "https://api.github.com"
EXPECTED_REPO = "codely-isuru/easy_clean_workforce"
# A public repository the token has no business reaching. Reading it proves
# nothing bad by itself; the assertion is about the *permissions* it reports.
UNRELATED_REPO = "octocat/Hello-World"


def _client() -> httpx.Client:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        pytest.fail("GITHUB_TOKEN is not set — cannot verify T-17 without the real token")
    return httpx.Client(
        base_url=API,
        timeout=15,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def test_the_github_token_has_no_write_access_to_the_target_repository() -> None:
    """A repository-scoped *read* token must report push=false, admin=false,
    maintain=false. If any is true, the tool that M1 grants to an agent can
    modify the owner business repository."""
    with _client() as client:
        response = client.get(f"/repos/{EXPECTED_REPO}")
        assert response.status_code == 200, f"cannot read the target repo: {response.status_code}"
        permissions = response.json().get("permissions", {})

    for level in ("push", "admin", "maintain"):
        assert permissions.get(level) is not True, (
            f"GITHUB_TOKEN reports `{level}` on {EXPECTED_REPO} — T-17 claims read-only. "
            f"Full permissions block: {permissions}"
        )
    assert permissions.get("pull") is True, f"token cannot even read: {permissions}"


def test_the_github_token_is_scoped_to_one_repository() -> None:
    """T-17: "A repository-scoped read token cannot write, cannot reach other
    repositories". A fine-grained PAT limited to one repo returns 403/404 when
    asked to enumerate installations beyond it."""
    with _client() as client:
        listed = client.get("/user/repos", params={"per_page": 100})

    if listed.status_code == 200:
        names = {repo["full_name"] for repo in listed.json()}
        beyond = sorted(names - {EXPECTED_REPO})
        assert not beyond, f"the token can enumerate repositories beyond {EXPECTED_REPO}: {beyond}"
    else:
        assert listed.status_code in (401, 403, 404), (
            f"unexpected status enumerating repositories: {listed.status_code}"
        )


def test_the_github_token_is_not_a_classic_scoped_token() -> None:
    """A classic PAT carries `x-oauth-scopes`. A fine-grained PAT does not.
    ADR-006 and .env.example both specify fine-grained; this is the check that
    a classic `repo`-scoped token (which is read *and* write, everywhere) was
    not pasted in by mistake."""
    with _client() as client:
        response = client.get("/rate_limit")

    scopes = response.headers.get("x-oauth-scopes")
    assert not scopes, (
        f"GITHUB_TOKEN looks like a classic PAT with scopes `{scopes}` — .env.example specifies a "
        "fine-grained PAT scoped to one repository with Contents/Pull requests/Issues read only"
    )


def test_the_anthropic_key_is_never_sent_to_github() -> None:
    """T-18 / T-21: the Anthropic key is injected at client construction for
    Anthropic only. This asserts the two credentials have not been crossed in
    configuration — a real mistake, and a silent one."""
    github = os.environ.get("GITHUB_TOKEN", "")
    anthropic = os.environ.get("ANTHROPIC_API_KEY", "")
    assert github and anthropic, "both credentials must be set to run this check"
    assert github != anthropic, "GITHUB_TOKEN and ANTHROPIC_API_KEY hold the same value"
    assert not github.startswith("sk-ant-"), "an Anthropic key is configured as GITHUB_TOKEN"
    assert not anthropic.startswith(("ghp_", "github_pat_")), (
        "a GitHub token is configured as ANTHROPIC_API_KEY"
    )
