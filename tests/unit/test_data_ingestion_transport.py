"""`UrllibTransport.get` itself is tested with `urllib.request.urlopen`
mocked out, not a live network call -- the test suite must stay
hermetic. The real, unmocked round trip (this transport driving
`data_ingestion.worldbank` against the actual live API) was run once,
by hand, during this module's own pre-implementation verification; see
`transport.py`'s own docstring and `test_worldbank_connector.py`'s real-
response-derived fixtures for what that confirmed.
"""

import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from prometheus.data_ingestion.transport import HttpRequestError, UrllibTransport


def test_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError):
        UrllibTransport(timeout=0.0)
    with pytest.raises(ValueError):
        UrllibTransport(timeout=-1.0)


def test_get_returns_status_and_body_on_success() -> None:
    fake_response = MagicMock()
    fake_response.status = 200
    fake_response.read.return_value = b'{"ok": true}'
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = False

    with patch("urllib.request.urlopen", return_value=fake_response) as mocked:
        transport = UrllibTransport(timeout=5.0)
        response = transport.get("https://example.invalid/api", {"a": "1", "b": "2"})

    assert response.status_code == 200
    assert response.body == b'{"ok": true}'
    called_url = mocked.call_args[0][0]
    assert called_url in (
        "https://example.invalid/api?a=1&b=2",
        "https://example.invalid/api?b=2&a=1",
    )


def test_get_with_no_params_omits_the_query_string() -> None:
    fake_response = MagicMock()
    fake_response.status = 200
    fake_response.read.return_value = b"{}"
    fake_response.__enter__.return_value = fake_response
    fake_response.__exit__.return_value = False

    with patch("urllib.request.urlopen", return_value=fake_response) as mocked:
        UrllibTransport().get("https://example.invalid/api", {})

    assert mocked.call_args[0][0] == "https://example.invalid/api"


def test_get_wraps_http_error() -> None:
    http_error = urllib.error.HTTPError(
        "https://example.invalid/api", 404, "Not Found", hdrs=None, fp=None  # type: ignore[arg-type]
    )
    with patch("urllib.request.urlopen", side_effect=http_error):
        with pytest.raises(HttpRequestError, match="404"):
            UrllibTransport().get("https://example.invalid/api", {})


def test_get_wraps_url_error() -> None:
    url_error = urllib.error.URLError("name resolution failed")
    with patch("urllib.request.urlopen", side_effect=url_error):
        with pytest.raises(HttpRequestError, match="network error"):
            UrllibTransport().get("https://example.invalid/api", {})
