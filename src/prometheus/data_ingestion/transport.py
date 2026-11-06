"""Pluggable HTTP transport for external data connectors (DAT-01/DAT-02:
"Create inventory of each external data source" / "Build FRED-MD/QD
ingestion with metadata capture", generalized here to any REST/JSON
source).

Every connector in `data_ingestion` takes a transport object rather than
calling `urllib` directly, so tests inject a fixture-returning fake
transport instead of making real network calls -- this keeps the test
suite hermetic, fast and deterministic (VAL-09: "deterministic CPU test
mode with fixed seeds"), with zero dependency on network availability,
rate limits or an external API's uptime or current data. `UrllibTransport`
is the one real implementation, using only the standard library (no new
third-party HTTP dependency -- this project currently has none, and a
simple JSON GET does not need one).
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status_code: int
    body: bytes


class HttpTransport(Protocol):
    def get(self, url: str, params: dict[str, str]) -> HttpResponse: ...


class HttpRequestError(Exception):
    """Raised by `UrllibTransport` on a network failure or non-2xx status."""


class UrllibTransport:
    """The real transport. Not exercised by this repository's own test
    suite (which must stay hermetic) -- verified instead via an ad hoc
    pre-implementation script that round-tripped a real request through
    `data_ingestion.worldbank`, `econosim.pit`, and back, confirmed
    correct, before any production code was written against it."""

    def __init__(self, timeout: float = 30.0) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = timeout

    def get(self, url: str, params: dict[str, str]) -> HttpResponse:
        query = urllib.parse.urlencode(params)
        full_url = f"{url}?{query}" if query else url
        try:
            with urllib.request.urlopen(full_url, timeout=self.timeout) as response:
                return HttpResponse(status_code=response.status, body=response.read())
        except urllib.error.HTTPError as exc:
            raise HttpRequestError(f"HTTP {exc.code} fetching {full_url}: {exc.reason}") from exc
        except urllib.error.URLError as exc:
            raise HttpRequestError(f"network error fetching {full_url}: {exc.reason}") from exc
