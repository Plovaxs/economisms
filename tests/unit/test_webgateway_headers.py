from __future__ import annotations

from prometheus.webgateway.headers import (
    API_CSP,
    SPA_CSP,
    finalize_headers,
    set_default_header,
)


def names(headers):
    return [name for name, _ in headers]


def as_dict(headers):
    return {name: value for name, value in headers}


def test_every_enforced_security_header_is_added_once() -> None:
    headers = finalize_headers([(b"content-type", b"text/plain")], https=False, is_html=False)
    out = as_dict(headers)
    assert out[b"x-content-type-options"] == b"nosniff"
    assert out[b"x-frame-options"] == b"DENY"
    assert out[b"referrer-policy"] == b"no-referrer"
    assert out[b"cross-origin-opener-policy"] == b"same-origin"
    assert out[b"cross-origin-resource-policy"] == b"same-origin"
    assert out[b"x-permitted-cross-domain-policies"] == b"none"
    assert b"camera=()" in out[b"permissions-policy"]
    assert len(names(headers)) == len(set(names(headers)))


def test_enforced_headers_replace_whatever_the_response_already_carried() -> None:
    headers = finalize_headers(
        [
            (b"X-Frame-Options", b"ALLOWALL"),
            (b"x-content-type-options", b"nope"),
            (b"Referrer-Policy", b"unsafe-url"),
        ],
        https=False,
        is_html=False,
    )
    out = as_dict(headers)
    assert out[b"x-frame-options"] == b"DENY"
    assert out[b"x-content-type-options"] == b"nosniff"
    assert out[b"referrer-policy"] == b"no-referrer"
    assert b"X-Frame-Options" not in out


def test_server_and_powered_by_banners_are_dropped() -> None:
    headers = finalize_headers(
        [(b"Server", b"uvicorn"), (b"X-Powered-By", b"x"), (b"content-type", b"a")],
        https=False,
        is_html=False,
    )
    assert b"server" not in {n.lower() for n in names(headers)}
    assert b"x-powered-by" not in {n.lower() for n in names(headers)}
    assert (b"content-type", b"a") in headers


def test_csp_depends_on_whether_the_response_is_an_html_document() -> None:
    assert (
        as_dict(finalize_headers([], https=False, is_html=True))[b"content-security-policy"]
        == SPA_CSP.encode()
    )
    assert (
        as_dict(finalize_headers([], https=False, is_html=False))[b"content-security-policy"]
        == API_CSP.encode()
    )


def test_a_csp_the_response_chose_itself_is_kept_and_not_duplicated() -> None:
    headers = finalize_headers(
        [(b"content-security-policy", b"default-src 'self'")], https=False, is_html=True
    )
    assert [v for n, v in headers if n == b"content-security-policy"] == [b"default-src 'self'"]


def test_hsts_and_upgrade_insecure_requests_are_https_only() -> None:
    plain = finalize_headers([], https=False, is_html=True)
    secure = finalize_headers([], https=True, is_html=True)
    assert b"strict-transport-security" not in as_dict(plain)
    assert b"upgrade-insecure-requests" not in as_dict(plain)[b"content-security-policy"]
    assert b"max-age=63072000" in as_dict(secure)[b"strict-transport-security"]
    assert as_dict(secure)[b"content-security-policy"].endswith(b"; upgrade-insecure-requests")


def test_an_upstream_hsts_header_is_never_relayed_over_cleartext() -> None:
    headers = finalize_headers(
        [(b"Strict-Transport-Security", b"max-age=0")], https=False, is_html=False
    )
    assert b"strict-transport-security" not in {n.lower() for n in names(headers)}


def test_set_default_header_only_fills_a_gap() -> None:
    headers = [(b"Cache-Control", b"private")]
    set_default_header(headers, b"cache-control", b"no-store")
    assert headers == [(b"Cache-Control", b"private")]
    set_default_header(headers, b"etag", b'"x"')
    assert (b"etag", b'"x"') in headers


def test_the_spa_policy_forbids_everything_it_does_not_need() -> None:
    directives = dict(part.strip().split(" ", 1) for part in SPA_CSP.split(";"))
    assert directives["default-src"] == "'none'"
    for needed in ("script-src", "style-src", "font-src", "connect-src", "manifest-src"):
        assert directives[needed] == "'self'"
    assert directives["img-src"] == "'self' data:"
    for locked in ("base-uri", "form-action", "frame-ancestors", "object-src"):
        assert directives[locked] == "'none'"
    assert "worker-src" not in directives and "frame-src" not in directives
