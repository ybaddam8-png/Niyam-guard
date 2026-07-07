"""
Structured logging: every log line is one JSON object, so a real log aggregator
(CloudWatch, Datadog, even just `jq` on a file) can filter/search instead of grepping
free text. request_id ties every log line in one HTTP request together, so a failure
mid-demo can actually be traced instead of guessed at.
"""
import json
import logging
import sys
import time
import uuid
from contextvars import ContextVar

_request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")


def get_request_id() -> str:
    """Public accessor so other modules can read the current request's id."""
    return _request_id_ctx.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": _request_id_ctx.get(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)


class RequestIdMiddleware:
    """Assigns a request_id per HTTP request, exposes it in the response header, and
    makes it available via get_request_id().

    Deliberately a raw ASGI middleware, NOT a BaseHTTPMiddleware subclass, and it
    handles unhandled exceptions itself rather than via @app.exception_handler(Exception).
    Two real bugs led here: (1) BaseHTTPMiddleware runs the downstream app in a separate
    task, and contextvars set beforehand aren't reliably visible inside it; (2) even
    after switching to raw ASGI, Starlette's build_middleware_stack() specifically pulls
    any handler registered for the bare Exception class OUT to ServerErrorMiddleware,
    which wraps ALL user middleware including this one — so by the time that handler
    would run, this middleware's contextvar was already reset and its send wrapper was
    no longer in the call chain. Both were caught by a test asserting request_id != "-"
    in the actual response body, not by code review.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = str(uuid.uuid4())[:8]
        token = _request_id_ctx.set(request_id)
        start = time.time()
        logger = logging.getLogger("niyamguard.request")
        status_holder: dict = {}
        response_started = False

        async def send_wrapper(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                status_holder["status_code"] = message["status"]
                headers = list(message.get("headers", []))
                headers.append((b"x-request-id", request_id.encode()))
                message["headers"] = headers
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
            duration_ms = (time.time() - start) * 1000
            method, path = scope.get("method", ""), scope.get("path", "")
            logger.info(f"{method} {path} -> {status_holder.get('status_code', '?')} ({duration_ms:.0f}ms)")
        except Exception:
            logger.exception(
                f"{scope.get('method', '')} {scope.get('path', '')} -> unhandled exception"
            )
            if response_started:
                raise
            body = json.dumps({
                "detail": "An internal error occurred. This has been logged.",
                "request_id": request_id,
            }).encode("utf-8")
            await send({
                "type": "http.response.start",
                "status": 500,
                "headers": [(b"content-type", b"application/json"), (b"x-request-id", request_id.encode())],
            })
            await send({"type": "http.response.body", "body": body})
        finally:
            _request_id_ctx.reset(token)
