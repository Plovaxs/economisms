"""Bounded ASGI HTTP application for authenticated, owner-scoped research jobs.

Use a real ASGI protocol server. Workers run separately. Application limits
are process-local; ingress TLS/connection limits and distributed rate limits
are separate deployment responsibilities.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import logging
import math
import os
import re
import sqlite3
import threading
import time
import uuid
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs

from jsonschema import Draft202012Validator, FormatChecker

from prometheus.evidence.jsonio import strict_json_loads
from prometheus.jobs.__main__ import job_response
from prometheus.jobs.artifacts import ArtifactError, ArtifactStore
from prometheus.jobs.store import (
    IdempotencyConflict,
    JobError,
    JobNotFound,
    JobStorageError,
    JobStore,
    QuotaExceeded,
)
from prometheus.orchestration.recipes import ResourceLimitError, _check_raw
from prometheus.service.auth import (
    AuthenticationError,
    CredentialStore,
    CredentialUnavailable,
    Principal,
)
from prometheus.service.schema import openapi_document

LOGGER = logging.getLogger("prometheus.service.audit")
Receive = Callable[[], Awaitable[dict[str, Any]]]
Send = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class ServicePolicy:
    max_body_bytes: int = 1_052_672
    max_header_bytes: int = 16_384
    max_headers: int = 64
    max_inflight: int = 8
    requests_per_owner: int = 120
    requests_global: int = 1200
    rate_window_seconds: float = 60.0
    body_timeout_seconds: float = 10.0
    allow_loopback_http: bool = True

    def __post_init__(self) -> None:
        for name in (
            "max_body_bytes",
            "max_header_bytes",
            "max_headers",
            "max_inflight",
            "requests_per_owner",
            "requests_global",
        ):
            if type(getattr(self, name)) is not int or getattr(self, name) < 1:
                raise ValueError("service capacities must be positive integers")
        for value in (self.rate_window_seconds, self.body_timeout_seconds):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                or not 0 < value <= 3600
            ):
                raise ValueError("service timing limits must be finite seconds in (0,3600]")
        if type(self.allow_loopback_http) is not bool:
            raise ValueError("allow_loopback_http must be boolean")


class HTTPError(ValueError):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        field: str | None = None,
        *,
        allow: str | None = None,
    ) -> None:
        self.status, self.code, self.message, self.field = status, code, message, field
        self.allow = allow


class ClientDisconnected(Exception):
    pass


class Admission:
    def __init__(self, policy: ServicePolicy, clock: Callable[[], float]) -> None:
        self.policy, self.clock = policy, clock
        self.lock = threading.Lock()
        self.inflight = 0
        self.buckets: dict[str, deque[float]] = {}

    def rate(self, key: str, capacity: int) -> None:
        now = self.clock()
        with self.lock:
            cutoff = now - self.policy.rate_window_seconds
            for item in list(self.buckets):
                bucket = self.buckets[item]
                while bucket and bucket[0] <= cutoff:
                    bucket.popleft()
                if not bucket:
                    del self.buckets[item]
            if key not in self.buckets and len(self.buckets) >= 257:
                raise HTTPError(429, "rate_limited", "request rate budget is exhausted")
            bucket = self.buckets.setdefault(key, deque())
            if len(bucket) >= capacity:
                raise HTTPError(429, "rate_limited", "request rate budget is exhausted")
            bucket.append(now)

    def enter(self) -> None:
        with self.lock:
            if self.inflight >= self.policy.max_inflight:
                raise HTTPError(503, "overloaded", "request concurrency capacity is exhausted")
            self.inflight += 1

    def leave(self) -> None:
        with self.lock:
            self.inflight -= 1


class ResearchService:
    def __init__(
        self,
        jobs: JobStore,
        artifacts: ArtifactStore,
        credentials: CredentialStore,
        *,
        policy: ServicePolicy | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if (
            artifacts.max_bytes != jobs.policy.max_artifact_bytes
            or artifacts.max_total_bytes != jobs.policy.max_store_bytes
        ):
            raise ValueError("service artifact limits must match persisted queue policy")
        self.jobs, self.artifacts, self.credentials = jobs, artifacts, credentials
        self.policy = policy or ServicePolicy()
        self.admission = Admission(self.policy, clock)
        self.document = openapi_document()
        self.validators = {
            item["properties"]["kind"]["const"]: Draft202012Validator(
                item, format_checker=FormatChecker()
            )
            for item in self.document["components"]["schemas"]["Submission"]["oneOf"]
        }
        self.pending: set[asyncio.Task[Any]] = set()
        self.draining = False

    async def __call__(self, scope: dict[str, Any], receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    self.draining = True
                    if self.pending:
                        await asyncio.gather(*self.pending, return_exceptions=True)
                    await send({"type": "lifespan.shutdown.complete"})
                    return
            return
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008})
            return
        if scope["type"] != "http":
            raise ValueError("unsupported ASGI scope")
        request_id = uuid.uuid4().hex
        try:
            if self.draining and scope["path"] != "/health/live":
                raise HTTPError(503, "shutting_down", "service is draining existing requests")
            self.admission.rate("global", self.policy.requests_global)
            self.admission.enter()
        except HTTPError as exc:
            status, body, extra = self._error(exc, request_id)
        else:
            # Keep capacity until underlying thread work finishes, even after caller cancellation.
            task = asyncio.create_task(self._process(scope, receive, request_id))
            self.pending.add(task)

            def finished(completed: asyncio.Task[Any]) -> None:
                self.pending.discard(completed)
                self.admission.leave()
                if not completed.cancelled():
                    completed.exception()

            task.add_done_callback(finished)
            try:
                status, body, extra = await asyncio.shield(task)
            except ClientDisconnected:
                return
        headers = [
            (b"content-type", b"application/json"),
            (b"cache-control", b"no-store"),
            (b"x-content-type-options", b"nosniff"),
            (b"x-request-id", request_id.encode("ascii")),
        ]
        data = json.dumps(body, sort_keys=True, allow_nan=False).encode("utf-8")
        headers.extend(extra)
        headers.append((b"content-length", str(len(data)).encode("ascii")))
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": data})

    @staticmethod
    def _log(
        request_id: str,
        status: int,
        code: str,
        principal: Principal | None,
        job: dict[str, Any] | None = None,
        diagnostic_id: str | None = None,
    ) -> None:
        event = {
            "event": "service_request",
            "request_id": request_id,
            "status": status,
            "code": code,
            "subject": principal.subject if principal else None,
            "job_id": job.get("job_id") if job else None,
            "job_trace_id": job.get("trace_id") if job else None,
            "diagnostic_id": diagnostic_id,
        }
        LOGGER.info(json.dumps(event, sort_keys=True))

    def _error(
        self, exc: HTTPError, request_id: str, principal: Principal | None = None
    ) -> tuple[int, dict[str, Any], list[tuple[bytes, bytes]]]:
        diagnostic = uuid.uuid4().hex
        body = {
            "error": {
                "code": exc.code,
                "message": exc.message,
                "request_id": request_id,
                "diagnostic_id": diagnostic,
                "field": exc.field,
            }
        }
        headers = []
        if exc.status == 401:
            headers.append((b"www-authenticate", b"Bearer"))
        if exc.allow is not None:
            headers.append((b"allow", exc.allow.encode("ascii")))
        if exc.status in (429, 503):
            headers.append(
                (b"retry-after", str(math.ceil(self.policy.rate_window_seconds)).encode())
            )
        self._log(request_id, exc.status, exc.code, principal, diagnostic_id=diagnostic)
        return exc.status, body, headers

    def _headers(self, scope: dict[str, Any]) -> dict[str, str]:
        raw = scope.get("headers", [])
        if len(raw) > self.policy.max_headers or sum(len(k) + len(v) for k, v in raw) > (
            self.policy.max_header_bytes
        ):
            raise HTTPError(431, "headers_too_large", "request headers exceed budget")
        headers = {}
        for key, value in raw:
            try:
                name, text = key.decode("ascii").lower(), value.decode("ascii")
            except UnicodeError as exc:
                raise HTTPError(400, "invalid_headers", "headers must use ASCII") from exc
            if (
                name in headers
                or re.fullmatch(r"[a-z0-9!#$%&'*+.^_`|~-]+", name) is None
                or any(ord(c) < 32 or ord(c) == 127 for c in text)
            ):
                raise HTTPError(400, "invalid_headers", "duplicate or malformed headers")
            headers[name] = text
        return headers

    async def _body(self, receive: Receive, headers: dict[str, str]) -> bytes:
        length = headers.get("content-length")
        if length is not None and re.fullmatch(r"[0-9]{1,8}", length) is None:
            raise HTTPError(400, "invalid_length", "invalid Content-Length")
        if length is not None and int(length) > self.policy.max_body_bytes:
            raise HTTPError(413, "body_too_large", "request body exceeds byte budget")
        if ("transfer-encoding" in headers and length is not None) or headers.get(
            "content-encoding", "identity"
        ) != "identity":
            raise HTTPError(400, "invalid_encoding", "ambiguous framing or unsupported encoding")

        async def collect() -> bytes:
            output = bytearray()
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    raise ClientDisconnected()
                if message["type"] != "http.request":
                    raise HTTPError(400, "invalid_body", "invalid request body message")
                chunk = message.get("body", b"")
                if len(output) + len(chunk) > self.policy.max_body_bytes:
                    raise HTTPError(413, "body_too_large", "request body exceeds byte budget")
                output.extend(chunk)
                if not message.get("more_body", False):
                    break
            if length is not None and len(output) != int(length):
                raise HTTPError(
                    400, "invalid_length", "Content-Length does not match received bytes"
                )
            return bytes(output)

        try:
            return await asyncio.wait_for(collect(), timeout=self.policy.body_timeout_seconds)
        except TimeoutError as exc:
            raise HTTPError(408, "body_timeout", "request body read deadline expired") from exc

    async def _process(
        self, scope: dict[str, Any], receive: Receive, request_id: str
    ) -> tuple[int, dict[str, Any], list[tuple[bytes, bytes]]]:
        principal = None
        try:
            headers = self._headers(scope)
            client = scope.get("client")
            loopback = False
            if client is not None:
                try:
                    loopback = ipaddress.ip_address(client[0]).is_loopback
                except ValueError:
                    pass
            if scope.get("scheme") != "https" and not (
                self.policy.allow_loopback_http and loopback
            ):
                raise HTTPError(403, "tls_required", "HTTPS is required outside loopback")
            path, method = scope["path"], scope["method"]
            if len(path) > 2048 or len(scope.get("query_string", b"")) > 2048:
                raise HTTPError(414, "target_too_large", "request target exceeds budget")
            public = path in ("/health/live", "/health/ready")
            if not public:
                principal = await asyncio.to_thread(
                    self.credentials.authenticate, headers.get("authorization")
                )
                self.admission.rate("owner:" + principal.owner, self.policy.requests_per_owner)
                if method != "GET" and "write" not in principal.scopes:
                    raise HTTPError(403, "forbidden", "write scope is required")
            raw = await self._body(receive, headers)
            if raw and not (path == "/v1/jobs" and method == "POST"):
                raise HTTPError(400, "unexpected_body", "this endpoint accepts no request body")
            status, body, extra = await asyncio.to_thread(
                self._dispatch,
                path,
                method,
                scope.get("query_string", b""),
                headers,
                raw,
                principal,
            )
            job = body if "job_id" in body else body.get("job_context")
            self._log(request_id, status, "ok", principal, job)
            return status, body, extra
        except ClientDisconnected:
            self._log(request_id, 499, "client_disconnected", principal)
            raise
        except AuthenticationError:
            error = HTTPError(401, "unauthorized", "valid bearer credentials are required")
        except (CredentialUnavailable, JobStorageError, sqlite3.Error, OSError):
            error = HTTPError(503, "dependency_unavailable", "service dependency is unavailable")
        except JobNotFound:
            error = HTTPError(404, "not_found", "job was not found")
        except IdempotencyConflict:
            error = HTTPError(409, "idempotency_conflict", "key identifies a different request")
        except QuotaExceeded:
            error = HTTPError(429, "quota_exceeded", "pending job capacity is exhausted")
        except ResourceLimitError:
            error = HTTPError(
                422, "resource_limit", "recipe exceeds admitted resource budget", "config"
            )
        except HTTPError as exc:
            error = exc
        except ArtifactError:
            error = HTTPError(
                503, "artifact_unavailable", "artifact failed availability/integrity checks"
            )
        except (JobError, ValueError, TypeError, OverflowError, RecursionError):
            error = HTTPError(
                422, "invalid_recipe", "request failed typed semantic validation", "config"
            )
        except Exception:
            error = HTTPError(500, "internal_error", "unexpected service failure")
        return self._error(error, request_id, principal)

    def _dispatch(
        self,
        path: str,
        method: str,
        query: bytes,
        headers: dict[str, str],
        raw: bytes,
        principal: Principal | None,
    ) -> tuple[int, dict[str, Any], list[tuple[bytes, bytes]]]:
        if path in ("/health/live", "/health/ready"):
            if method != "GET":
                raise HTTPError(405, "method_not_allowed", "GET is required", allow="GET")
            if query:
                raise HTTPError(400, "invalid_query", "unexpected query parameters")
            if path == "/health/ready":
                self.credentials.check_ready()
                self.jobs.check_ready()
                if not self.artifacts.root.is_dir() or not os.access(
                    self.artifacts.root, os.R_OK | os.W_OK | os.X_OK
                ):
                    raise OSError("artifact storage is unavailable")
            return 200, {"status": "live" if path.endswith("live") else "ready"}, []
        if principal is None:
            raise AuthenticationError()
        if path == "/v1/openapi.json":
            if method != "GET":
                raise HTTPError(405, "method_not_allowed", "GET is required", allow="GET")
            if query:
                raise HTTPError(400, "invalid_query", "unexpected query parameters")
            return 200, self.document, []
        if path == "/v1/jobs" and method == "POST":
            if query:
                raise HTTPError(400, "invalid_query", "unexpected query parameters")
            if headers.get("content-type", "").lower() not in (
                "application/json",
                "application/json; charset=utf-8",
            ):
                raise HTTPError(415, "unsupported_media_type", "application/json is required")
            key = headers.get("idempotency-key")
            if key is None or re.fullmatch(r"[A-Za-z0-9._:@-]{1,128}", key) is None:
                raise HTTPError(
                    400, "invalid_idempotency_key", "a bounded Idempotency-Key is required"
                )
            try:
                body = strict_json_loads(raw.decode("utf-8"))
            except (ValueError, UnicodeError, RecursionError) as exc:
                raise HTTPError(
                    400, "invalid_json", "a strict UTF-8 JSON object is required"
                ) from exc
            _check_raw(body, self.jobs.limits)  # Bound recursion/work before schema traversal.
            if (
                not isinstance(body, dict)
                or not isinstance(body.get("kind"), str)
                or body["kind"] not in self.validators
            ):
                raise HTTPError(
                    422, "invalid_kind", "an allowlisted runner kind is required", "kind"
                )
            failure = next(self.validators[body["kind"]].iter_errors(body), None)
            if failure is not None:
                field = ".".join(str(part) for part in failure.absolute_path) or "$"
                raise HTTPError(
                    422,
                    "schema_error",
                    "wire schema constraint failed: " + failure.validator,
                    field[:256],
                )
            job = self.jobs.submit(
                body["kind"],
                body["config"],
                owner=principal.owner,
                idempotency_key=key,
                timeout_seconds=body.get("timeout_seconds"),
            )
            return 202, job_response(job), [(b"location", f"/v1/jobs/{job.job_id}".encode())]
        if path == "/v1/jobs" and method == "GET":
            try:
                pairs = parse_qs(
                    query.decode("ascii"),
                    keep_blank_values=True,
                    strict_parsing=True,
                    max_num_fields=2,
                )
                if set(pairs) - {"limit", "cursor"} or any(len(v) != 1 for v in pairs.values()):
                    raise ValueError()
                limit = pairs.get("limit", ["50"])[0]
                if re.fullmatch(r"[0-9]{1,3}", limit) is None:
                    raise ValueError()
                jobs, cursor = self.jobs.list_jobs(
                    owner=principal.owner, limit=int(limit), cursor=pairs.get("cursor", [None])[0]
                )
            except (ValueError, UnicodeError) as exc:
                if isinstance(exc, (JobStorageError, sqlite3.Error)):
                    raise
                raise HTTPError(
                    400, "invalid_query", "invalid limit or owner-scoped cursor"
                ) from exc
            return 200, {"jobs": [job_response(job) for job in jobs], "next_cursor": cursor}, []
        match = re.fullmatch(r"/v1/jobs/([a-f0-9-]{36})(/cancel|/artifact)?", path)
        if match:
            identifier, action = match.groups()
            try:
                if str(uuid.UUID(identifier)) != identifier:
                    raise ValueError()
            except ValueError as exc:
                raise HTTPError(404, "not_found", "endpoint was not found") from exc
            if query:
                raise HTTPError(400, "invalid_query", "unexpected query parameters")
            allowed = "POST" if action == "/cancel" else "GET"
            if method != allowed:
                raise HTTPError(405, "method_not_allowed", allowed + " is required", allow=allowed)
            if action == "/cancel":
                return 200, job_response(self.jobs.cancel(identifier, owner=principal.owner)), []
            job = self.jobs.get(identifier, owner=principal.owner)
            if action == "/artifact":
                if job.artifact_sha256 is None:
                    raise HTTPError(409, "artifact_pending", "job has no published artifact")
                artifact = self.artifacts.get(job.artifact_sha256)
                context = artifact.get("job_context", {})
                if (
                    any(
                        context.get(key) != value
                        for key, value in {
                            "job_id": job.job_id,
                            "trace_id": job.trace_id,
                            "kind": job.kind,
                            "recipe_sha256": job.recipe_sha256,
                            "attempt": job.attempts,
                        }.items()
                    )
                    or artifact["run_manifest"]["result_hash"] != job.result_hash
                ):
                    raise ArtifactError("job/artifact lineage differs")
                # Strong ETag identifies these exact response bytes, not the unsigned content seal.
                data = json.dumps(artifact, sort_keys=True, allow_nan=False).encode("utf-8")
                etag = '"' + hashlib.sha256(data).hexdigest() + '"'
                return 200, artifact, [(b"etag", etag.encode("ascii"))]
            return 200, job_response(job), []
        if path == "/v1/jobs":
            raise HTTPError(405, "method_not_allowed", "GET or POST is required", allow="GET, POST")
        raise HTTPError(404, "not_found", "endpoint was not found")
