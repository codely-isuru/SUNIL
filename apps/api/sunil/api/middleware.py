"""Middleware: CORS (TB1) and the signed session cookie (ADR-007).

Two settings carry the whole browser trust boundary:

* `WEB_ORIGIN` is the **single** allowed origin. `allow_origins=["*"]` with
  `allow_credentials=True` is not merely discouraged — it is the configuration
  that turns every page on the internet into an authenticated client of this API,
  so the allow-list is built from one configured value and nothing widens it.
* `SESSION_SECRET` signs the cookie. `https_only` follows the origin scheme, so a
  production `https://` origin gets a Secure cookie without a second switch to
  forget, while local `http://localhost` development still works.

`same_site="lax"` (not `"none"`) because the browser page and the API are both
`localhost` (ADR-008) — the CSRF pair (`X-SUNIL-Client` + Origin) is the control
that matters, and `lax` removes the cross-site POST case entirely.

`OwnerIdentityMiddleware` then publishes the established identity where Stream
D's route dependencies look for it — see its own docstring.
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

from sunil.api.deps import CLIENT_HEADER, SESSION_USER_KEY


class OwnerIdentityMiddleware:
    """Publish the ADR-007 session's owner id on `request.state.owner_user_id`.

    Stream D's `routes/approvals.py::require_owner_session` — the single owner
    lane shared by the C4 and C6 routes — reads `request.state.owner_user_id` and
    documents it as "the identity ADR-007 session middleware established". That
    middleware is the spine's, and until this round it established nothing there,
    so every C4/C6 read answered 401 behind a perfectly valid cookie.

    This publishes the value; it does not decide anything. There is still exactly
    ONE reader of the signed cookie (`SessionMiddleware`) and one key
    (`SESSION_USER_KEY`), which is why this is a three-line copy rather than a
    second dependency that re-derives identity — two derivations of "who the
    owner is" is how they come to disagree.

    **It must run INSIDE `SessionMiddleware`** (added before it, since Starlette
    applies middleware outermost-last), because `scope["session"]` does not exist
    until that middleware has run. If it is ever reordered outside, `session` is
    absent, the key is `None`, and the dependency refuses — the failure mode is a
    locked door, not an open one.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            scope.setdefault("state", {})
            scope["state"]["owner_user_id"] = (scope.get("session") or {}).get(
                SESSION_USER_KEY
            )
        await self.app(scope, receive, send)


def install_middleware(app: FastAPI, settings: Any) -> None:
    """Order matters: the session middleware must be added AFTER CORS so that it
    runs INSIDE it (Starlette applies middleware outermost-last), which keeps a
    rejected cross-origin preflight from ever touching cookie handling. By the
    same rule `OwnerIdentityMiddleware` is added FIRST, so it runs innermost —
    after the session has been decoded and before any route dependency reads it."""
    app.add_middleware(OwnerIdentityMiddleware)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value(),
        session_cookie=settings.session_cookie_name,
        same_site="lax",
        https_only=urlparse(settings.web_origin).scheme == "https",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.web_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Content-Type", "Accept", CLIENT_HEADER],
    )
