from __future__ import annotations

import pytest

from prometheus.httpsec.headers import (
    API_CSP,
    finalize_headers,
    set_default_header,
)


def as_dict(headers):
    return {name: value for name, value in headers}


def test_every_enforced_header_is_added_exactly_once() -> None:
    headers = finalize_headers([(b"content-type", b"text/plain")], https=False)
    out = as_dict(headers)
    assert out[b"x-content-type-options"] == b"nosniff"
    assert out[b"x-frame-options"] == b"DENY"
    assert out[b"referrer-policy"] == b"no-referrer"
    assert out[b"cross-origin-opener-policy"] == b"same-origin"
    assert out[b"cross-origin-resource-policy"] == b"same-origin"
    assert out[b"x-permitted-cross-domain-policies"] == b"none"
    assert b"camera=()" in out[b"permissions-policy"]
    names = [name for name, _ in headers]
    assert len(names) == len(set(names))


def test_the_default_policy_is_the_api_one() -> None:
    assert (
        as_dict(finalize_headers([], https=False))[b"content-security-policy"] == API_CSP.encode()
    )


def test_a_caller_policy_replaces_the_default() -> None:
    out = as_dict(finalize_headers([], https=False, csp="default-src 'self'"))
    assert out[b"content-security-policy"] == b"default-src 'self'"


@pytest.mark.parametrize(
    "weak",
    [
        (b"X-Frame-Options", b"ALLOWALL"),
        (b"x-content-type-options", b"sniff"),
        (b"Referrer-Policy", b"unsafe-url"),
        (b"Cross-Origin-Resource-Policy", b"cross-origin"),
        (b"Permissions-Policy", b"camera=*"),
    ],
)
def test_a_weaker_value_already_on_the_response_is_replaced_not_kept(weak) -> None:
    headers = finalize_headers([weak], https=False)
    lowered = [name.lower() for name, _ in headers]
    assert lowered.count(weak[0].lower()) == 1
    assert (weak[0], weak[1]) not in headers


def test_banners_are_dropped() -> None:
    headers = finalize_headers(
        [(b"Server", b"uvicorn"), (b"X-Powered-By", b"x"), (b"etag", b'"a"')], https=False
    )
    lowered = {name.lower() for name, _ in headers}
    assert b"server" not in lowered and b"x-powered-by" not in lowered
    assert (b"etag", b'"a"') in headers


def test_a_csp_the_response_chose_itself_is_kept() -> None:
    headers = finalize_headers([(b"Content-Security-Policy", b"default-src 'self'")], https=False)
    assert [v for n, v in headers if n.lower() == b"content-security-policy"] == [
        b"default-src 'self'"
    ]


def test_hsts_and_upgrade_insecure_requests_only_over_https() -> None:
    plain = as_dict(finalize_headers([], https=False, upgrade_insecure_requests=True))
    secure = as_dict(finalize_headers([], https=True, upgrade_insecure_requests=True))
    assert b"strict-transport-security" not in plain
    assert b"upgrade-insecure-requests" not in plain[b"content-security-policy"]
    assert b"max-age=63072000" in secure[b"strict-transport-security"]
    assert secure[b"content-security-policy"].endswith(b"; upgrade-insecure-requests")


def test_upgrade_insecure_requests_is_opt_in() -> None:
    secure = as_dict(finalize_headers([], https=True))
    assert b"upgrade-insecure-requests" not in secure[b"content-security-policy"]


def test_a_stale_hsts_header_from_the_response_is_never_relayed_over_cleartext() -> None:
    headers = finalize_headers([(b"Strict-Transport-Security", b"max-age=0")], https=False)
    assert b"strict-transport-security" not in {name.lower() for name, _ in headers}


def test_applying_it_twice_changes_nothing() -> None:
    once = finalize_headers([(b"content-type", b"a")], https=True)
    twice = finalize_headers(once, https=True)
    assert sorted(once) == sorted(twice)


def test_set_default_header_only_fills_a_gap() -> None:
    headers = [(b"Cache-Control", b"private")]
    set_default_header(headers, b"cache-control", b"no-store")
    assert headers == [(b"Cache-Control", b"private")]
    set_default_header(headers, b"etag", b'"x"')
    assert (b"etag", b'"x"') in headers
