"""Pure request-target validation and routing for the web gateway.

Plain functions over strings -- no ASGI, no sockets -- so the whole
surface can be unit-tested and property-tested (Hypothesis) exhaustively.

Why this exists: the first gateway matched routes with
`path.startswith("/api/jobs")` and built the upstream URL by string
concatenation, so the CLIENT chose the authority of the URL the gateway
then requested. Checked against a real server before this rewrite:
`/api/jobs.attacker.example/x` against a portless upstream
(`--jobs-url http://jobs-api`) made the gateway resolve and dial
`jobs-api.attacker.example`, and its 502 body echoed the internal URL back.
`/api/jobs@evil.example/x` produced `http://127.0.0.1:8765@evil.example/x`,
whose RFC 3986 host is `evil.example` -- urllib on current CPython happens
to fail that as a DNS error instead of connecting, but any RFC-compliant
client (one `UpstreamTransport` swap away) would have connected. The same
concatenation let a decoded `%3F`/`%23` inside a path segment leak into the
upstream query/fragment, and let a NUL byte or a non-ASCII query crash a
handler. Everything here is built so those classes of bug cannot be
expressed:

* a request target is validated against a closed character set BEFORE it
  is routed, and rejected (never "cleaned up") if it falls outside it;
* a prefix only matches on a whole path-segment boundary;
* the upstream path is the client's own still-percent-encoded bytes (so
  `%2F` can never silently become a `/`), always begins with `/`, and
  contains no dot-segments, empty segments, backslashes, NULs or
  control characters in any decoded segment;
* `?` and `#` cannot appear in a validated path at all, so a path can
  never smuggle a query string or fragment.

Because the validated path always starts with `/`, concatenating it
onto a configured `scheme://host:port` base can never alter the
authority component -- and `webgateway.app` additionally re-parses the
final URL and refuses it if the authority ever differs from the
configured upstream (belt and braces).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from urllib.parse import quote, unquote_to_bytes

MAX_PATH_BYTES = 2048
MAX_QUERY_BYTES = 2048

# RFC 3986 `pchar` plus the segment separator, and `%` for escapes. Notably
# absent: `?`, `#`, `\`, space, `"`, `<`, `>`, `^`, `` ` ``, `{`, `|`, `}`,
# every control character, and everything non-ASCII.
_ALLOWED_PATH = re.compile(r"/[A-Za-z0-9._~!$&'()*+,;=:@%/-]*")
_ALLOWED_QUERY = re.compile(r"[A-Za-z0-9._~!$&'()*+,;=:@%/?-]*")
_BAD_PERCENT = re.compile(r"%(?![0-9A-Fa-f]{2})")

_JOBS_PREFIX = "/api/jobs"
_DASHBOARD_PREFIX = "/api/dashboard"
_DASHBOARD_UPSTREAM_PREFIX = "/dashboard"
_API_PREFIX = "/api"


class PathRejected(ValueError):
    """The request target is malformed or outside the accepted grammar."""


class RouteKind(Enum):
    HEALTH = "health"
    READY = "ready"
    STATIC = "static"
    JOBS = "jobs"
    DASHBOARD = "dashboard"
    UNKNOWN_API = "unknown_api"


@dataclass(frozen=True, slots=True)
class Route:
    """`target` is, for JOBS/DASHBOARD, the validated upstream path (still
    percent-encoded, always starting with `/`); for STATIC, the decoded
    path to resolve under the dist root; otherwise empty."""

    kind: RouteKind
    target: str = ""


def raw_path_from_scope(scope: dict[str, object]) -> str:
    """The client's still-percent-encoded path, as the server received it.

    Real ASGI servers (uvicorn) provide `raw_path`. A scope without it
    (a hand-built test scope) falls back to re-encoding the decoded
    `path`, which keeps every round-trip lossless for the characters the
    grammar above accepts."""
    raw = scope.get("raw_path")
    if isinstance(raw, bytes):
        try:
            return raw.decode("ascii")
        except UnicodeDecodeError as exc:
            raise PathRejected("request path must be ASCII") from exc
    path = scope.get("path", "")
    if not isinstance(path, str):
        raise PathRejected("request path must be text")
    return quote(path, safe="/")


def validate_query(raw_query: bytes) -> str:
    if len(raw_query) > MAX_QUERY_BYTES:
        raise PathRejected("query string exceeds the byte budget")
    try:
        query = raw_query.decode("ascii")
    except UnicodeDecodeError as exc:
        raise PathRejected("query string must be ASCII") from exc
    if _ALLOWED_QUERY.fullmatch(query) is None or _BAD_PERCENT.search(query):
        raise PathRejected("query string contains characters outside the accepted set")
    return query


def _validate_path(raw_path: str) -> list[str]:
    if len(raw_path) > MAX_PATH_BYTES:
        raise PathRejected("request path exceeds the byte budget")
    if _ALLOWED_PATH.fullmatch(raw_path) is None or _BAD_PERCENT.search(raw_path):
        raise PathRejected("request path contains characters outside the accepted set")
    segments = raw_path.split("/")[1:]
    decoded_segments: list[str] = []
    for index, segment in enumerate(segments):
        if segment == "" and index != len(segments) - 1:
            raise PathRejected("request path contains an empty segment")
        try:
            decoded = unquote_to_bytes(segment).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise PathRejected("request path is not valid UTF-8") from exc
        if (
            decoded in (".", "..")
            or "/" in decoded
            or "\\" in decoded
            or any(ord(char) < 0x20 or ord(char) == 0x7F for char in decoded)
        ):
            raise PathRejected("request path segment is not allowed")
        decoded_segments.append(decoded)
    return decoded_segments


def _under(raw_path: str, prefix: str) -> str | None:
    """The remainder of `raw_path` after `prefix`, but only on a whole
    path-segment boundary -- `/api/jobsX` is NOT under `/api/jobs`."""
    if raw_path == prefix:
        return ""
    if raw_path.startswith(prefix + "/"):
        return raw_path[len(prefix) :]
    return None


def match_route(raw_path: str) -> Route:
    decoded_segments = _validate_path(raw_path)
    if raw_path == "/health/live":
        return Route(RouteKind.HEALTH)
    if raw_path == "/health/ready":
        return Route(RouteKind.READY)
    jobs_rest = _under(raw_path, _JOBS_PREFIX)
    if jobs_rest is not None:
        return Route(RouteKind.JOBS, jobs_rest or "/")
    dashboard_rest = _under(raw_path, _DASHBOARD_PREFIX)
    if dashboard_rest is not None:
        return Route(RouteKind.DASHBOARD, _DASHBOARD_UPSTREAM_PREFIX + dashboard_rest)
    if _under(raw_path, _API_PREFIX) is not None:
        return Route(RouteKind.UNKNOWN_API)
    return Route(RouteKind.STATIC, "/" + "/".join(decoded_segments))


def public_prefix(kind: RouteKind) -> str:
    """The public (browser-facing) path prefix a proxied route lives under."""
    if kind is RouteKind.JOBS:
        return _JOBS_PREFIX
    if kind is RouteKind.DASHBOARD:
        return _DASHBOARD_PREFIX
    raise ValueError(f"{kind} is not a proxied route")


def rewrite_location(location: str, kind: RouteKind, upstream_origin: str) -> str:
    """Map an upstream-relative `Location` back into the public namespace.

    `service.application` answers a job submission with
    `Location: /v1/jobs/<id>`, relative to ITS root. Left alone, a browser
    would resolve that against the gateway's origin and miss the
    `/api/jobs` prefix entirely. Absolute URLs naming the upstream's own
    origin are mapped the same way (so an internal address is never
    handed to a client); anything else is returned untouched."""
    if location.startswith(upstream_origin + "/") or location == upstream_origin:
        location = location[len(upstream_origin) :] or "/"
    if not location.startswith("/") or location.startswith("//"):
        return location
    if kind is RouteKind.DASHBOARD:
        if location == _DASHBOARD_UPSTREAM_PREFIX or location.startswith(
            _DASHBOARD_UPSTREAM_PREFIX + "/"
        ):
            return _DASHBOARD_PREFIX + location[len(_DASHBOARD_UPSTREAM_PREFIX) :]
        return location
    return public_prefix(kind) + location
