"""LIVE checks on the owner's `GITHUB_TOKEN` (opt-in, skipped by default).

T-17 in `docs/THREAT_MODEL.md` rates PAT over-scope **Mitigated** on the
strength of "provisioning is the owner's action". The 2026-08-19 M1 worklog
already recorded the objection this file answers: *provisioning is not
verification*. These tests are that verification, and they run only when

    SUNIL_LIVE_GITHUB_TEST=1

is set **and** a token is present, so CI and every other stream are unaffected.

Run them (PowerShell, from the repo root):

    $env:SUNIL_LIVE_GITHUB_TEST = '1'
    $env:GITHUB_TOKEN = (Select-String '^GITHUB_TOKEN=' .env).Line.Split('=',2)[1]
    python -m pytest apps/api/tests/unit/tools/test_github_token_posture_live.py -v

=========================================================================
SECRET DISCIPLINE — the rule that produced these tests' odd-looking shape
=========================================================================
M1 had to revoke and rotate a credential because four assertions in the file
whose purpose was proving secrets never leak used a raw credential **as an
assertion operand** — and pytest prints operands when an assertion fails. So:
every predicate about the token is reduced to a `bool` BEFORE it reaches
`assert`, and no test ever interpolates the token into a message. Statuses,
header names and repository names are the only things that appear.

=========================================================================
WHY THERE IS NO "ATTEMPT A WRITE" TEST
=========================================================================
Every GitHub GET is gated by a *read* permission, so no GET can demonstrate the
absence of write access (M1's lesson: `permissions` on `GET /repos/{o}/{r}`
reports the USER's role, not the token's, and read `admin: True` for a token
that got 403 elsewhere — a check that could never have falsified T-17). The
probes below are **write-class but incapable of mutating anything**: a `PATCH`
of a ref that does not exist and a merge of two branches that do not exist.
Success is impossible for any token, so only the authorisation verdict varies.
"""

from __future__ import annotations

import os

import httpx
import pytest

#: The only repository `config/projects.yaml` gives the native tool.
OWNER = "codely-isuru"
REPO = "SUNIL"

#: A repository the token must NOT be able to reach (T-17 containment).
OFF_LIMITS = "codely-isuru/easy_clean_workforce"

BASE_URL = os.environ.get("GITHUB_API_BASE_URL", "https://api.github.com")

live = pytest.mark.skipif(
    os.environ.get("SUNIL_LIVE_GITHUB_TEST") != "1",
    reason="live GitHub posture check is opt-in: set SUNIL_LIVE_GITHUB_TEST=1 "
    "with a GITHUB_TOKEN in the environment",
)


def token() -> str:
    value = os.environ.get("GITHUB_TOKEN")
    if not value:
        pytest.skip("GITHUB_TOKEN is not set in this environment")
    return value


def headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token()}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def client() -> httpx.Client:
    # `follow_redirects=False` for the ADR-017 reason the adapter states: a
    # redirect would forward `Authorization: Bearer <PAT>` to whoever issued it.
    return httpx.Client(base_url=BASE_URL, timeout=30.0, follow_redirects=False)


@live
def test_the_token_is_accepted_by_github_at_all() -> None:
    """`GET /rate_limit` is satisfied by ANY valid credential, including one with
    no repository permissions whatsoever. A 401 here therefore separates
    "expired/revoked/invalid" from "valid but under-scoped" — which no
    repository endpoint can do on its own.

    This test is the precondition for every other test in this file; when it
    fails, the rest are meaningless rather than merely red.
    """
    with client() as http:
        response = http.get("/rate_limit", headers=headers())

    assert response.status_code == 200, (
        "GitHub rejected the credential outright (HTTP "
        f"{response.status_code}). The token is expired, revoked or invalid — "
        "T-17 cannot be verified until it is replaced. See docs/SECRETS_SETUP.md."
    )


@live
def test_the_token_can_read_the_one_repository_it_is_for() -> None:
    """The read half of T-17: the tool's only reachable repository is readable."""
    with client() as http:
        response = http.get(
            f"/repos/{OWNER}/{REPO}/commits", params={"per_page": 1}, headers=headers()
        )

    assert response.status_code == 200


@live
@pytest.mark.parametrize(
    ("label", "method", "path", "body"),
    [
        (
            "patch-nonexistent-ref",
            "PATCH",
            f"/repos/{OWNER}/{REPO}/git/refs/heads/sunil-t17-probe-does-not-exist",
            {"sha": "0" * 40},
        ),
        (
            "merge-nonexistent-branches",
            "POST",
            f"/repos/{OWNER}/{REPO}/merges",
            {
                "base": "sunil-t17-probe-does-not-exist",
                "head": "sunil-t17-probe-also-does-not-exist",
            },
        ),
    ],
)
def test_a_write_class_call_is_refused(
    label: str, method: str, path: str, body: dict[str, object]
) -> None:
    """A read-only token must be refused on the *authorisation* check, before
    GitHub ever considers whether the target exists.

    403 is the pass: "Resource not accessible by personal access token".
    404/422 would mean the token got PAST authorisation and was stopped only by
    the target being absent — i.e. it holds write access it must not have.
    Neither probe can mutate anything: the ref and both branches do not exist.
    """
    with client() as http:
        response = http.request(method, path, json=body, headers=headers())

    assert response.status_code == 403, (
        f"write-class probe {label!r} returned HTTP {response.status_code}; "
        "403 is required. 404/422 means the token passed the authorisation "
        "check and holds write access that T-17 forbids."
    )


@live
def test_the_token_cannot_reach_another_repository() -> None:
    """T-17's containment claim: repository-scoped means one repository."""
    with client() as http:
        response = http.get(f"/repos/{OFF_LIMITS}", headers=headers())

    # 404 is how GitHub hides a repository a fine-grained token cannot see; a
    # 403 would also be a refusal. A 200 is the failure this test exists for.
    assert response.status_code in (403, 404), (
        f"the token could read {OFF_LIMITS} (HTTP {response.status_code}); "
        "T-17 requires it to be scoped to a single repository."
    )


@live
def test_the_token_is_not_a_classic_pat() -> None:
    """A classic PAT is account-wide and cannot satisfy T-17 no matter which
    boxes were ticked, so its mere shape is a failure.

    Detection uses GitHub's own answer: `x-oauth-scopes` is returned for classic
    tokens (even when the scope list is empty) and omitted for fine-grained
    ones. The prefix is a corroborating signal only, and is reduced to a `bool`
    here so the token can never become an assertion operand.
    """
    with client() as http:
        response = http.get("/rate_limit", headers=headers())

    if response.status_code != 200:
        pytest.skip(
            "credential rejected (HTTP "
            f"{response.status_code}); token class is indeterminate because "
            "GitHub sends no x-oauth-scopes header on a rejection"
        )

    looks_classic_by_header = "x-oauth-scopes" in response.headers
    looks_classic_by_prefix = bool(token().startswith("ghp_"))

    assert not looks_classic_by_header, (
        "GitHub returned an x-oauth-scopes header, which it sends only for "
        "CLASSIC tokens. A classic PAT is account-wide and cannot satisfy T-17."
    )
    assert not looks_classic_by_prefix
