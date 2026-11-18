"""`HttpUpstreamTransport` is checked against REAL loopback HTTP servers --
the previous version of this file faked `urllib.request.urlopen`, which is
exactly the layer whose redirect-following, proxy-environment and
unbounded-read defaults were the bugs. A fake could never have caught
them. Everything binds `127.0.0.1:0`, so the suite stays hermetic: no
external network, no fixed port."""

from __future__ import annotations

import http.server
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager

import pytest

from prometheus.webgateway.proxy import (
    HttpUpstreamTransport,
    UpstreamRequestError,
    UpstreamResponse,
    UpstreamResponseTooLargeError,
    UpstreamUnavailableError,
    origin_of,
)

Handler = Callable[[http.server.BaseHTTPRequestHandler], None]


@contextmanager
def serve(handler: Handler) -> Iterator[tuple[str, list[dict[str, object]]]]:
    seen: list[dict[str, object]] = []

    class _Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            seen.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "raw_headers": list(self.headers.items()),
                    "body": self.rfile.read(length) if length else b"",
                }
            )
            handler(self)

        do_GET = do_POST = do_HEAD = do_DELETE = _handle

        def log_message(self, *args: object) -> None:
            pass

    class _Server(http.server.ThreadingHTTPServer):
        def handle_error(self, request: object, client_address: object) -> None:
            pass  # the client hanging up mid-reply is the point of several tests

    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}", seen
    finally:
        server.shutdown()
        server.server_close()


def reply(
    status: int = 200,
    body: bytes = b"",
    headers: tuple[tuple[str, str], ...] = (),
) -> Handler:
    def handler(request: http.server.BaseHTTPRequestHandler) -> None:
        request.send_response(status)
        for name, value in headers:
            request.send_header(name, value)
        request.send_header("Content-Length", str(len(body)))
        request.end_headers()
        if request.command != "HEAD":
            request.wfile.write(body)

    return handler


def test_forwards_method_path_headers_and_body_and_relays_the_response() -> None:
    with serve(reply(201, b'{"ok":true}', (("X-Thing", "1"),))) as (base, seen):
        result = HttpUpstreamTransport().request(
            "POST",
            f"{base}/v1/jobs?a=1&b=2",
            (("authorization", "Bearer secret-token"), ("content-type", "application/json")),
            b'{"kind":"qmacro"}',
            timeout=5.0,
        )
    assert result.status == 201
    assert result.body == b'{"ok":true}'
    assert ("X-Thing", "1") in result.headers
    call = seen[0]
    assert call["method"] == "POST"
    assert call["path"] == "/v1/jobs?a=1&b=2"
    assert call["body"] == b'{"kind":"qmacro"}'
    headers = call["headers"]
    assert isinstance(headers, dict)
    assert headers["authorization"] == "Bearer secret-token"
    assert headers["content-length"] == str(len(b'{"kind":"qmacro"}'))
    assert headers["host"] == base.removeprefix("http://")


def test_an_upstreams_non_2xx_response_is_relayed_not_raised() -> None:
    with serve(reply(404, b'{"error":"nf"}')) as (base, _):
        result = HttpUpstreamTransport().request("GET", f"{base}/x", (), b"", timeout=5.0)
    assert (result.status, result.body) == (404, b'{"error":"nf"}')


def test_a_redirect_is_relayed_to_the_caller_and_never_followed() -> None:
    """urllib followed the 302 and re-sent `Authorization` to the target."""
    with serve(reply(200, b"target")) as (target_base, target_seen):
        location = f"{target_base}/stolen"
        with serve(reply(302, b"", (("Location", location),))) as (base, _):
            result = HttpUpstreamTransport().request(
                "GET", f"{base}/x", (("Authorization", "Bearer s3cret"),), b"", timeout=5.0
            )
    assert result.status == 302
    assert dict(result.headers)["Location"] == location
    assert target_seen == [], "the redirect target must never be contacted"


def test_proxy_environment_variables_are_ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(name, "http://127.0.0.1:9")  # nothing listens on :9
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.delenv("NO_PROXY", raising=False)
    with serve(reply(200, b"direct")) as (base, seen):
        result = HttpUpstreamTransport().request("GET", f"{base}/x", (), b"", timeout=5.0)
    assert result.body == b"direct"
    assert len(seen) == 1


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://127.0.0.1/x",
        "data:text/plain,hi",
        "gopher://127.0.0.1/",
        "http://user:pass@127.0.0.1:1/",
        "http:///nohost",
        "http://127.0.0.1:99999/x",
        "//127.0.0.1/x",
        "127.0.0.1:8765/x",
    ],
)
def test_only_plain_http_urls_without_userinfo_are_ever_requested(url: str) -> None:
    with pytest.raises(UpstreamUnavailableError, match="not permitted"):
        HttpUpstreamTransport().request("GET", url, (), b"", timeout=1.0)


def test_an_origin_allowlist_is_a_second_barrier_behind_routing() -> None:
    with (
        serve(reply(200, b"ok")) as (allowed, _),
        serve(reply(200, b"evil")) as (other, other_seen),
    ):
        transport = HttpUpstreamTransport(allowed_origins=[allowed])
        assert transport.request("GET", f"{allowed}/x", (), b"", timeout=5.0).body == b"ok"
        with pytest.raises(UpstreamUnavailableError, match="not permitted"):
            transport.request("GET", f"{other}/x", (), b"", timeout=5.0)
    assert other_seen == []


def test_the_authority_smuggling_url_is_refused_by_the_allowlist() -> None:
    """The exact URL the first gateway built for `/api/jobs@evil.example/x`."""
    transport = HttpUpstreamTransport(allowed_origins=["http://127.0.0.1:8765"])
    with pytest.raises(UpstreamUnavailableError, match="not permitted"):
        transport.request("GET", "http://127.0.0.1:8765@evil.example/x", (), b"", timeout=1.0)


def test_a_response_over_the_ceiling_is_refused_by_declared_length() -> None:
    with serve(reply(200, b"x" * 2000)) as (base, _):
        with pytest.raises(UpstreamResponseTooLargeError):
            HttpUpstreamTransport(max_response_bytes=1000).request(
                "GET", f"{base}/x", (), b"", timeout=5.0
            )


def test_a_chunked_response_over_the_ceiling_is_cut_off_while_streaming() -> None:
    def chunked(request: http.server.BaseHTTPRequestHandler) -> None:
        request.send_response(200)
        request.send_header("Transfer-Encoding", "chunked")
        request.end_headers()
        for _ in range(8):
            request.wfile.write(b"200\r\n" + b"y" * 512 + b"\r\n")
        request.wfile.write(b"0\r\n\r\n")

    with serve(chunked) as (base, _):
        with pytest.raises(UpstreamResponseTooLargeError):
            HttpUpstreamTransport(max_response_bytes=1000).request(
                "GET", f"{base}/x", (), b"", timeout=5.0
            )


def test_a_response_exactly_at_the_ceiling_is_allowed() -> None:
    with serve(reply(200, b"z" * 1000)) as (base, _):
        result = HttpUpstreamTransport(max_response_bytes=1000).request(
            "GET", f"{base}/x", (), b"", timeout=5.0
        )
    assert len(result.body) == 1000


def test_a_chunked_response_is_reassembled() -> None:
    def chunked(request: http.server.BaseHTTPRequestHandler) -> None:
        request.send_response(200)
        request.send_header("Transfer-Encoding", "chunked")
        request.end_headers()
        request.wfile.write(b"3\r\nabc\r\n3\r\ndef\r\n0\r\n\r\n")

    with serve(chunked) as (base, _):
        assert HttpUpstreamTransport().request("GET", f"{base}/", (), b"", timeout=5.0).body == (
            b"abcdef"
        )


def test_a_slow_upstream_times_out_with_a_generic_message() -> None:
    def slow(request: http.server.BaseHTTPRequestHandler) -> None:
        time.sleep(1.5)
        reply(200, b"late")(request)

    with serve(slow) as (base, _):
        started = time.monotonic()
        with pytest.raises(UpstreamUnavailableError) as raised:
            HttpUpstreamTransport().request("GET", f"{base}/x", (), b"", timeout=0.3)
    assert time.monotonic() - started < 1.4
    assert str(raised.value) == "upstream unavailable"


def test_a_drip_feeding_upstream_hits_the_total_deadline() -> None:
    def drip(request: http.server.BaseHTTPRequestHandler) -> None:
        request.send_response(200)
        request.send_header("Transfer-Encoding", "chunked")
        request.end_headers()
        for _ in range(30):
            request.wfile.write(b"1\r\nz\r\n")
            request.wfile.flush()
            time.sleep(0.1)
        request.wfile.write(b"0\r\n\r\n")

    with serve(drip) as (base, _):
        started = time.monotonic()
        with pytest.raises(UpstreamUnavailableError, match="deadline"):
            HttpUpstreamTransport().request("GET", f"{base}/x", (), b"", timeout=0.5)
    assert time.monotonic() - started < 2.0


def test_a_refused_connection_does_not_leak_the_address_or_the_socket_error() -> None:
    with serve(reply()) as (base, _):
        dead = base
    with pytest.raises(UpstreamUnavailableError) as raised:
        HttpUpstreamTransport().request("GET", f"{dead}/x", (), b"", timeout=2.0)
    message = str(raised.value)
    assert message == "upstream unavailable"
    assert "127.0.0.1" not in message and "refused" not in message.lower()


def test_a_malformed_upstream_reply_is_an_unavailable_upstream() -> None:
    def garbage(request: http.server.BaseHTTPRequestHandler) -> None:
        request.wfile.write(b"NOT HTTP AT ALL\r\n\r\n")
        request.close_connection = True

    with serve(garbage) as (base, _):
        with pytest.raises(UpstreamUnavailableError):
            HttpUpstreamTransport().request("GET", f"{base}/x", (), b"", timeout=2.0)


def test_head_returns_headers_and_no_body() -> None:
    with serve(reply(200, b"body-that-head-never-carries", (("X-Kind", "head"),))) as (base, _):
        result = HttpUpstreamTransport().request("HEAD", f"{base}/x", (), b"", timeout=5.0)
    assert result.status == 200
    assert result.body == b""
    assert ("X-Kind", "head") in result.headers


def test_duplicate_response_headers_are_preserved() -> None:
    cookies = (("Set-Cookie", "a=1"), ("Set-Cookie", "b=2"))
    with serve(reply(200, b"", cookies)) as (base, _):
        result = HttpUpstreamTransport().request("GET", f"{base}/x", (), b"", timeout=5.0)
    assert [v for k, v in result.headers if k == "Set-Cookie"] == ["a=1", "b=2"]


def test_duplicate_request_headers_are_sent_as_given() -> None:
    with serve(reply(200, b"")) as (base, seen):
        HttpUpstreamTransport().request(
            "GET",
            f"{base}/x",
            (("authorization", "one"), ("authorization", "two")),
            b"",
            timeout=5.0,
        )
    raw = seen[0]["raw_headers"]
    assert isinstance(raw, list)
    assert [v for k, v in raw if k.lower() == "authorization"] == ["one", "two"]


@pytest.mark.parametrize(
    ("method", "header"),
    [
        ("GET", ("bad header name", "v")),
        ("GET", ("x-ok", "line1\r\nInjected: 1")),
        ("GET", ("x-ok", "nul\x00byte")),
        ("GET", ("", "v")),
        ("GE T", ("x-ok", "v")),
    ],
)
def test_an_invalid_method_or_header_is_a_request_error_not_an_upstream_failure(
    method: str, header: tuple[str, str]
) -> None:
    with serve(reply(200, b"")) as (base, seen):
        with pytest.raises(UpstreamRequestError):
            HttpUpstreamTransport().request(method, f"{base}/x", (header,), b"", timeout=5.0)
    assert seen == [], "an invalid request must never reach the wire"


def test_an_empty_post_body_still_carries_content_length_zero() -> None:
    with serve(reply(200, b"")) as (base, seen):
        HttpUpstreamTransport().request("POST", f"{base}/x", (), b"", timeout=5.0)
    headers = seen[0]["headers"]
    assert isinstance(headers, dict)
    assert headers["content-length"] == "0"


def test_origin_of_normalizes_scheme_host_and_default_port() -> None:
    assert origin_of("HTTP://LocalHost/x") == ("http", "localhost", 80)
    assert origin_of("https://example.org") == ("https", "example.org", 443)
    assert origin_of("http://127.0.0.1:8765/v1") == ("http", "127.0.0.1", 8765)


def test_constructor_validation() -> None:
    with pytest.raises(ValueError):
        HttpUpstreamTransport(max_response_bytes=0)
    with pytest.raises(UpstreamUnavailableError):
        HttpUpstreamTransport(allowed_origins=["file:///x"])


def test_upstream_response_is_a_plain_value_object() -> None:
    assert UpstreamResponse(200, (("a", "b"),), b"x") == UpstreamResponse(200, (("a", "b"),), b"x")
