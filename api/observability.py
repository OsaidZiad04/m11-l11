"""Observability layer for the M10 backend."""

import contextvars
import json
import logging
import time
import uuid

from prometheus_client import Counter, Gauge, Histogram
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send


requests_total = Counter(
    "requests_total",
    "Total HTTP requests",
    ["path", "status"],
)

request_latency_seconds = Histogram(
    "request_latency_seconds",
    "Request latency in seconds",
    ["path"],
)

inflight_requests = Gauge(
    "inflight_requests",
    "In-flight requests",
)

request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id",
    default="",
)


class RequestIdMiddleware:
    """Generate a request ID and attach it to the response."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = uuid.uuid4().hex
        token = request_id_var.set(request_id)

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            request_id_var.reset(token)


class StructuredLoggingMiddleware:
    """Emit one structured JSON log line per HTTP request."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = int(message["status"])

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            latency_ms = (time.perf_counter() - started) * 1000

            log_line = {
                "ts": time.time(),
                "level": "INFO",
                "request_id": request_id_var.get(),
                "path": scope.get("path", ""),
                "status": status_code,
                "latency_ms": round(latency_ms, 2),
            }

            logging.getLogger("m11.api").info(json.dumps(log_line))


class MetricsMiddleware:
    """Record request count, latency, and in-flight request count."""

    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = str(scope.get("path", ""))

        if path in {"/metrics", "/metrics/"}:
            await self.app(scope, receive, send)
            return

        inflight_requests.inc()
        started = time.perf_counter()
        status_code = 500

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code

            if message["type"] == "http.response.start":
                status_code = int(message["status"])

            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            elapsed_seconds = time.perf_counter() - started

            inflight_requests.dec()
            requests_total.labels(
                path=path,
                status=str(status_code),
            ).inc()
            request_latency_seconds.labels(path=path).observe(elapsed_seconds)