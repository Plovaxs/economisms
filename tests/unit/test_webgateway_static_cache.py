"""Conditional requests, compression and the bounded in-memory cache for the
gateway's static files. The frontend bundle is ~740 kB of JavaScript: without
these, every page load re-sends all of it uncompressed and the gateway re-reads
and re-hashes it from disk on every request."""

from __future__ import annotations

import gzip
import os
import time

import pytest

from prometheus.webgateway.static_files import StaticCache, locate_static_file, resolve_static_file
from tests.unit.test_webgateway_app import make_app, request


@pytest.fixture
def dist(tmp_path):
    root = tmp_path / "dist"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>" + "spa shell " * 200 + "</html>")
    (root / "assets" / "app.js").write_text("console.log('hello');\n" * 300)
    (root / "assets" / "tiny.js").write_text("x=1;")
    (root / "assets" / "font.woff2").write_bytes(b"wOF2" + os.urandom(4000))
    (root / "assets" / "logo.png").write_bytes(b"\x89PNG" + os.urandom(4000))
    return root


def gunzip(body: bytes) -> bytes:
    return gzip.decompress(body)


# --- the pure layer ---------------------------------------------------------------------


def test_a_text_file_is_precompressed_and_gets_a_strong_etag(dist) -> None:
    file = resolve_static_file(dist, "/assets/app.js")
    assert file.etag.startswith('"') and file.etag.endswith('"') and len(file.etag) == 34
    assert file.gzipped is not None and len(file.gzipped) < len(file.body)
    assert gunzip(file.gzipped) == file.body


def test_small_and_already_compressed_files_are_not_compressed(dist) -> None:
    assert resolve_static_file(dist, "/assets/tiny.js").gzipped is None
    assert resolve_static_file(dist, "/assets/font.woff2").gzipped is None
    assert resolve_static_file(dist, "/assets/logo.png").gzipped is None


def test_the_etag_is_a_function_of_the_bytes_and_compression_is_deterministic(dist) -> None:
    first = resolve_static_file(dist, "/assets/app.js")
    second = resolve_static_file(dist, "/assets/app.js")
    assert first.etag == second.etag and first.gzipped == second.gzipped
    (dist / "assets" / "app.js").write_text("console.log('changed');\n" * 300)
    assert resolve_static_file(dist, "/assets/app.js").etag != first.etag


def test_locate_returns_the_path_without_reading_the_file(dist) -> None:
    target, relative, fallback = locate_static_file(dist, "/assets/app.js")
    assert target.name == "app.js" and relative == "assets/app.js" and fallback is False
    assert locate_static_file(dist, "/lab/x")[2] is True


def test_the_cache_serves_the_same_object_until_the_file_changes(dist) -> None:
    cache = StaticCache()
    first = cache.get(dist, "/assets/app.js")
    assert cache.get(dist, "/assets/app.js").body is first.body
    path = dist / "assets" / "app.js"
    path.write_text("console.log('v2');\n" * 300)
    os.utime(path, ns=(time.time_ns() + 5_000_000_000,) * 2)  # force a distinct mtime
    assert cache.get(dist, "/assets/app.js").body != first.body


def test_the_shell_is_cached_once_but_stamped_per_request(dist) -> None:
    cache = StaticCache()
    direct = cache.get(dist, "/index.html")
    fallback = cache.get(dist, "/lab/pde-solver")
    assert direct.is_spa_fallback is False and fallback.is_spa_fallback is True
    assert direct.body == fallback.body and direct.etag == fallback.etag


def test_the_cache_is_bounded_by_entry_count_and_by_bytes(dist) -> None:
    for i in range(20):
        (dist / "assets" / f"f{i}.js").write_text(f"console.log({i});\n" * 200)
    by_count = StaticCache(max_entries=5)
    for i in range(20):
        by_count.get(dist, f"/assets/f{i}.js")
    assert len(by_count) == 5
    by_bytes = StaticCache(max_entries=1000, max_bytes=20_000)
    for i in range(20):
        by_bytes.get(dist, f"/assets/f{i}.js")
    assert by_bytes.total_bytes <= 20_000


def test_the_cache_still_refuses_traversal_and_hidden_files(dist) -> None:
    from prometheus.webgateway.static_files import StaticFileNotFoundError

    cache = StaticCache()
    for path in ("/../x", "/.env", "/assets/missing.js"):
        with pytest.raises(StaticFileNotFoundError):
            cache.get(dist, path)


# --- over the app -----------------------------------------------------------------------


def test_a_matching_if_none_match_is_a_304_with_no_body(dist) -> None:
    app = make_app(dist)
    first = request(app, "GET", "/assets/app.js")
    again = request(
        app, "GET", "/assets/app.js", headers=[("if-none-match", first.headers["etag"])]
    )
    assert again.status == 304 and again.body == b""
    assert again.headers["etag"] == first.headers["etag"]
    assert "content-length" not in again.headers, "a 304 carries no body, so no length"
    assert "immutable" in again.headers["cache-control"]


def test_a_stale_if_none_match_gets_the_full_response(dist) -> None:
    resp = request(make_app(dist), "GET", "/assets/app.js", headers=[("if-none-match", '"stale"')])
    assert resp.status == 200 and len(resp.body) > 1000


@pytest.mark.parametrize("make", [lambda e: "*", lambda e: f'"other", {e}', lambda e: f"W/{e}"])
def test_if_none_match_accepts_star_lists_and_weak_forms(dist, make) -> None:
    app = make_app(dist)
    etag = request(app, "GET", "/assets/app.js").headers["etag"]
    resp = request(app, "GET", "/assets/app.js", headers=[("if-none-match", make(etag))])
    assert resp.status == 304


def test_gzip_is_served_to_clients_that_ask_for_it(dist) -> None:
    app = make_app(dist)
    plain = request(app, "GET", "/assets/app.js")
    packed = request(app, "GET", "/assets/app.js", headers=[("accept-encoding", "br, gzip;q=0.8")])
    assert "content-encoding" not in plain.headers
    assert packed.headers["content-encoding"] == "gzip"
    assert gunzip(packed.body) == plain.body
    assert int(packed.headers["content-length"]) == len(packed.body) < len(plain.body)
    assert packed.headers["vary"] == "accept-encoding" == plain.headers["vary"]
    assert packed.headers["etag"] != plain.headers["etag"], "a different representation"


@pytest.mark.parametrize("value", ["gzip;q=0", "identity", "br", ""])
def test_gzip_is_not_served_when_it_was_not_accepted(dist, value) -> None:
    resp = request(make_app(dist), "GET", "/assets/app.js", headers=[("accept-encoding", value)])
    assert "content-encoding" not in resp.headers


def test_the_gzip_representation_has_its_own_validator(dist) -> None:
    app = make_app(dist)
    headers = [("accept-encoding", "gzip")]
    first = request(app, "GET", "/assets/app.js", headers=headers)
    again = request(
        app, "GET", "/assets/app.js", headers=[*headers, ("if-none-match", first.headers["etag"])]
    )
    assert again.status == 304
    identity_etag = request(app, "GET", "/assets/app.js").headers["etag"]
    mismatch = request(
        app, "GET", "/assets/app.js", headers=[*headers, ("if-none-match", identity_etag)]
    )
    assert mismatch.status == 200


def test_files_that_are_not_worth_compressing_say_nothing_about_encoding(dist) -> None:
    for path in ("/assets/tiny.js", "/assets/font.woff2", "/assets/logo.png"):
        resp = request(make_app(dist), "GET", path, headers=[("accept-encoding", "gzip")])
        assert "content-encoding" not in resp.headers and "vary" not in resp.headers, path


def test_head_reports_the_compressed_length_and_sends_no_body(dist) -> None:
    app = make_app(dist)
    get = request(app, "GET", "/assets/app.js", headers=[("accept-encoding", "gzip")])
    head = request(app, "HEAD", "/assets/app.js", headers=[("accept-encoding", "gzip")])
    assert head.body == b"" and head.headers["content-length"] == get.headers["content-length"]
    assert head.headers["content-encoding"] == "gzip"


def test_the_shell_is_always_revalidated_but_can_still_be_a_304(dist) -> None:
    app = make_app(dist)
    first = request(app, "GET", "/lab/x")
    assert first.headers["cache-control"] == "no-cache"
    again = request(app, "GET", "/lab/x", headers=[("if-none-match", first.headers["etag"])])
    assert again.status == 304 and again.headers["cache-control"] == "no-cache"


def test_security_headers_ride_on_304_and_gzip_responses_too(dist) -> None:
    app = make_app(dist)
    etag = request(app, "GET", "/").headers["etag"]
    for resp in (
        request(app, "GET", "/", headers=[("if-none-match", etag)]),
        request(app, "GET", "/", headers=[("accept-encoding", "gzip")]),
    ):
        assert resp.headers["x-content-type-options"] == "nosniff"
        assert resp.headers["x-frame-options"] == "DENY"
        assert "content-security-policy" in resp.headers


def test_a_304_of_the_html_shell_carries_the_spa_csp_not_the_api_one(dist) -> None:
    """A browser merges a 304's headers into the entry it has cached for the document.
    A 304 that said `default-src 'none'` would REPLACE the SPA's policy in that entry and
    blank the page the next time it is loaded from cache."""
    from prometheus.webgateway.headers import API_CSP, SPA_CSP

    app = make_app(dist)
    ok = request(app, "GET", "/")
    again = request(app, "GET", "/", headers=[("if-none-match", ok.headers["etag"])])
    assert again.status == 304
    assert (
        again.headers["content-security-policy"] == SPA_CSP == ok.headers["content-security-policy"]
    )
    asset = request(app, "GET", "/assets/app.js")
    asset_304 = request(
        app, "GET", "/assets/app.js", headers=[("if-none-match", asset.headers["etag"])]
    )
    assert asset_304.headers["content-security-policy"] == API_CSP
