"""One error shape for the whole API — C5 §3's `{"error": {kind, message}}`.

FastAPI's default bodies (`{"detail": …}` for `HTTPException`, a list of
pydantic error dicts for a 422) are neither C5's shape nor safe by default: the
422 body echoes the offending `input` back to the caller, which on this API
would mean echoing whatever the client sent — including a credential a client
put in the wrong field. `validation_error_handler` therefore reports `type` and
`loc` and drops `input` entirely.
"""

from __future__ import annotations

from typing import Any

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from sunil.api.schemas import ErrorKind, error_payload
from sunil.logging import get_logger

_logger = get_logger("sunil.api.errors")


class ApiError(Exception):
    """An error with a C5 `kind`. Raised by dependencies and routes; rendered by
    `api_error_handler` below."""

    def __init__(self, status_code: int, kind: ErrorKind, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.kind: ErrorKind = kind
        self.message = message


async def api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, ApiError)
    # The refusal is recorded; the CREDENTIAL is not. `kind`, `status` and `path`
    # are the whole payload — no header value is an input to this call, which is
    # C5 §3's structural rule rather than a redaction hope.
    _logger.info(
        "api_error", kind=exc.kind, status=exc.status_code, path=request.url.path
    )
    return JSONResponse(
        status_code=exc.status_code, content=error_payload(exc.kind, exc.message)
    )


async def ops_api_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """The same envelope for Stream D's separate `ApiError` class.

    `routes/approvals.py` declares its own `ApiError` (it was built in a worktree
    with no spine module to import one from), and every C4 and C6 route raises
    THAT class. Registering only the handler above would leave each Stream D
    refusal unhandled — a 500 on an authentication refusal, which is an outage
    rather than a denial, and one that returns a stack trace where a 401 belongs.

    Handled here rather than by calling Stream D's own `install_error_handlers`,
    because that function ALSO rebinds `RequestValidationError` and would
    silently replace the C5-contracted 422 text for every route in the app.

    `X-Content-Type-Options: nosniff` is set on the error path too (C4 §4): the
    message can carry a path parameter the caller chose, and "it is only an error
    body" is exactly how a JSON response comes to be rendered as HTML.
    """
    from sunil.api.routes.approvals import ApiError as OpsApiError  # noqa: PLC0415

    assert isinstance(exc, OpsApiError)
    _logger.info(
        "api_error", kind=exc.kind, status=exc.status_code, path=request.url.path
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(exc.kind, exc.message),
        headers={"X-Content-Type-Options": "nosniff"},
    )


async def validation_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """422 in C5's shape, with the offending input NEVER reflected."""
    del request
    assert isinstance(exc, RequestValidationError)
    fields: list[str] = []
    for error in exc.errors():
        location = ".".join(str(part) for part in error.get("loc", ()) if part != "body")
        fields.append(f"{location or 'body'}: {error.get('type', 'invalid')}")
    return JSONResponse(
        status_code=422,
        content=error_payload("validation_error", "; ".join(fields) or "invalid request body"),
    )


async def http_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Anything raising a bare `HTTPException` (including Starlette's own 404 for
    an unrouted path) still answers in C5's shape."""
    del request
    assert isinstance(exc, StarletteHTTPException)
    kind: dict[int, Any] = {
        401: "unauthenticated",
        403: "forbidden_client",
        404: "not_found",
        422: "validation_error",
    }
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(kind.get(exc.status_code, "not_found"), str(exc.detail)),
    )
