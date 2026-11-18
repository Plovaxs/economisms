"""A hardened reverse-proxy transport over `http.client`.

The first version used `urllib.request.urlopen`, whose defaults are wrong
for a reverse proxy in four ways (each confirmed against a real local
server before this rewrite):

* it FOLLOWS redirects -- and copies the request's `Authorization` header
  onto the redirected request -- so a redirecting upstream could make the
  gateway re-send a caller's bearer token to a different host, and the
  client never saw the 3xx it was supposed to receive;
* it honours `http_proxy`/`https_proxy` from the environment, silently
  routing gateway-to-backend traffic through whatever proxy the
  deployment happens to export;
* it also speaks `file:`, `ftp:` and `data:` URLs;
* it reads a response into memory with no ceiling.

`http.client` speaks only HTTP(S), never redirects, never consults the
environment, and lets the response be read incrementally -- so every one
of those is closed by construction here, and the transport can be
restricted to an explicit allowlist of upstream origins as a second,
independent barrier behind `webgateway.routing`.

Error messages are deliberately generic: they reach clients, and an
internal address or socket error text is topology a client has no need
to learn. The detail is logged server-side by the caller.
"""

from __future__ import annotations

import http.client
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol
from urllib.parse import urlsplit

_READ_CHUNK = 64 * 1024
_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")
_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True, slots=True)
class UpstreamResponse:
    status: int
    headers: tuple[tuple[str, str], ...]
    body: bytes


class UpstreamTransport(Protocol):
    def request(
        self,
        method: str,
        url: str,
        headers: tuple[tuple[str, str], ...],
        body: bytes,
        *,
        timeout: float,
    ) -> UpstreamResponse: ...


class UpstreamUnavailableError(ValueError):
    """The upstream could not be reached or did not answer coherently
    (refused, timed out, malformed reply, address not permitted). NOT
    raised for a reachable upstream's own non-2xx answer, which is a
    real response to relay."""


class UpstreamResponseTooLargeError(UpstreamUnavailableError):
    """The upstream's response exceeded the configured byte ceiling."""


class UpstreamRequestError(ValueError):
    """The request the transport was asked to send is itself malformed
    (an invalid header name/value or method) -- a caller error, not an
    upstream failure."""


def origin_of(url: str) -> tuple[str, str, int]:
    """`(scheme, lower-cased host, port)` for an http(s) URL, or
    `UpstreamUnavailableError` for anything else (other schemes, userinfo,
    a missing host, an invalid port)."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError as exc:
        raise UpstreamUnavailableError("upstream address is not permitted") from exc
    scheme = parts.scheme.lower()
    if (
        scheme not in _DEFAULT_PORTS
        or not parts.hostname
        or parts.username is not None
        or parts.password is not None
    ):
        raise UpstreamUnavailableError("upstream address is not permitted")
    return scheme, parts.hostname.lower(), port or _DEFAULT_PORTS[scheme]


class HttpUpstreamTransport:
    """The one real transport. Its behaviour is checked against real
    loopback servers in `tests/unit/test_webgateway_proxy.py`."""

    def __init__(
        self,
        *,
        max_response_bytes: int = 32 * 1024 * 1024,
        allowed_origins: Iterable[str] | None = None,
    ) -> None:
        if type(max_response_bytes) is not int or max_response_bytes < 1:
            raise ValueError("max_response_bytes must be a positive integer")
        self.max_response_bytes = max_response_bytes
        self.allowed: frozenset[tuple[str, str, int]] | None = (
            None if allowed_origins is None else frozenset(origin_of(o) for o in allowed_origins)
        )

    def request(
        self,
        method: str,
        url: str,
        headers: tuple[tuple[str, str], ...],
        body: bytes,
        *,
        timeout: float = 30.0,
    ) -> UpstreamResponse:
        origin = origin_of(url)
        if self.allowed is not None and origin not in self.allowed:
            raise UpstreamUnavailableError("upstream address is not permitted")
        _check_request_line(method, headers)
        parts = urlsplit(url)
        scheme, host, port = origin
        target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        connection_class = (
            http.client.HTTPSConnection if scheme == "https" else http.client.HTTPConnection
        )
        deadline = time.monotonic() + timeout
        connection = connection_class(host, port, timeout=timeout)
        try:
            connection.putrequest(method, target, skip_host=True, skip_accept_encoding=True)
            connection.putheader("Host", parts.netloc)
            for name, value in headers:
                connection.putheader(name, value)
            if body or method in ("POST", "PUT", "PATCH"):
                connection.putheader("Content-Length", str(len(body)))
            connection.endheaders(body or None)
            response = connection.getresponse()
            payload = self._read(response, deadline)
            return UpstreamResponse(response.status, tuple(response.getheaders()), payload)
        except UpstreamUnavailableError:
            raise
        except ValueError as exc:
            raise UpstreamRequestError("request cannot be forwarded") from exc
        except (OSError, http.client.HTTPException) as exc:
            raise UpstreamUnavailableError("upstream unavailable") from exc
        finally:
            connection.close()

    def _read(self, response: http.client.HTTPResponse, deadline: float) -> bytes:
        declared = response.getheader("Content-Length")
        if declared is not None and declared.isdigit() and int(declared) > self.max_response_bytes:
            raise UpstreamResponseTooLargeError("upstream response is too large")
        chunks: list[bytes] = []
        total = 0
        while True:
            if time.monotonic() > deadline:
                raise UpstreamUnavailableError("upstream response deadline exceeded")
            # read1, not read: `read(n)` on a chunked body blocks until n bytes or
            # EOF arrive, so a drip-feeding upstream could outlive the deadline
            # without this loop ever getting control back to check it.
            chunk = response.read1(_READ_CHUNK)
            if not chunk:
                return b"".join(chunks)
            total += len(chunk)
            if total > self.max_response_bytes:
                raise UpstreamResponseTooLargeError("upstream response is too large")
            chunks.append(chunk)


def _check_request_line(method: str, headers: tuple[tuple[str, str], ...]) -> None:
    """`http.client` only rejects CR/LF injection; it accepts spaces in a header
    name and NUL or other control characters in a value. This is the last
    layer before the wire, so it enforces the actual grammar."""
    if _TOKEN.fullmatch(method) is None:
        raise UpstreamRequestError("request cannot be forwarded")
    for name, value in headers:
        if _TOKEN.fullmatch(name) is None or any(
            (ord(char) < 0x20 and char != "\t") or ord(char) == 0x7F for char in value
        ):
            raise UpstreamRequestError("request cannot be forwarded")
