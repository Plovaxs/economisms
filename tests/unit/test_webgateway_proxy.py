from __future__ import annotations

import io
import urllib.error

import pytest

from prometheus.webgateway.proxy import (
    UpstreamResponse,
    UpstreamUnavailableError,
    UrllibUpstreamTransport,
)


class _FakeUrlopen:
    """Stands in for `urllib.request.urlopen` -- this project's
    established hermetic-testing pattern (data_ingestion.transport)
    injects a fake TRANSPORT rather than mocking urllib internals;
    here that would mean reimplementing urllib's own request-building,
    so instead this fakes the one function UrllibUpstreamTransport
    calls, exactly at its boundary."""

    def __init__(self, response=None, http_error=None, url_error=None):
        self._response, self._http_error, self._url_error = response, http_error, url_error
        self.captured_request = None

    def __call__(self, request, timeout):
        self.captured_request = request
        if self._url_error is not None:
            raise self._url_error
        if self._http_error is not None:
            raise self._http_error
        return self._response


class _FakeHttpResponse:
    def __init__(self, status, headers, body):
        self.status, self._headers, self._body = status, headers, body

    def getheaders(self):
        return self._headers

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_forwards_method_url_headers_and_body_unchanged(monkeypatch) -> None:
    fake = _FakeUrlopen(
        response=_FakeHttpResponse(200, [("content-type", "application/json")], b'{"ok":true}')
    )
    monkeypatch.setattr("urllib.request.urlopen", fake)
    transport = UrllibUpstreamTransport()

    result = transport.request(
        "POST",
        "http://127.0.0.1:8765/v1/jobs",
        (("authorization", "Bearer secret-token"), ("content-type", "application/json")),
        b'{"kind":"qmacro"}',
        timeout=5.0,
    )

    assert result == UpstreamResponse(
        status=200, headers=(("content-type", "application/json"),), body=b'{"ok":true}'
    )
    assert fake.captured_request.full_url == "http://127.0.0.1:8765/v1/jobs"
    assert fake.captured_request.get_method() == "POST"
    assert fake.captured_request.data == b'{"kind":"qmacro"}'
    assert fake.captured_request.get_header("Authorization") == "Bearer secret-token"


def test_empty_body_is_sent_as_no_body_not_an_empty_bytestring(monkeypatch) -> None:
    fake = _FakeUrlopen(response=_FakeHttpResponse(200, [], b""))
    monkeypatch.setattr("urllib.request.urlopen", fake)
    transport = UrllibUpstreamTransport()

    transport.request("GET", "http://127.0.0.1:8765/v1/jobs/abc", (), b"", timeout=5.0)

    assert fake.captured_request.data is None


def test_a_reachable_upstreams_non_2xx_response_is_relayed_not_raised(monkeypatch) -> None:
    http_error = urllib.error.HTTPError(
        "http://127.0.0.1:8765/v1/jobs/missing",
        404,
        "Not Found",
        {"content-type": "application/json"},
        io.BytesIO(b'{"error":"not found"}'),
    )
    fake = _FakeUrlopen(http_error=http_error)
    monkeypatch.setattr("urllib.request.urlopen", fake)
    transport = UrllibUpstreamTransport()

    result = transport.request("GET", "http://127.0.0.1:8765/v1/jobs/missing", (), b"", timeout=5.0)

    assert result.status == 404
    assert result.body == b'{"error":"not found"}'


def test_an_unreachable_upstream_raises_a_clean_error(monkeypatch) -> None:
    fake = _FakeUrlopen(url_error=urllib.error.URLError("connection refused"))
    monkeypatch.setattr("urllib.request.urlopen", fake)
    transport = UrllibUpstreamTransport()

    with pytest.raises(UpstreamUnavailableError, match="unavailable"):
        transport.request("GET", "http://127.0.0.1:8765/v1/jobs", (), b"", timeout=5.0)
