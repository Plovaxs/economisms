"""A minimal reverse-proxy transport, modeled on
`data_ingestion.transport`'s inject-a-fake-for-tests pattern -- but a
wider shape than `HttpTransport.get`'s GET-only, params-only contract,
since a reverse proxy needs to forward an arbitrary method, arbitrary
request headers, and an arbitrary request body, and needs the
response's status and headers back too, not just its body.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Protocol


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
    """Raised by `UrllibUpstreamTransport` when the upstream cannot be
    reached at all (connection refused, DNS failure, timeout) -- NOT
    raised for a reachable upstream's own non-2xx response, which is a
    real, faithfully-relayed response, not a proxy failure."""


class UrllibUpstreamTransport:
    """The one real transport. Not exercised by this repository's own
    test suite (which must stay hermetic, per every other connector in
    this project) -- `webgateway.app`'s tests inject a fake instead."""

    def request(
        self,
        method: str,
        url: str,
        headers: tuple[tuple[str, str], ...],
        body: bytes,
        *,
        timeout: float = 30.0,
    ) -> UpstreamResponse:
        request = urllib.request.Request(url, data=body or None, method=method)
        for name, value in headers:
            request.add_header(name, value)
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return UpstreamResponse(
                    status=response.status,
                    headers=tuple(response.getheaders()),
                    body=response.read(),
                )
        except urllib.error.HTTPError as exc:
            # A reachable upstream's own non-2xx answer (401/404/...) --
            # a real response to relay, not a proxy-level failure.
            return UpstreamResponse(
                status=exc.code,
                headers=tuple(exc.headers.items()) if exc.headers else (),
                body=exc.read(),
            )
        except urllib.error.URLError as exc:
            raise UpstreamUnavailableError(f"upstream unavailable: {url}: {exc.reason}") from exc
