"""`RequestContextMiddleware` — the second layer of the explicit
constructor list (`sunil/main.py`), between CORS (outermost) and
`SessionMiddleware` (innermost). §3.3, §5.3, §9.5.

Responsibilities, exactly three:

1. **Accept or reject `X-Request-Id`.** If the caller supplied one, it
   must be a valid UUID4 or the request is rejected with 422 — this is the
   frozen §6 contract's own failure mode for `POST /api/v1/chat`, applied
   once here because there is only one place this header should be
   parsed. If the caller supplied none, one is generated so every request
   still has a stable id to log against.
2. **Bind `request_id` to structlog's `contextvars`** for the life of the
   request, so every log line carries it without every call site passing
   it explicitly (FR-008).
3. **Record the turn clock's start** (`request.state.turn_started_monotonic`)
   — the §5.3 turn deadline's anchor. This middleware does not construct a
   `TraceContext` itself (that needs a DB session-maker this layer does
   not have); it hands the earliest possible timestamp to whichever route
   builds one (T11a's chat handler).
"""

from __future__ import annotations

import time
import uuid
from typing import Any

import structlog
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.sessions import SessionMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

_REQUEST_ID_HEADER = "X-Request-Id"


def is_valid_uuid4(value: str) -> bool:
    try:
        parsed = uuid.UUID(value)
    except (ValueError, AttributeError, TypeError):
        return False
    return parsed.version == 4


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        header_value = request.headers.get(_REQUEST_ID_HEADER)
        if header_value is not None and not is_valid_uuid4(header_value):
            return JSONResponse(
                status_code=422,
                content={"detail": f"{_REQUEST_ID_HEADER} must be a valid UUID4"},
            )

        request_id = header_value or str(uuid.uuid4())
        request.state.request_id = request_id
        request.state.turn_started_monotonic = time.monotonic()

        with structlog.contextvars.bound_contextvars(request_id=request_id):
            response = await call_next(request)

        response.headers[_REQUEST_ID_HEADER] = request_id
        return response


def build_session_middleware(settings: Any) -> Middleware:
    """`sunil.main.create_app()`'s `SessionMiddleware` entry — moved here
    (T11b) because unwrapping `settings.session_secret` is a
    `SecretStr.get_secret_value()` call, and `sunil/main.py` is not on
    `tests/security/test_import_boundaries.py
    ::test_agents_never_unwrap_a_secret`'s allow-list (`providers/`,
    `tools/`, `db/`, `api/`, `settings.py`, `redaction.py`) — this module
    is. Kept generic over `settings: Any` (matching `sunil.redaction`'s
    own pattern) so this module carries no import-time dependency on
    `sunil.settings`.
    """
    return Middleware(
        SessionMiddleware,
        secret_key=settings.session_secret.get_secret_value(),
        session_cookie=settings.session_cookie_name,
        max_age=86400,
        same_site="lax",
        https_only=False,  # local dev is http://localhost; flip when hosted over TLS
        path="/",
    )
