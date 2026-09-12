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
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware

from sunil.api.deps import CLIENT_HEADER


def install_middleware(app: FastAPI, settings: Any) -> None:
    """Order matters: the session middleware must be added AFTER CORS so that it
    runs INSIDE it (Starlette applies middleware outermost-last), which keeps a
    rejected cross-origin preflight from ever touching cookie handling."""
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
