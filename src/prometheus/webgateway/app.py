"""The gateway's ASGI app: serves the built frontend as static files,
and reverse-proxies `/api/jobs/*` and `/api/dashboard/*` to the two
real backends, replaying `frontend/vite.config.ts`'s own dev-proxy
rewrites exactly so the SAME built assets work against this origin
unmodified.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from prometheus.webgateway.proxy import (
    UpstreamResponse,
    UpstreamTransport,
    UpstreamUnavailableError,
    UrllibUpstreamTransport,
)
from prometheus.webgateway.static_files import StaticFileNotFoundError, resolve_static_file

Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]

_HOP_BY_HOP_REQUEST_HEADERS = frozenset({"host", "content-length", "connection"})
_HOP_BY_HOP_RESPONSE_HEADERS = frozenset({"content-length", "transfer-encoding", "connection"})


class WebGatewayHTTPError(ValueError):
    def __init__(self, status: int, message: str) -> None:
        self.status, self.message = status, message


class WebGatewayService:
    def __init__(
        self,
        dist_root: Path,
        jobs_url: str,
        dashboard_url: str,
        transport: UpstreamTransport | None = None,
    ) -> None:
        self.dist_root = dist_root
        self.jobs_url = jobs_url.rstrip("/")
        self.dashboard_url = dashboard_url.rstrip("/")
        self.transport = transport or UrllibUpstreamTransport()

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            # Same handling as dashboard.app.DashboardService/
            # service.application.ResearchService -- real ASGI servers
            # (uvicorn) send this before any HTTP request.
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        if scope["type"] != "http":
            raise ValueError("this gateway serves HTTP only")
        request_body = await _read_body(receive)
        try:
            status, headers, body = self._dispatch(scope, request_body)
        except WebGatewayHTTPError as exc:
            status = exc.status
            headers = [(b"content-type", b"text/plain; charset=utf-8")]
            body = exc.message.encode("utf-8")
        headers.append((b"content-length", str(len(body)).encode("ascii")))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    def _dispatch(
        self, scope: dict[str, Any], request_body: bytes
    ) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
        path, method = scope["path"], scope["method"]
        if path == "/health/live":
            return 200, [(b"content-type", b"text/plain; charset=utf-8")], b"live"
        if path.startswith("/api/jobs"):
            upstream_path = path.removeprefix("/api/jobs")
            return self._proxy(self.jobs_url, upstream_path, scope, method, request_body)
        if path.startswith("/api/dashboard"):
            upstream_path = "/dashboard" + path.removeprefix("/api/dashboard")
            return self._proxy(self.dashboard_url, upstream_path, scope, method, request_body)
        try:
            static = resolve_static_file(self.dist_root, path)
        except StaticFileNotFoundError as exc:
            raise WebGatewayHTTPError(404, str(exc)) from exc
        return 200, [(b"content-type", static.content_type.encode("ascii"))], static.body

    def _proxy(
        self,
        base_url: str,
        upstream_path: str,
        scope: dict[str, Any],
        method: str,
        request_body: bytes,
    ) -> tuple[int, list[tuple[bytes, bytes]], bytes]:
        query_string = scope.get("query_string", b"").decode("ascii")
        url = f"{base_url}{upstream_path}" + (f"?{query_string}" if query_string else "")
        try:
            response: UpstreamResponse = self.transport.request(
                method, url, _forward_request_headers(scope), request_body, timeout=30.0
            )
        except UpstreamUnavailableError as exc:
            raise WebGatewayHTTPError(502, str(exc)) from exc
        headers = [
            (name.lower().encode("ascii"), value.encode("latin-1"))
            for name, value in response.headers
            if name.lower() not in _HOP_BY_HOP_RESPONSE_HEADERS
        ]
        return response.status, headers, response.body


async def _read_body(receive: Receive) -> bytes:
    body = b""
    more_body = True
    while more_body:
        message = await receive()
        body += message.get("body", b"")
        more_body = message.get("more_body", False)
    return body


def _forward_request_headers(scope: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    raw_headers = scope.get("headers", [])
    return tuple(
        (name.decode("ascii"), value.decode("latin-1"))
        for name, value in raw_headers
        if name.decode("ascii").lower() not in _HOP_BY_HOP_REQUEST_HEADERS
    )
