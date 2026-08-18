"""T-17 / T-18 — the real credentials' scope. The only tests here that need a
live secret, and therefore the only ones marked `live`.

**This file leaked a credential once. Read this before editing it.**

The first version asserted on raw values:

    assert github and anthropic, "both credentials must be set to run this check"

pytest rewrites assertions to render the *operands* of a failing assert. When
`ANTHROPIC_API_KEY` became optional (T25) and the owner correctly removed it,
that assertion failed and printed the live GitHub token. A test written to
prove secrets never leak leaked one. The token was revoked and rotated.

The rule this file now follows, structurally rather than by care:

**A raw secret is never bound to a local, never an operand of an `assert`,
never interpolated into a message, and never passed to `pytest.fail()`.**

Values stay inside `SecretStr` — whose `repr` is `**********` — and are
unwrapped only inside the small predicate helpers below, which return `bool`
or `int`. So even a future assertion written carelessly renders a mask rather
than a credential. Every assertion in this file compares a boolean, a length
or a status code.

Two supporting rules:

- **Missing credential skips, never fails.** These are `live`-marked; a
  credential that is absent (and `ANTHROPIC_API_KEY` is now legitimately
  optional) is "not applicable", not "broken". A failing test is what pulls a
  value into the output in the first place.
- **Values are read through `Settings`, the way the application reads them**
  — from `.env` at the repo root. Nothing exports these into the process
  environment, which is why the earlier `os.environ` version could not see a
  credential that was demonstrably present, and failed for that reason.

Deselected by CI (`-m "not live"`); CI must never hold a credential. Run by
hand, deliberately:

    cd apps/api && python -m pytest tests/security -m live -q

Every request below is read-only. Nothing here writes to GitHub.
"""

from __future__ import annotations

import os

import httpx
import pytest
from pydantic import SecretStr

pytestmark = pytest.mark.live

API_TIMEOUT_S = 15.0
EXPECTED_REPO = "codely-isuru/easy_clean_workforce"

# Classic personal access tokens: `ghp_`/`gho_`/`ghu_`/`ghs_`/`ghr_` + 36
# characters. A fine-grained token is `github_pat_` + 82. Shape alone
# distinguishes them, so nothing needs to print a token to tell them apart.
_CLASSIC_PAT_PREFIXES = ("ghp_", "gho_", "ghu_", "ghs_", "ghr_")
_CLASSIC_PAT_LENGTH = 40
_FINE_GRAINED_PREFIX = "github_pat_"


def _settings():
    """The application's own view of configuration — `.env` at the repo root,
    exactly as the app reads it. Never `os.environ`: nothing exports these."""
    from sunil.settings import Settings

    return Settings()


def _require(secret: SecretStr | None, variable: str) -> SecretStr:
    """Return the secret, or **skip**. Never fails, so a missing credential can
    never drag a present one into an assertion failure's output."""
    if secret is None or not secret.get_secret_value():
        pytest.skip(f"{variable} is not configured — this live check is not applicable")
    return secret


# -- predicates: the only place a value is ever unwrapped --------------------
#
# Each returns a bool or an int. A secret cannot escape through them, so no
# caller can leak one by accident.


def _starts_with(secret: SecretStr, prefixes: tuple[str, ...]) -> bool:
    return secret.get_secret_value().startswith(prefixes)


def _length(secret: SecretStr) -> int:
    return len(secret.get_secret_value())


def _same_value(left: SecretStr, right: SecretStr) -> bool:
    return left.get_secret_value() == right.get_secret_value()


def _client(token: SecretStr, base_url: str) -> httpx.Client:
    """The token is unwrapped inline, into the header, and is never bound to a
    local. There is no name in any frame holding a raw credential, so a
    traceback through this function cannot render one."""
    return httpx.Client(
        base_url=base_url,
        timeout=API_TIMEOUT_S,
        follow_redirects=False,
        headers={
            "Authorization": f"Bearer {token.get_secret_value()}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


# The three endpoints the M1 adapter actually calls
# (`sunil/tools/github/adapter.py`). If any is refused, the tool cannot do its
# job — this is the positive half of "what can this credential actually do".
_REQUIRED_READS = ("commits", "pulls", "issues")

# Read endpoints that GitHub gates behind **write-level** permission:
# `collaborators` requires push, `hooks` requires admin. Probing these answers
# "does this token hold more than read?" without going near a mutating verb.
_WRITE_GATED_READS = ("collaborators", "hooks")

# Every probe in this file is an HTTP GET. That is the safety property, and it
# is structural rather than a promise: no GitHub REST GET mutates state, so
# even a token wrongly holding admin cannot change anything through these
# tests. `_assert_probes_are_all_gets()` enforces it mechanically below, so a
# later edit adding a POST fails here rather than against the owner's real
# repository.
_ALLOWED_METHOD = "GET"


def _probe(client: httpx.Client, path: str) -> int:
    """Issue one read-only probe and return its status code only. The response
    body is deliberately discarded: it can contain collaborator logins, webhook
    URLs or secret *names*, none of which belong in test output."""
    response = client.request(_ALLOWED_METHOD, path)
    return response.status_code


def test_every_probe_in_this_file_is_a_get() -> None:
    """The side-effect-free guarantee, mechanised.

    These tests run against the owner's real repositories, so "provably cannot
    mutate" has to be checked rather than intended. `_probe()` is the only way
    this module reaches GitHub, and it is pinned to GET.
    """
    import ast
    import inspect
    import sys

    source = inspect.getsource(sys.modules[__name__])
    verbs = {"post", "put", "patch", "delete"}
    offenders = [
        f"line {node.lineno}: .{node.func.attr}()"
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in verbs
    ]
    assert not offenders, "a mutating HTTP verb appears in the live credential suite: " + "; ".join(
        offenders
    )
    assert _ALLOWED_METHOD == "GET"


def test_the_github_token_can_do_exactly_what_m1_needs_and_no_more() -> None:
    """T-17, measured as **capability** rather than role.

    The previous version asserted on the `permissions` block of
    `GET /repos/{owner}/{repo}`. That block reports the *authenticated user's*
    role on the repository, not the token's grants: against a real fine-grained
    token it returned `admin: True, push: True` while `/commits` and `/issues`
    both returned 403 "Resource not accessible by personal access token". It
    could therefore neither pass for a correctly-scoped token nor fail for the
    right reason on an over-scoped one — the field simply does not vary with
    token scope.

    Capability is asked of the endpoints themselves, in both directions,
    because either half alone is satisfiable by a broken token: a token with no
    access at all passes the negative half, and an admin token passes the
    positive half. Together they mean "exactly the reads M1 performs, and
    nothing gated behind write".
    """
    settings = _settings()
    token = _require(settings.github_token, "GITHUB_TOKEN")

    with _client(token, settings.github_api_base_url) as client:
        required = {
            name: _probe(client, f"/repos/{EXPECTED_REPO}/{name}") for name in _REQUIRED_READS
        }
        write_gated = {
            name: _probe(client, f"/repos/{EXPECTED_REPO}/{name}") for name in _WRITE_GATED_READS
        }

    refused_reads = sorted(name for name, status in required.items() if status != 200)
    assert not refused_reads, (
        f"GITHUB_TOKEN cannot read {refused_reads} on {EXPECTED_REPO} "
        f"(statuses: {required}). M1's GitHub tool calls exactly these three endpoints, so it "
        "cannot function. Grant Contents, Pull requests and Issues: read on that repository."
    )

    # 403/404 both mean "not permitted"; GitHub uses 404 to avoid confirming
    # existence for some resources. Anything else — 200 above all — means the
    # token holds more than the read access T-17 records.
    over_scoped = sorted(name for name, status in write_gated.items() if status not in (403, 404))
    assert not over_scoped, (
        f"GITHUB_TOKEN can reach write-gated endpoints {over_scoped} on {EXPECTED_REPO} "
        f"(statuses: {write_gated}). THREAT_MODEL T-17 records this token as read-only; "
        "re-issue it with Contents, Pull requests and Issues set to read and nothing else."
    )


# A control repository the token must NOT be able to read: any private
# repository other than the target. Supplied by environment because it cannot
# be derived — see the test below for why. `SUNIL_LIVE_CONTROL_REPO=owner/name`.
_CONTROL_REPO_VAR = "SUNIL_LIVE_CONTROL_REPO"


def test_the_github_token_cannot_reach_a_repository_it_was_not_granted() -> None:
    """T-17's containment half: "a repository-scoped read token cannot reach
    other repositories".

    The previous version listed `GET /user/repos` and asserted the result was a
    subset of the target. That measures nothing for a fine-grained token: run
    against a real one it returned four repositories, **none of them the
    target**, because that endpoint enumerates the *user's* repositories rather
    than the token's grants — the same class of defect as reading the
    `permissions` role block.

    There is no endpoint that reports a fine-grained PAT's repository scope, so
    containment cannot be proven by enumeration at all. It can only be proven
    by probing a repository the token should not reach and finding it refused,
    which needs a **private** control repository named explicitly: a public one
    proves nothing, since any token can read public repositories.

    Skips when unconfigured rather than asserting something weaker, so a pass
    here always means a real refusal was observed.
    """
    control_repo = os.environ.get(_CONTROL_REPO_VAR, "").strip()
    if not control_repo:
        pytest.skip(
            f"{_CONTROL_REPO_VAR} is not set — containment cannot be proven without a private "
            "control repository the token should not reach (no endpoint reports a fine-grained "
            f"PAT's scope). Set {_CONTROL_REPO_VAR}=owner/name to enable this check."
        )
    if control_repo == EXPECTED_REPO:
        pytest.skip(f"{_CONTROL_REPO_VAR} names the target repository; it must be a different one")

    settings = _settings()
    token = _require(settings.github_token, "GITHUB_TOKEN")

    with _client(token, settings.github_api_base_url) as client:
        status = _probe(client, f"/repos/{control_repo}")

    assert status in (403, 404), (
        f"GITHUB_TOKEN can reach {control_repo}, which it was not granted (HTTP {status}). "
        "A fine-grained token must be scoped to codely-isuru/easy_clean_workforce only; "
        "re-issue it with 'Only select repositories' and that repository alone."
    )


def test_the_github_token_is_fine_grained_not_a_classic_pat() -> None:
    """The runbook and `.env.example` both specify a **fine-grained** PAT
    scoped to one repository. A classic PAT is a different risk class: its
    `repo` scope is read *and* write across every repository the owner can
    reach, so the blast radius of a leak is the whole account rather than one
    read-only repository — and no per-repository setting narrows it.

    Decided by **shape**, not by reading the token and not by asking GitHub
    for its scopes: the previous version interpolated the `x-oauth-scopes`
    header into the failure message, which is metadata about a credential and
    does not belong in output either.
    """
    settings = _settings()
    token = _require(settings.github_token, "GITHUB_TOKEN")

    looks_classic = _starts_with(token, _CLASSIC_PAT_PREFIXES) and _length(token) == (
        _CLASSIC_PAT_LENGTH
    )
    looks_fine_grained = _starts_with(token, (_FINE_GRAINED_PREFIX,))

    assert not looks_classic, (
        "GITHUB_TOKEN is a classic personal access token. The runbook specifies a "
        "fine-grained PAT scoped to codely-isuru/easy_clean_workforce with Contents, "
        "Pull requests and Issues set to read and nothing else. A classic PAT's `repo` "
        "scope is read AND write across every repository the account can reach, so a leak "
        "exposes the whole account rather than one read-only repository. "
        "Re-issue at github.com/settings/personal-access-tokens, then replace GITHUB_TOKEN "
        "in .env. (This message deliberately names no value.)"
    )
    assert looks_fine_grained, (
        "GITHUB_TOKEN is neither a classic nor a fine-grained PAT by shape. Confirm it is a "
        "GitHub token and re-issue it as fine-grained if not."
    )


_GITHUB_PREFIXES = (*_CLASSIC_PAT_PREFIXES, _FINE_GRAINED_PREFIX)

# Both provider keys, each skipped independently. `ANTHROPIC_API_KEY` is
# optional since T25 and the owner may hold either vendor's key or both;
# OPENAI_API_KEY is the one on the M1 hot path, because `general_reasoning`
# now resolves to OpenAI (`config/models.yaml`).
_PROVIDER_KEYS = (
    ("ANTHROPIC_API_KEY", "anthropic_api_key", ("sk-ant-",)),
    ("OPENAI_API_KEY", "openai_api_key", ("sk-",)),
)


@pytest.mark.parametrize(("variable", "attribute", "prefixes"), _PROVIDER_KEYS)
def test_a_provider_key_is_never_configured_as_the_github_token(
    variable: str, attribute: str, prefixes: tuple[str, ...]
) -> None:
    """T-18 / T-21: each credential is injected into exactly one client, so
    crossing two of them in `.env` sends a provider key to GitHub — or the
    GitHub PAT to a model vendor, in a prompt-bearing request. A real mistake,
    and a silent one: GitHub answers 401 and the turn surfaces `tool_failed`,
    which looks like an outage rather than a leak.

    Skips when the provider key is absent, which is legitimate: `ANTHROPIC_
    API_KEY` is optional and the owner may hold only one vendor's key. The
    earlier version *asserted* both were present — that assertion is what
    printed a live token when the optional one went away.

    Every comparison below is a boolean. No value is interpolated anywhere.
    """
    settings = _settings()
    github_token = _require(settings.github_token, "GITHUB_TOKEN")
    provider_key = _require(getattr(settings, attribute), variable)

    assert not _same_value(github_token, provider_key), (
        f"GITHUB_TOKEN and {variable} hold the same value in .env — one of them is wrong. "
        "Re-check both entries; this message names no value."
    )
    assert not _starts_with(github_token, prefixes), (
        f"GITHUB_TOKEN has {variable}'s prefix — a provider key appears to be configured as "
        "the GitHub token, which would send it to api.github.com."
    )
    assert not _starts_with(provider_key, _GITHUB_PREFIXES), (
        f"{variable} has a GitHub token's prefix — the PAT appears to be configured as a "
        "provider key, which would send it to a model vendor inside a prompt-bearing request."
    )
