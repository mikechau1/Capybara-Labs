"""Structured JSON logs and request IDs. Card M1-03 owns this file.

Every request gets an ID: the caller's `X-Request-ID` header if it looks safe, otherwise a new
one. The ID is returned in the same header and added to every log line written while the
request is handled, so one request can be traced through the logs.

Log from any module with the standard library and the ID is added for you:

    log = logging.getLogger(__name__)
    log.info("grant created", extra={"grant_id": grant.id})

Fields passed in `extra` become JSON fields. Never log secrets, tokens or document text.
"""

import json
import logging
import re
import sys
import time
import uuid
from collections.abc import Callable
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

REQUEST_ID_HEADER = "X-Request-ID"

# Accept a caller's ID only if it is short and plain, so it cannot break or forge log lines.
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9._-]{1,128}")

_request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has; anything else on a record came from `extra`.
# `color_message` is Uvicorn's copy of its message with terminal colour codes.
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "color_message"}

request_log = logging.getLogger("app.request")


def current_request_id() -> str | None:
    """The ID of the request being handled, or None outside a request."""
    return _request_id.get()


class JsonFormatter(logging.Formatter):
    """One JSON object per line: time, level, logger, message, request_id, then any extras."""

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or _request_id.get()
        if request_id:
            entry["request_id"] = request_id
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and key not in entry and key != "request_id":
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class _JsonHandler(logging.StreamHandler):
    """Marks the handler this module installs, so configuring again replaces only ours."""


def _stamp_request_id(
    factory: Callable[..., logging.LogRecord],
) -> Callable[..., logging.LogRecord]:
    """Wrap a record factory so each record keeps the request ID from the moment it is created.

    Reading the ID at creation, not when the line is printed, keeps it correct even when a
    handler formats the record later, after the request has finished.
    """

    def make_record(*args: Any, **kwargs: Any) -> logging.LogRecord:
        record = factory(*args, **kwargs)
        record.request_id = _request_id.get()
        return record

    make_record._stamps_request_id = True  # type: ignore[attr-defined]
    return make_record


def configure_logging(level: str) -> None:
    """Send all logs, including Uvicorn's, to stdout as JSON lines."""
    factory = logging.getLogRecordFactory()
    if not getattr(factory, "_stamps_request_id", False):
        logging.setLogRecordFactory(_stamp_request_id(factory))

    root = logging.getLogger()
    for handler in [h for h in root.handlers if isinstance(h, _JsonHandler)]:
        root.removeHandler(handler)
    handler = _JsonHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(level)

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_log = logging.getLogger(name)
        uvicorn_log.handlers.clear()
        uvicorn_log.propagate = True
    # RequestContextMiddleware writes one line per request, with its ID, so Uvicorn's own
    # access log would only repeat it.
    logging.getLogger("uvicorn.access").disabled = True


class RequestContextMiddleware:
    """Gives each HTTP request an ID and writes one log line when the request finishes."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        incoming = Headers(scope=scope).get(REQUEST_ID_HEADER)
        is_safe = incoming is not None and _SAFE_REQUEST_ID.fullmatch(incoming)
        request_id = incoming if is_safe else uuid.uuid4().hex
        token = _request_id.set(request_id)
        started = time.perf_counter()
        status = 500  # stays 500 if the app fails before sending a response

        async def send_with_request_id(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                MutableHeaders(scope=message).append(REQUEST_ID_HEADER, request_id)
            await send(message)

        try:
            await self.app(scope, receive, send_with_request_id)
        finally:
            method, path = scope["method"], scope["path"]
            # 501 is a stub for an unbuilt card, which is expected, not a server failure.
            failed = status >= 500 and status != 501
            request_log.log(
                logging.ERROR if failed else logging.INFO,
                "%s %s %s",
                method,
                path,
                status,
                extra={
                    "method": method,
                    "path": path,
                    "status": status,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            _request_id.reset(token)
