"""GitHub tool-result projection — the headline security control for T8
(`ARCHITECTURE_V1.md` §9.4 control 3, success-test step 13, ET-12).

Untrusted GitHub content (commit messages, PR/issue titles and — above
all — **bodies**) is written by third parties and is then placed in
front of a model that holds authority. This module is the *one* place a
raw GitHub API response is converted into the allow-listed, length-capped
shape that may ever reach a prompt. The adapter (`adapter.py`) never
returns raw API JSON as `ToolResult.data` — only this module's output
does — so there is no code path that "reaches around" the projection by
constructing its own dict from the raw response.

**Allow-list, never deny-list**, per the Security Reviewer's own
framing: a deny-list silently admits every field GitHub adds later. The
three permitted shapes are declared as constants immediately below, and
every projector function is checked against them by construction (each
projector's `return` literal *is* the allow-list — there is no loop over
`raw.items()` that a new field could sneak through).

Also provides `wrap_untrusted_tool_result()` — §9.4 control 4 — so T10's
agent has a ready-made, unbypassable way to wrap already-projected
content for prompt inclusion with the delimiter escaped, rather than
reimplementing string-escaping ad hoc at the one call site that needs it.
"""

from __future__ import annotations

import json
from typing import Any

# The complete allow-lists (Security Reviewer, quoted verbatim). Deny-list
# projection is the thing this whole module exists to avoid.
COMMIT_ALLOWED_FIELDS = frozenset({"sha", "message", "author_login", "committed_at"})
PULL_REQUEST_ALLOWED_FIELDS = frozenset(
    {"number", "title", "author_login", "created_at", "updated_at", "draft"}
)
ISSUE_ALLOWED_FIELDS = frozenset({"number", "title", "author_login", "created_at", "comments"})

_COMMIT_MESSAGE_CAP = 300
_TITLE_CAP = 200

_UNTRUSTED_TAG = "untrusted_tool_result"
_CLOSING_DELIMITER = f"</{_UNTRUSTED_TAG}>"
_OPENING_DELIMITER_PREFIX = f"<{_UNTRUSTED_TAG}"


def _neutralise_delimiter(text: str) -> str:
    """Escape `<`/`>` so no free-text field can carry a literal
    `</untrusted_tool_result>` (or a forged opening tag) through
    projection itself — **not only** at the later prompt-wrapping step
    (`wrap_untrusted_tool_result`). Control 4 depends on the delimiter
    being unforgeable from inside the content; that must hold even for a
    caller that reads a projected field directly and never calls the
    wrap helper, so this is where the guarantee actually starts.

    Applied *before* the length cap, not after: escaping can only grow a
    string, and capping the escaped text is what keeps the final length
    bound exact (a raw string exactly at the cap could otherwise grow
    past it once escaped).
    """
    return text.replace("<", "&lt;").replace(">", "&gt;")


def project_commit(raw: dict[str, Any]) -> dict[str, Any]:
    """`{sha[:7], message[:300], author_login, committed_at}` — no other
    key. `sha` is truncated to 7 characters (a short hash, not a secret,
    but still not the full raw object); `message` is capped so a single
    field cannot carry unbounded attacker prose."""
    sha = raw.get("sha") or ""
    commit = raw.get("commit") or {}
    message = _neutralise_delimiter(commit.get("message") or "")[:_COMMIT_MESSAGE_CAP]
    author_login = (raw.get("author") or {}).get("login")
    committed_at = (commit.get("author") or {}).get("date")
    projected = {
        "sha": sha[:7],
        "message": message,
        "author_login": author_login,
        "committed_at": committed_at,
    }
    assert set(projected) == COMMIT_ALLOWED_FIELDS
    return projected


def project_pull_request(raw: dict[str, Any]) -> dict[str, Any]:
    """`{number, title[:200], author_login, created_at, updated_at,
    draft}` — deliberately **no `body` key**. Issue and PR bodies are
    excluded entirely in M1: long free-form text from strangers is the
    highest-yield injection surface and an M1 status summary does not
    need it."""
    projected = {
        "number": raw.get("number"),
        "title": _neutralise_delimiter(raw.get("title") or "")[:_TITLE_CAP],
        "author_login": (raw.get("user") or {}).get("login"),
        "created_at": raw.get("created_at"),
        "updated_at": raw.get("updated_at"),
        "draft": raw.get("draft", False),
    }
    assert set(projected) == PULL_REQUEST_ALLOWED_FIELDS
    return projected


def project_issue(raw: dict[str, Any]) -> dict[str, Any] | None:
    """`{number, title[:200], author_login, created_at, comments}` — no
    `body`. Returns `None` for an item that carries a `pull_request` key:
    GitHub's `/issues` endpoint also returns pull requests, and an
    unfiltered listing counts every PR twice."""
    if "pull_request" in raw:
        return None
    projected = {
        "number": raw.get("number"),
        "title": _neutralise_delimiter(raw.get("title") or "")[:_TITLE_CAP],
        "author_login": (raw.get("user") or {}).get("login"),
        "created_at": raw.get("created_at"),
        "comments": raw.get("comments", 0),
    }
    assert set(projected) == ISSUE_ALLOWED_FIELDS
    return projected


def project_recent_activity(payload: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    """The adapter's one entry point into this module.

    `payload` carries the three raw GitHub API response bodies under
    `commits`, `pulls`, `issues` (matching the three concurrent GET calls
    the adapter makes); the returned shape uses `pull_requests` for the
    projected key, matching the plan/agent-facing vocabulary rather than
    GitHub's own endpoint name.
    """
    commits = payload.get("commits") or []
    pulls = payload.get("pulls") or []
    issues = payload.get("issues") or []

    return {
        "commits": [project_commit(c) for c in commits],
        "pull_requests": [project_pull_request(p) for p in pulls],
        "issues": [projected for raw in issues if (projected := project_issue(raw)) is not None],
    }


def wrap_untrusted_tool_result(*, tool: str, operation: str, projected: dict[str, Any]) -> str:
    """§9.4 control 4 — wrap already-projected content (never a raw
    payload) for inclusion in a **user**-role prompt message, with any
    occurrence of the closing delimiter inside the content escaped so
    injected text cannot forge a fake `</untrusted_tool_result>` and step
    outside the wrapper.

    Escaping replaces `<` and `>` with their HTML entity forms *only*
    within the serialised content, never in the wrapper tags themselves,
    so the envelope stays well-formed while nothing inside it can end it
    early.
    """
    serialised = json.dumps(projected, ensure_ascii=False, default=str)
    escaped = serialised.replace("<", "&lt;").replace(">", "&gt;")
    assert _CLOSING_DELIMITER not in escaped
    return (
        f'{_OPENING_DELIMITER_PREFIX} tool="{tool}" operation="{operation}">'
        f"{escaped}"
        f"{_CLOSING_DELIMITER}"
    )
