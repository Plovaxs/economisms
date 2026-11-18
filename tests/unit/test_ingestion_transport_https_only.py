"""`UrllibTransport` is the one real network path every data connector uses.
`urllib.request.urlopen` also speaks file:, ftp: and data: URLs, so the
transport refuses anything but https BEFORE any I/O happens -- these tests
make `urlopen` explode if it is ever reached."""

from __future__ import annotations

import pytest

from prometheus.data_ingestion.transport import HttpRequestError, UrllibTransport


@pytest.fixture
def no_io(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("urlopen must never be reached for a non-https URL")

    monkeypatch.setattr("urllib.request.urlopen", forbidden)


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.org/data.csv",
        "data:text/csv,a,b",
        "http://example.org/plain-http",
        "gopher://example.org/",
        "//example.org/protocol-relative",
        "example.org/no-scheme",
        "",
        "HTTP://EXAMPLE.ORG/upper",
    ],
)
def test_anything_but_https_is_refused_before_any_io(no_io, url) -> None:
    with pytest.raises(HttpRequestError, match="only https"):
        UrllibTransport().get(url, {"q": "1"})


def test_an_https_url_is_passed_through_with_its_query(monkeypatch) -> None:
    seen = {}

    class _Response:
        status = 200

        def read(self):
            return b"ok"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(url, timeout):
        seen["url"], seen["timeout"] = url, timeout
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    response = UrllibTransport(timeout=5.0).get("https://example.org/data.csv", {"a": "1"})
    assert (response.status_code, response.body) == (200, b"ok")
    assert seen == {"url": "https://example.org/data.csv?a=1", "timeout": 5.0}
