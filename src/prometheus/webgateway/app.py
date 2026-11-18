"""The gateway's ASGI app: serves the built frontend as static files,
and reverse-proxies `/api/jobs/*` and `/api/dashboard/*` to the two
real backends, replaying `frontend/vite.config.ts`'s own dev-proxy
rewrites exactly so the SAME built assets work against this origin
unmodified.

It is the single origin a browser talks to, so it is also where the
edge controls live: strict request-target validation and routing
(`webgateway.routing`), per-client rate limiting, bounded request and
response bodies, bounded upstream concurrency, security and cache
headers on every response (`webgateway.headers`), a catch-all that turns
any unexpected failure into a generic 500 (detail goes to the log, never
the client), and one structured access-log line per request that never
contains a query string or a credential.

Proxied calls run in a worker thread: the transport does blocking
socket I/O, and doing that on the event loop would let a single slow
backend response (the dashboard trains models) freeze every other
request -- static files and the health probe included.
"""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from prometheus.httpsec.concurrency import BoundedExecutor, Overloaded
from prometheus.httpsec.ratelimit import TokenBucketLimiter, client_key
from prometheus.webgateway.headers import (
    IMMUTABLE_CACHE,
    NO_STORE_CACHE,
    REVALIDATE_CACHE,
    HeaderList,
    finalize_headers,
    set_default_header,
)
from prometheus.webgateway.proxy import (
    HttpUpstreamTransport,
    UpstreamRequestError,
    UpstreamResponse,
    UpstreamResponseTooLargeError,
    UpstreamTransport,
    UpstreamUnavailableError,
)
from prometheus.webgateway.routing import (
    PathRejected,
    Route,
    RouteKind,
    match_route,
    raw_path_from_scope,
    rewrite_location,
    validate_query,
)
from prometheus.webgateway.static_files import StaticFileNotFoundError, resolve_static_file

Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]

ACCESS_LOGGER = logging.getLogger("prometheus.webgateway.access")
LOGGER = logging.getLogger("prometheus.webgateway")

_PROXIED_METHODS = frozenset({"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"})
_READ_METHODS = ("GET", "HEAD")
_HOP_BY_HOP = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
    }
)
_NOT_FORWARDED = frozenset(
    {
        "host",
        "content-length",
        "expect",
        "forwarded",
        "x-forwarded-for",
        "x-forwarded-host",
        "x-forwarded-proto",
        "x-forwarded-port",
        "x-real-ip",
        "x-request-id",
    }
)
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_MAX_HEADERS = 64
_MAX_HEADER_BYTES = 16_384


@dataclass(frozen=True, slots=True)
class GatewayConfig:
    max_request_body_bytes: int = 1_052_672
    max_response_bytes: int = 32 * 1024 * 1024
    upstream_timeout_seconds: float = 30.0
    body_timeout_seconds: float = 10.0
    max_upstream_inflight: int = 16
    rate_limit_per_second: float = 20.0
    rate_limit_burst: int = 100
    trusted_proxy_hops: int = 0

    def __post_init__(self) -> None:
        for name in (
            "max_request_body_bytes",
            "max_response_bytes",
            "max_upstream_inflight",
            "rate_limit_burst",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError(f"{name} must be a positive integer")
        if type(self.trusted_proxy_hops) is not int or not 0 <= self.trusted_proxy_hops <= 8:
            raise ValueError("trusted_proxy_hops must be an integer in [0,8]")
        for name in ("upstream_timeout_seconds", "body_timeout_seconds"):
            if not 0 < getattr(self, name) <= 600:
                raise ValueError(f"{name} must be in (0,600]")
        if self.rate_limit_per_second < 0:
            raise ValueError("rate_limit_per_second must be >= 0 (0 disables limiting)")


@dataclass(slots=True)
class _Response:
    status: int
    headers: HeaderList
    body: bytes
    is_html: bool = False
    route: str = "rejected"
    upstream_status: int | None = None
    upstream_request_id: str | None = None
    log: bool = True


class _ClientGone(Exception):
    pass


def _error(
    status: int,
    code: str,
    message: str,
    request_id: str,
    *,
    headers: HeaderList | None = None,
    route: str = "rejected",
) -> _Response:
    body = json.dumps(
        {"error": {"code": code, "message": message, "request_id": request_id}},
        sort_keys=True,
    ).encode("utf-8")
    out: HeaderList = [(b"content-type", b"application/json"), (b"cache-control", NO_STORE_CACHE)]
    out.extend(headers or [])
    return _Response(status, out, body, route=route)


class WebGatewayService:
    def __init__(
        self,
        dist_root: Path,
        jobs_url: str,
        dashboard_url: str,
        transport: UpstreamTransport | None = None,
        *,
        config: GatewayConfig | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config or GatewayConfig()
        self.dist_root = dist_root
        self.jobs_url = _origin_url(jobs_url)
        self.dashboard_url = _origin_url(dashboard_url)
        self.transport: UpstreamTransport = transport or HttpUpstreamTransport(
            max_response_bytes=self.config.max_response_bytes,
            allowed_origins=(self.jobs_url, self.dashboard_url),
        )
        self.limiter: TokenBucketLimiter | None = (
            TokenBucketLimiter(
                rate_per_second=self.config.rate_limit_per_second,
                burst=self.config.rate_limit_burst,
                clock=clock,
            )
            if self.config.rate_limit_per_second > 0
            else None
        )
        self._clock = clock
        self._executor = BoundedExecutor(self.config.max_upstream_inflight)
        self._denied_logged_at: dict[str, float] = {}

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
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            raise ValueError("this gateway serves HTTP only")
        started = time.monotonic()
        request_id = uuid.uuid4().hex
        method = str(scope.get("method", "GET")).upper()
        try:
            response = await self._handle(scope, receive, request_id, method)
        except _ClientGone:
            return
        except Exception:
            LOGGER.exception("unhandled gateway failure request_id=%s", request_id)
            response = _error(
                500, "internal_error", "unexpected gateway failure", request_id, route="error"
            )
        headers = finalize_headers(
            response.headers, https=scope.get("scheme") == "https", is_html=response.is_html
        )
        headers.append((b"x-gateway-request-id", request_id.encode("ascii")))
        headers.append((b"content-length", str(len(response.body)).encode("ascii")))
        await send({"type": "http.response.start", "status": response.status, "headers": headers})
        await send(
            {"type": "http.response.body", "body": b"" if method == "HEAD" else response.body}
        )
        if response.log:
            self._log_access(scope, method, request_id, response, started)

    async def _handle(
        self, scope: dict[str, Any], receive: Receive, request_id: str, method: str
    ) -> _Response:
        route: Route | None = None
        rejection: PathRejected | None = None
        query = ""
        try:
            route = match_route(raw_path_from_scope(scope))
            query = validate_query(scope.get("query_string", b""))
        except PathRejected as exc:
            rejection = exc
        peer = self._peer_ip(scope)
        client = client_key(peer)
        if (route is None or route.kind is not RouteKind.HEALTH) and self.limiter is not None:
            decision = self.limiter.acquire(client)
            if not decision.allowed:
                return self._rate_limited(client, decision.retry_after_seconds, request_id)
        if rejection is not None or route is None:
            return _error(
                400, "invalid_request_target", str(rejection or "invalid request"), request_id
            )
        if route.kind is RouteKind.HEALTH:
            return self._health(method, request_id)
        if route.kind is RouteKind.UNKNOWN_API:
            return _error(404, "not_found", "endpoint was not found", request_id, route="api")
        if route.kind is RouteKind.STATIC:
            return await self._static(method, route, request_id)
        if method not in _PROXIED_METHODS:
            return _error(
                405,
                "method_not_allowed",
                "method is not supported",
                request_id,
                headers=[(b"allow", ", ".join(sorted(_PROXIED_METHODS)).encode("ascii"))],
            )
        return await self._proxy(
            scope, receive, route, query, method, peer or "unknown", request_id
        )

    def _health(self, method: str, request_id: str) -> _Response:
        if method not in _READ_METHODS:
            return _error(
                405,
                "method_not_allowed",
                "GET or HEAD is required",
                request_id,
                headers=[(b"allow", b"GET, HEAD")],
                route="health",
            )
        return _Response(
            200,
            [(b"content-type", b"text/plain; charset=utf-8"), (b"cache-control", NO_STORE_CACHE)],
            b"live",
            route="health",
        )

    async def _static(self, method: str, route: Route, request_id: str) -> _Response:
        if method not in _READ_METHODS:
            return _error(
                405,
                "method_not_allowed",
                "GET or HEAD is required",
                request_id,
                headers=[(b"allow", b"GET, HEAD")],
                route="static",
            )
        try:
            static = await asyncio.to_thread(resolve_static_file, self.dist_root, route.target)
        except StaticFileNotFoundError:
            return _error(404, "not_found", "no such file", request_id, route="static")
        immutable = not static.is_spa_fallback and static.relative_path.startswith("assets/")
        return _Response(
            200,
            [
                (b"content-type", static.content_type.encode("ascii")),
                (b"cache-control", IMMUTABLE_CACHE if immutable else REVALIDATE_CACHE),
            ],
            static.body,
            is_html=static.is_html,
            route="static",
        )

    async def _proxy(
        self,
        scope: dict[str, Any],
        receive: Receive,
        route: Route,
        query: str,
        method: str,
        peer: str,
        request_id: str,
    ) -> _Response:
        name = f"proxy:{route.kind.value}"
        base = self.jobs_url if route.kind is RouteKind.JOBS else self.dashboard_url
        url = base + route.target + (f"?{query}" if query else "")
        if _authority(url) != _authority(base):
            # Unreachable for a validated route; asserted anyway because the
            # cost of being wrong is a server-side request forgery.
            LOGGER.error("refusing upstream URL whose authority differs request_id=%s", request_id)
            return _error(500, "internal_error", "unexpected gateway failure", request_id)
        try:
            headers = _forward_headers(scope, peer, request_id)
        except PathRejected as exc:
            return _error(400, "invalid_headers", str(exc), request_id, route=name)
        too_large = _error(
            413, "body_too_large", "request body exceeds byte budget", request_id, route=name
        )
        declared = _declared_length(scope)
        if declared is not None and declared > self.config.max_request_body_bytes:
            return too_large
        try:
            body = await asyncio.wait_for(
                self._read_body(receive), timeout=self.config.body_timeout_seconds
            )
        except TimeoutError:
            return _error(
                408, "body_timeout", "request body read deadline expired", request_id, route=name
            )
        if body is None:
            return too_large
        try:
            upstream: UpstreamResponse = await self._executor.run(
                self.transport.request,
                method,
                url,
                headers,
                body,
                timeout=self.config.upstream_timeout_seconds,
            )
        except Overloaded:
            return _error(
                503,
                "overloaded",
                "upstream concurrency capacity is exhausted",
                request_id,
                headers=[(b"retry-after", b"1")],
                route=name,
            )
        except UpstreamResponseTooLargeError:
            LOGGER.warning("upstream response too large request_id=%s route=%s", request_id, name)
            return _error(
                502,
                "upstream_response_too_large",
                "upstream response is too large",
                request_id,
                route=name,
            )
        except UpstreamUnavailableError as exc:
            LOGGER.warning("upstream unavailable request_id=%s route=%s: %s", request_id, name, exc)
            return _error(
                502, "upstream_unavailable", "upstream unavailable", request_id, route=name
            )
        except UpstreamRequestError:
            return _error(
                400, "invalid_request", "request cannot be forwarded", request_id, route=name
            )
        return self._relay(upstream, route, base, name)

    def _relay(self, upstream: UpstreamResponse, route: Route, base: str, name: str) -> _Response:
        headers: HeaderList = []
        upstream_request_id: str | None = None
        for raw_name, value in upstream.headers:
            lowered = raw_name.lower()
            # `date` is dropped too: this gateway's own server stamps one, and a
            # response with two Date headers is malformed.
            if lowered in _HOP_BY_HOP or lowered in ("content-length", "date"):
                continue
            if lowered == "location":
                value = rewrite_location(value, route.kind, base)
            if lowered == "x-request-id":
                upstream_request_id = value[:128]
            headers.append((lowered.encode("ascii", "replace"), value.encode("latin-1", "replace")))
        set_default_header(headers, b"cache-control", NO_STORE_CACHE)
        return _Response(
            upstream.status,
            headers,
            upstream.body,
            route=name,
            upstream_status=upstream.status,
            upstream_request_id=upstream_request_id,
        )

    async def _read_body(self, receive: Receive) -> bytes | None:
        """The whole request body, or None once it exceeds the budget."""
        limit = self.config.max_request_body_bytes
        output = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                raise _ClientGone()
            if message["type"] != "http.request":
                return None
            output.extend(message.get("body", b""))
            if len(output) > limit:
                return None
            if not message.get("more_body", False):
                return bytes(output)

    def _peer_ip(self, scope: dict[str, Any]) -> str | None:
        peer = scope.get("client")
        host: str | None = peer[0] if peer else None
        hops = self.config.trusted_proxy_hops
        if hops:
            for name, value in scope.get("headers", []):
                if name == b"x-forwarded-for":
                    chain = [p.strip() for p in value.decode("latin-1").split(",") if p.strip()]
                    if len(chain) >= hops and _is_ip(chain[-hops]):
                        host = chain[-hops]
                    break
        return host

    def _rate_limited(self, client: str, retry_after: float, request_id: str) -> _Response:
        response = _error(
            429,
            "rate_limited",
            "request rate budget is exhausted",
            request_id,
            headers=[(b"retry-after", str(max(1, int(retry_after) + 1)).encode("ascii"))],
            route="rate_limited",
        )
        # One log line per denied client per second: an attacker's request
        # rate must not become the log volume.
        now = self._clock()
        last = self._denied_logged_at.get(client)
        response.log = last is None or now - last >= 1.0
        if response.log:
            if len(self._denied_logged_at) >= 1024:
                self._denied_logged_at.clear()
            self._denied_logged_at[client] = now
        return response

    def _log_access(
        self,
        scope: dict[str, Any],
        method: str,
        request_id: str,
        response: _Response,
        started: float,
    ) -> None:
        event = {
            "event": "gateway_request",
            "request_id": request_id,
            "method": method[:16],
            "path": str(scope.get("path", ""))[:200],
            "status": response.status,
            "route": response.route,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "bytes": len(response.body),
            "client": client_key(self._peer_ip(scope)),
            "upstream_status": response.upstream_status,
            "upstream_request_id": response.upstream_request_id,
        }
        ACCESS_LOGGER.info(json.dumps(event, sort_keys=True))


def _is_ip(text: str) -> bool:
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def _declared_length(scope: dict[str, Any]) -> int | None:
    for name, value in scope.get("headers", []):
        if name == b"content-length":
            text = value.decode("latin-1")
            return int(text) if text.isascii() and text.isdigit() else None
    return None


def _forward_headers(
    scope: dict[str, Any], peer: str, request_id: str
) -> tuple[tuple[str, str], ...]:
    raw = scope.get("headers", [])
    if len(raw) > _MAX_HEADERS or sum(len(k) + len(v) for k, v in raw) > _MAX_HEADER_BYTES:
        raise PathRejected("request headers exceed budget")
    named_hop_by_hop: set[str] = set()
    for name, value in raw:
        if name.lower() == b"connection":
            named_hop_by_hop.update(
                token.strip().lower()
                for token in value.decode("latin-1").split(",")
                if _TOKEN.fullmatch(token.strip())
            )
    forwarded: list[tuple[str, str]] = []
    for raw_name, raw_value in raw:
        name = raw_name.decode("latin-1")
        value = raw_value.decode("latin-1")
        lowered = name.lower()
        if _TOKEN.fullmatch(name) is None or any(
            (ord(char) < 0x20 and char != "\t") or ord(char) == 0x7F for char in value
        ):
            raise PathRejected("request headers are malformed")
        if lowered in _HOP_BY_HOP or lowered in _NOT_FORWARDED or lowered in named_hop_by_hop:
            continue
        forwarded.append((lowered, value))
    forwarded.append(("x-forwarded-for", peer))
    forwarded.append(("x-forwarded-proto", "https" if scope.get("scheme") == "https" else "http"))
    forwarded.append(("x-request-id", request_id))
    return tuple(forwarded)


def _origin_url(url: str) -> str:
    parts = urlsplit(url)
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
        or parts.query
        or parts.fragment
        or parts.path not in ("", "/")
    ):
        raise ValueError(f"upstream URL must be a bare http(s)://host[:port] origin: {url!r}")
    return f"{parts.scheme}://{parts.netloc}"


def _authority(url: str) -> tuple[str, str]:
    parts = urlsplit(url)
    return parts.scheme, parts.netloc
