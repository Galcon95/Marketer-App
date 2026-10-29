"""Logging of the whole server, configured once in server.py: one console handler, JSON lines by default.

Every log line carries the id of the HTTP request that produced it, so a request can be followed through its
retrievals, model calls (usage log), tool calls, blocked injections and failures:

    RequestIdMiddleware   gives each HTTP request an id (the caller's X-Request-ID if it is a sane value, else a
                          new one), keeps it in the context variable `request_id` while the request runs, returns
                          it in the X-Request-ID response header and logs one line when the request ends
    RequestIdFilter       copies the current id into every log record (`-` outside a request, e.g. at startup)
    JsonFormatter         one JSON object per line: time, level, logger, request_id, message (+ exception)

The context variable reaches FastAPI's worker threads, background tasks (ingestion after an upload) and LangGraph's
nodes, because all of them copy the context. The graphs also put the id into their run metadata, so a LangSmith
trace and the local log lines share one key. Settings in config.py: LOG_FORMAT ("json" or "text"), LOG_LEVEL.
"""

import json
import logging
import logging.config
import re
import time
from contextvars import ContextVar
from datetime import datetime, timezone
from uuid import uuid4

from app.core import config

request_id: ContextVar[str | None] = ContextVar("request_id", default=None)

HEADER = "X-Request-ID"
_SANE_ID = re.compile(r"[A-Za-z0-9._-]{1,64}")  # ids taken from callers; anything else is replaced

logger = logging.getLogger("app.request")


def current_request_id() -> str | None:
    """The id of the HTTP request being handled, None outside a request."""
    return request_id.get()


class RequestIdFilter(logging.Filter):
    """Adds `request_id` to every record (the current request's id, or "-")."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id.get() or "-"
        return True


class JsonFormatter(logging.Formatter):
    """Formats a record as one JSON line: time (UTC, ISO 8601), level, logger, request_id, message, exception."""

    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "time": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "request_id": getattr(record, "request_id", "-"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry)  # ASCII only (non-ASCII escaped), so no Windows console code page can choke on it


def setup() -> None:
    """Configure logging for the whole server (call once, at startup).

    Application loggers go to one console handler at LOG_LEVEL, as JSON lines or readable text (LOG_FORMAT).
    uvicorn keeps its own handlers; httpx's line per HTTP request is silenced (the usage log has every model call).
    """
    logging.config.dictConfig({
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {"request_id": {"()": RequestIdFilter}},
        "formatters": {
            "json": {"()": JsonFormatter},
            "text": {"format": "%(asctime)s %(levelname)-7s [%(request_id)s] %(name)s: %(message)s"},
        },
        "handlers": {
            "console": {"class": "logging.StreamHandler", "formatter": config.LOG_FORMAT, "filters": ["request_id"]},
        },
        "root": {"level": config.LOG_LEVEL, "handlers": ["console"]},
        "loggers": {name: {"level": "WARNING"} for name in ("httpx", "httpx2", "httpcore")},  # httpx2: MCP SDK's copy
    })


class RequestIdMiddleware:
    """ASGI middleware: one id per HTTP request, in the context, the response header and a closing log line.

    GET requests (the client polls health and ingestion status) are logged at DEBUG, unless they fail; everything
    else at INFO, 4xx at WARNING and 5xx at ERROR.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming = dict(scope.get("headers") or []).get(HEADER.lower().encode(), b"").decode("latin-1")
        rid = incoming if _SANE_ID.fullmatch(incoming) else uuid4().hex[:16]
        token = request_id.set(rid)
        started, status = time.perf_counter(), 500

        async def send_with_id(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                message = {**message, "headers": [*message.get("headers", []), (HEADER.lower().encode(), rid.encode())]}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            level = (logging.ERROR if status >= 500 else logging.WARNING if status >= 400
                     else logging.DEBUG if scope["method"] == "GET" else logging.INFO)
            logger.log(level, "%s %s -> %d (%d ms)", scope["method"], scope["path"], status,
                       round((time.perf_counter() - started) * 1000))
            request_id.reset(token)
