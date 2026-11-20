"""One error shape for every API error. Card M1-03 owns this file.

Every error response has this body, whatever caused it:

    {"detail": "A sentence a person can read.", "code": "not_found", "request_id": "6f1c..."}

- `detail` is always a string; the UI shows it as is.
- `code` is a stable word for code to check. It follows the status unless you pass your own.
- `request_id` matches the X-Request-ID header and the log lines for that request.
- Validation errors (422) add `errors`: which fields were wrong, without echoing their values.

Raise errors in your module like this:

    raise ApiError(404, "No grant with that ID.")
    raise ApiError(409, "That grant is already revoked.", code="grant_revoked")

A plain `HTTPException` also works and gets the same shape.
"""

import logging
from http import HTTPStatus

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.shared.logs import current_request_id

log = logging.getLogger(__name__)

_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "too_many_requests",
    500: "internal_error",
    501: "not_implemented",
    503: "unavailable",
}


def code_for(status_code: int) -> str:
    return _CODES.get(status_code, "error")


class ApiError(HTTPException):
    """An HTTPException that can carry its own `code`."""

    def __init__(
        self,
        status_code: int,
        detail: str,
        code: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(status_code, detail, headers)
        self.code = code or code_for(status_code)


def not_implemented(card: str) -> ApiError:
    """Raise from a stub endpoint so callers can tell "not built yet" apart from a real error."""
    return ApiError(501, f"Not implemented yet. See board card {card}.")


def error_response(
    status_code: int,
    detail: str,
    code: str | None = None,
    headers: dict[str, str] | None = None,
    errors: list[dict[str, object]] | None = None,
) -> JSONResponse:
    body: dict[str, object] = {
        "detail": detail,
        "code": code or code_for(status_code),
        "request_id": current_request_id(),
    }
    if errors is not None:
        body["errors"] = errors
    return JSONResponse(body, status_code=status_code, headers=headers)


async def _http_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    detail = exc.detail if isinstance(exc.detail, str) else HTTPStatus(exc.status_code).phrase
    return error_response(exc.status_code, detail, getattr(exc, "code", None), exc.headers)


async def _validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Keep where and why; drop the submitted values, which could be secrets or document text.
    errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return error_response(422, "The request is not valid.", errors=errors)


class UnhandledErrorMiddleware:
    """Turns a crash into a 500 in the standard shape and logs the traceback.

    The caller never sees the traceback, only a request ID that leads to it in the logs.
    This is middleware rather than an exception handler so that it runs inside
    RequestContextMiddleware and the request ID is still known.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def tracking_send(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, receive, tracking_send)
        except Exception:
            log.exception("Unhandled error")
            if response_started:
                raise  # too late to send an error body; the server closes the connection
            await error_response(500, "Internal error.")(scope, receive, send)


def install_error_handlers(app: FastAPI) -> None:
    """Call before adding RequestContextMiddleware, so that middleware wraps this one."""
    app.add_exception_handler(StarletteHTTPException, _http_error)
    app.add_exception_handler(RequestValidationError, _validation_error)
    app.add_middleware(UnhandledErrorMiddleware)
