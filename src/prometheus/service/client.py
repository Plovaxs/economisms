"""Typed synchronous v1 client with bounded reads and no credential redirects.

No automatic submission retries: callers reuse their idempotency key after
uncertain transport outcomes. TLS certificate verification uses Python's
default context. Environment proxy settings are deliberately not inherited.
"""

from __future__ import annotations

import ipaddress
import json
import math
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from http.client import HTTPException
from types import MappingProxyType
from typing import Any, Literal, cast
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from prometheus.evidence.jsonio import strict_json_loads
from prometheus.evidence.verify import audit_evidence_bundle

JobStatus = Literal["queued", "running", "succeeded", "failed", "cancelled", "timed_out"]
_STATUSES = {"queued", "running", "succeeded", "failed", "cancelled", "timed_out"}


class ClientProtocolError(ValueError):
    pass


class ClientTransportError(OSError):
    pass


class ServiceError(ValueError):
    def __init__(self, status: int, code: str, diagnostic_id: str, request_id: str) -> None:
        self.status, self.code = status, code
        self.diagnostic_id, self.request_id = diagnostic_id, request_id
        super().__init__(f"HTTP {status}: {code}; diagnostic_id={diagnostic_id}")


def _identifier(value: str) -> str:
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError("job ID must be a canonical UUID")
    return value


@dataclass(frozen=True, slots=True)
class JobSnapshot:
    job_id: str
    trace_id: str
    kind: str
    status: JobStatus
    created_at: datetime
    updated_at: datetime
    recipe_sha256: str
    attempts: int
    cancel_requested: bool
    timeout_seconds: float
    resource_estimate: Mapping[str, int]
    artifact_sha256: str | None
    result_hash: str | None
    error_code: str | None
    diagnostic_id: str | None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> JobSnapshot:
        try:
            _identifier(raw["job_id"])
            if (
                raw["status"] not in _STATUSES
                or re.fullmatch(r"[a-f0-9]{32}", raw["trace_id"]) is None
            ):
                raise ValueError()
            created = datetime.fromisoformat(raw["created_at"])
            updated = datetime.fromisoformat(raw["updated_at"])
            if created.tzinfo is None or updated.tzinfo is None:
                raise ValueError()
            for name in ("recipe_sha256", "artifact_sha256", "result_hash"):
                if name != "recipe_sha256" and raw[name] is None:
                    continue
                if (
                    not isinstance(raw[name], str)
                    or re.fullmatch(r"[a-f0-9]{64}", raw[name]) is None
                ):
                    raise ValueError()
            if (
                not isinstance(raw["kind"], str)
                or type(raw["attempts"]) is not int
                or raw["attempts"] < 0
                or type(raw["cancel_requested"]) is not bool
                or isinstance(raw["timeout_seconds"], bool)
                or not isinstance(raw["timeout_seconds"], (int, float))
                or not math.isfinite(raw["timeout_seconds"])
                or raw["timeout_seconds"] <= 0
                or not isinstance(raw["resource_estimate"], dict)
                or any(
                    type(value) is not int or value < 0
                    for value in raw["resource_estimate"].values()
                )
                or any(
                    raw[name] is not None and not isinstance(raw[name], str)
                    for name in ("error_code", "diagnostic_id")
                )
            ):
                raise ValueError()
            return cls(
                raw["job_id"],
                raw["trace_id"],
                raw["kind"],
                cast(JobStatus, raw["status"]),
                created,
                updated,
                raw["recipe_sha256"],
                raw["attempts"],
                raw["cancel_requested"],
                float(raw["timeout_seconds"]),
                MappingProxyType(dict(raw["resource_estimate"])),
                raw["artifact_sha256"],
                raw["result_hash"],
                raw["error_code"],
                raw["diagnostic_id"],
            )
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise ClientProtocolError("invalid v1 job response") from exc


@dataclass(frozen=True, slots=True)
class JobPage:
    jobs: tuple[JobSnapshot, ...]
    next_cursor: str | None


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


class ResearchClient:
    def __init__(
        self,
        origin: str,
        token: str,
        *,
        timeout_seconds: float = 15.0,
        max_response_bytes: int = 134_217_728,
    ) -> None:
        parsed = urlsplit(origin)
        try:
            loopback = ipaddress.ip_address(parsed.hostname or "").is_loopback
        except ValueError:
            loopback = False
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or (parsed.scheme == "http" and not loopback)
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.path not in ("", "/")
            or any(ord(c) < 33 for c in origin)
        ):
            raise ValueError(
                "origin requires HTTPS, or HTTP with a loopback IP, and no path/credentials"
            )
        if not isinstance(token, str) or re.fullmatch(r"[A-Za-z0-9_-]{43,128}", token) is None:
            raise ValueError("a bounded bearer token is required")
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not 0 < timeout_seconds <= 3600
            or type(max_response_bytes) is not int
            or not 1 <= max_response_bytes <= 1_073_741_824
        ):
            raise ValueError("client timeout/response budget is invalid")
        self.origin, self._token = origin.rstrip("/"), token
        self.timeout_seconds, self.max_response_bytes = timeout_seconds, max_response_bytes
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def _decode(self, response: Any) -> dict[str, Any]:
        if response.headers.get_content_type() != "application/json":
            raise ClientProtocolError("service response must be JSON")
        length = response.headers.get("Content-Length")
        if length is not None and (
            not length.isdigit() or len(length) > 10 or int(length) > self.max_response_bytes
        ):
            raise ClientProtocolError("response exceeds byte budget or has invalid length")
        data = response.read(self.max_response_bytes + 1)
        if len(data) > self.max_response_bytes or (length is not None and len(data) != int(length)):
            raise ClientProtocolError("response exceeds byte budget or has incomplete content")
        try:
            result = strict_json_loads(data.decode("utf-8"))
        except (ValueError, UnicodeError, RecursionError) as exc:
            raise ClientProtocolError("invalid response JSON") from exc
        if not isinstance(result, dict):
            raise ClientProtocolError("response must be a JSON object")
        return result

    def _request(
        self, method: str, path: str, *, body: dict[str, Any] | None = None, key: str | None = None
    ) -> dict[str, Any]:
        headers = {"Authorization": "Bearer " + self._token, "Accept": "application/json"}
        if key is not None:
            if not isinstance(key, str) or re.fullmatch(r"[A-Za-z0-9._:@-]{1,128}", key) is None:
                raise ValueError("a bounded idempotency key is required")
            headers["Idempotency-Key"] = key
        data = None
        if body is not None:
            data = json.dumps(body, allow_nan=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = Request(self.origin + path, data=data, headers=headers, method=method)
        try:
            with self._opener.open(request, timeout=self.timeout_seconds) as response:
                return self._decode(response)
        except HTTPError as exc:
            with exc:
                error = self._decode(exc).get("error")
            if not isinstance(error, dict) or any(
                not isinstance(error.get(name), str) or re.fullmatch(pattern, error[name]) is None
                for name, pattern in (
                    ("code", r"[a-z_]{1,64}"),
                    ("request_id", r"[a-f0-9]{32}"),
                    ("diagnostic_id", r"[a-f0-9]{32}"),
                )
            ):
                raise ClientProtocolError("invalid service error envelope") from None
            raise ServiceError(
                exc.code, error["code"], error["diagnostic_id"], error["request_id"]
            ) from None
        except (URLError, TimeoutError, ConnectionError, OSError, HTTPException) as exc:
            raise ClientTransportError(
                "service transport failed; submission outcome may be unknown"
            ) from exc

    def submit(
        self,
        kind: str,
        config: Mapping[str, Any],
        *,
        idempotency_key: str,
        timeout_seconds: float | None = None,
    ) -> JobSnapshot:
        body: dict[str, Any] = {"kind": kind, "config": dict(config)}
        if timeout_seconds is not None:
            body["timeout_seconds"] = timeout_seconds
        return JobSnapshot.from_dict(
            self._request("POST", "/v1/jobs", body=body, key=idempotency_key)
        )

    def get_job(self, job_id: str) -> JobSnapshot:
        return JobSnapshot.from_dict(self._request("GET", "/v1/jobs/" + _identifier(job_id)))

    def cancel_job(self, job_id: str) -> JobSnapshot:
        return JobSnapshot.from_dict(
            self._request("POST", "/v1/jobs/" + _identifier(job_id) + "/cancel")
        )

    def list_jobs(self, *, limit: int = 50, cursor: str | None = None) -> JobPage:
        if (
            type(limit) is not int
            or not 1 <= limit <= 100
            or (cursor is not None and (not isinstance(cursor, str) or len(cursor) > 1024))
        ):
            raise ValueError("invalid page limit/cursor")
        query: dict[str, str | int] = {"limit": limit}
        if cursor is not None:
            query["cursor"] = cursor
        raw = self._request("GET", "/v1/jobs?" + urlencode(query))
        if (
            not isinstance(raw.get("jobs"), list)
            or len(raw["jobs"]) > limit
            or (
                raw.get("next_cursor") is not None
                and (not isinstance(raw["next_cursor"], str) or len(raw["next_cursor"]) > 1024)
            )
        ):
            raise ClientProtocolError("invalid job page response")
        return JobPage(
            tuple(JobSnapshot.from_dict(job) for job in raw["jobs"]), raw.get("next_cursor")
        )

    def get_artifact(self, job_id: str) -> dict[str, Any]:
        job = self.get_job(job_id)
        artifact = self._request("GET", "/v1/jobs/" + _identifier(job_id) + "/artifact")
        try:
            audit = audit_evidence_bundle(artifact, expected_sha256=job.artifact_sha256)
        except (ValueError, TypeError) as exc:
            raise ClientProtocolError("artifact failed integrity/metadata verification") from exc
        context = artifact.get("job_context", {})
        if (
            job.artifact_sha256 is None
            or audit.result_hash != job.result_hash
            or any(
                context.get(key) != value
                for key, value in {
                    "job_id": job.job_id,
                    "trace_id": job.trace_id,
                    "recipe_sha256": job.recipe_sha256,
                    "kind": job.kind,
                    "attempt": job.attempts,
                }.items()
            )
        ):
            raise ClientProtocolError("artifact differs from job lineage")
        return artifact
