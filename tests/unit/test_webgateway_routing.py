"""`webgateway.routing` is pure string logic, so it is checked two ways:
named payloads (every attack class the first gateway was confirmed
vulnerable to, against a real PoC before the rewrite) and a Hypothesis
property over ARBITRARY text -- whatever a client sends, a routed path
may never change the upstream authority, escape its prefix, or carry a
query/fragment."""

from __future__ import annotations

from urllib.parse import unquote, urlsplit

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from prometheus.webgateway.routing import (
    PathRejected,
    Route,
    RouteKind,
    match_route,
    public_prefix,
    raw_path_from_scope,
    rewrite_location,
    validate_query,
)

JOBS_BASE = "http://127.0.0.1:8765"
DASHBOARD_BASE = "http://127.0.0.1:8766"


def test_jobs_prefix_is_stripped_exactly_like_vites_dev_proxy() -> None:
    assert match_route("/api/jobs/v1/jobs/abc") == Route(RouteKind.JOBS, "/v1/jobs/abc")


def test_dashboard_prefix_is_rewritten_exactly_like_vites_dev_proxy() -> None:
    assert match_route("/api/dashboard/economy") == Route(RouteKind.DASHBOARD, "/dashboard/economy")
    assert match_route("/api/dashboard") == Route(RouteKind.DASHBOARD, "/dashboard")


def test_a_bare_prefix_routes_to_the_upstream_root() -> None:
    assert match_route("/api/jobs") == Route(RouteKind.JOBS, "/")
    assert match_route("/api/jobs/") == Route(RouteKind.JOBS, "/")


def test_health_and_static_and_unknown_api() -> None:
    assert match_route("/health/live").kind is RouteKind.HEALTH
    assert match_route("/") == Route(RouteKind.STATIC, "/")
    assert match_route("/assets/app.js") == Route(RouteKind.STATIC, "/assets/app.js")
    assert match_route("/lab/pde-solver").kind is RouteKind.STATIC
    assert match_route("/api").kind is RouteKind.UNKNOWN_API
    assert match_route("/api/").kind is RouteKind.UNKNOWN_API
    assert match_route("/api/nope/x").kind is RouteKind.UNKNOWN_API


@pytest.mark.parametrize(
    "path",
    [
        "/api/jobs@evil.example/latest/meta-data",
        "/api/jobs@169.254.169.254/",
        "/api/jobs:80@evil.example/",
        "/api/jobs%40evil.example/",
    ],
)
def test_the_authority_smuggling_payload_never_reaches_a_proxy_route(path: str) -> None:
    """`/api/jobs@host/...` used to become `http://127.0.0.1:8765@host/...`
    -- a request to `host`. It is not under the `/api/jobs` prefix (no
    segment boundary), so it is treated as an unknown static path."""
    route = match_route(path)
    assert route.kind is not RouteKind.JOBS
    assert route.kind is not RouteKind.DASHBOARD


def test_a_prefix_only_matches_on_a_whole_segment() -> None:
    assert match_route("/api/jobsX/v1").kind is RouteKind.UNKNOWN_API
    assert match_route("/api/jobs-admin").kind is RouteKind.UNKNOWN_API
    assert match_route("/api/dashboardX").kind is RouteKind.UNKNOWN_API
    assert match_route("/apix").kind is RouteKind.STATIC


@pytest.mark.parametrize(
    "path",
    [
        "/api/jobs/../../admin",
        "/api/jobs/%2e%2e/admin",
        "/api/jobs/%2E%2E/admin",
        "/api/jobs/.%2e/admin",
        "/api/jobs/./v1",
        "/api/jobs/a%2Fb",
        "/api/jobs/a%2fb",
        "/api/jobs/a%5Cb",
        "/api/jobs\\evil",
        "/api/jobs/%00",
        "/api/jobs/a\x00b",
        "/api/jobs/%0d%0aX-Injected: 1",
        "/api/jobs/a b",
        "/api/jobs/a?b=1",
        "/api/jobs/a#frag",
        "/api/jobs//v1",
        "/api/jobs/%zz",
        "/api/jobs/%2",
        "/api/jobs/%ff",
        "/api/jobs/é",
        "/api/jobs/<script>",
        "api/jobs/v1",
        "http://evil.example/api/jobs",
        "",
        "/" + "a" * 3000,
    ],
)
def test_malformed_or_traversing_targets_are_rejected_outright(path: str) -> None:
    with pytest.raises(PathRejected):
        match_route(path)


def test_a_percent_encoded_character_is_forwarded_as_the_client_sent_it() -> None:
    route = match_route("/api/jobs/v1/jobs/a%20b%3Fc")
    assert route.target == "/v1/jobs/a%20b%3Fc"


def test_a_single_trailing_slash_is_allowed() -> None:
    assert match_route("/api/dashboard/").target == "/dashboard/"


def test_raw_path_wins_over_the_decoded_path() -> None:
    scope = {"path": "/api/jobs/a/b", "raw_path": b"/api/jobs/a%2Fb"}
    assert raw_path_from_scope(scope) == "/api/jobs/a%2Fb"


def test_without_raw_path_the_decoded_path_is_re_encoded_losslessly() -> None:
    assert raw_path_from_scope({"path": "/api/jobs/a b?x"}) == "/api/jobs/a%20b%3Fx"
    assert raw_path_from_scope({"path": "/api/jobs@evil"}) == "/api/jobs%40evil"


def test_a_non_ascii_raw_path_is_rejected() -> None:
    with pytest.raises(PathRejected):
        raw_path_from_scope({"raw_path": "/é".encode()})


def test_query_validation() -> None:
    assert validate_query(b"") == ""
    assert validate_query(b"n_steps=3&seed=1") == "n_steps=3&seed=1"
    assert validate_query(b"cursor=a%20b&x=/y?z") == "cursor=a%20b&x=/y?z"
    for bad in (b"q=\xc3\xa9", b"a b", b"a#b", b"a=%zz", b"a\x00", b"x=" + b"a" * 3000, b"a=<b>"):
        with pytest.raises(PathRejected):
            validate_query(bad)


def test_public_prefix_only_exists_for_proxied_routes() -> None:
    assert public_prefix(RouteKind.JOBS) == "/api/jobs"
    assert public_prefix(RouteKind.DASHBOARD) == "/api/dashboard"
    with pytest.raises(ValueError):
        public_prefix(RouteKind.STATIC)


def test_a_relative_location_is_mapped_back_into_the_public_namespace() -> None:
    assert rewrite_location("/v1/jobs/abc", RouteKind.JOBS, JOBS_BASE) == "/api/jobs/v1/jobs/abc"
    assert (
        rewrite_location("/dashboard/economy?x=1", RouteKind.DASHBOARD, DASHBOARD_BASE)
        == "/api/dashboard/economy?x=1"
    )


def test_an_absolute_location_naming_the_upstream_never_leaks_its_address() -> None:
    assert (
        rewrite_location(JOBS_BASE + "/v1/jobs/abc", RouteKind.JOBS, JOBS_BASE)
        == "/api/jobs/v1/jobs/abc"
    )


def test_an_external_or_protocol_relative_location_is_left_untouched() -> None:
    assert rewrite_location("https://example.org/x", RouteKind.JOBS, JOBS_BASE) == (
        "https://example.org/x"
    )
    assert rewrite_location("//example.org/x", RouteKind.JOBS, JOBS_BASE) == "//example.org/x"


# The adversarial alphabet leans on every character that has ever mattered in a
# URL parser, instead of leaving it to uniformly random unicode to stumble on
# one of them.
_SPECIAL = st.sampled_from(
    list("/@:?#\\%.;&=+ <>\"'`{}|^~!$*(),-_\x00\r\n\t") + ["%2f", "%2e", "%40"]
)
_PATHS = st.one_of(
    st.text(max_size=80),
    st.lists(st.one_of(_SPECIAL, st.text(alphabet="abc012", max_size=4)), max_size=40).map("".join),
).map(lambda s: "/api/jobs" + s)


@settings(max_examples=600, deadline=None)
@given(_PATHS)
def test_property_a_routed_path_can_never_change_the_upstream_authority(path: str) -> None:
    try:
        route = match_route(path)
    except PathRejected:
        return
    if route.kind is RouteKind.JOBS:
        url = JOBS_BASE + route.target
        parts = urlsplit(url)
        assert (parts.scheme, parts.netloc) == ("http", "127.0.0.1:8765")
        assert parts.username is None and parts.password is None
        assert route.target.startswith("/")
        assert parts.query == "" and parts.fragment == ""
        for segment in route.target.split("/")[1:]:
            decoded = unquote(segment)
            assert decoded not in (".", "..")
            assert "/" not in decoded and "\\" not in decoded
            assert not any(ord(c) < 0x20 or ord(c) == 0x7F for c in decoded)
    elif route.kind is RouteKind.DASHBOARD:
        raise AssertionError("a /api/jobs-prefixed path must never route to the dashboard")


@settings(max_examples=400, deadline=None)
@given(
    st.text(alphabet=st.sampled_from(list("/@:?#\\%.abc012 \x00")), max_size=40).map(
        lambda s: "/api/dashboard" + s
    )
)
def test_property_dashboard_routes_stay_under_the_dashboard_prefix(path: str) -> None:
    try:
        route = match_route(path)
    except PathRejected:
        return
    if route.kind is RouteKind.DASHBOARD:
        parts = urlsplit(DASHBOARD_BASE + route.target)
        assert parts.netloc == "127.0.0.1:8766"
        assert route.target == "/dashboard" or route.target.startswith("/dashboard/")
