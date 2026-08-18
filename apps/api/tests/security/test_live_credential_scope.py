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


def test_the_github_token_has_no_write_access_to_the_target_repository() -> None:
    """T-17. A repository-scoped read token must report `push`, `admin` and
    `maintain` false. If any is true, the tool M1 grants an agent can modify
    the owner's business repository.

    `permissions` is GitHub's own boolean block — no credential — but it is
    reduced to the three booleans under test rather than interpolated whole,
    so this assertion's output cannot grow to include something sensitive if
    GitHub adds a field.
    """
    settings = _settings()
    token = _require(settings.github_token, "GITHUB_TOKEN")

    with _client(token, settings.github_api_base_url) as client:
        response = client.get(f"/repos/{EXPECTED_REPO}")
        status = response.status_code
        permissions = response.json().get("permissions", {}) if status == 200 else {}

    assert status == 200, f"cannot read the target repository: HTTP {status}"
    granted = sorted(level for level in ("push", "admin", "maintain") if permissions.get(level))
    assert not granted, (
        f"GITHUB_TOKEN grants {granted} on {EXPECTED_REPO}; T-17 records it as read-only. "
        "Re-issue it with Contents/Pull requests/Issues set to read."
    )
    assert permissions.get("pull") is True, "GITHUB_TOKEN cannot read the target repository"


def test_the_github_token_is_scoped_to_one_repository() -> None:
    """T-17: "a repository-scoped read token cannot reach other repositories".
    Repository *names* are not credentials, so naming the excess ones is what
    makes the failure actionable."""
    settings = _settings()
    token = _require(settings.github_token, "GITHUB_TOKEN")

    with _client(token, settings.github_api_base_url) as client:
        listed = client.get("/user/repos", params={"per_page": 100})
        status = listed.status_code
        names = {repo["full_name"] for repo in listed.json()} if status == 200 else set()

    if status == 200:
        beyond = sorted(names - {EXPECTED_REPO})
        assert not beyond, f"the token can enumerate repositories beyond {EXPECTED_REPO}: {beyond}"
    else:
        assert status in (401, 403, 404), f"unexpected status enumerating repositories: {status}"


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
