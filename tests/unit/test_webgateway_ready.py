"""`/health/live` answers "is THIS process up"; `/health/ready` answers "can it
actually serve" -- both backends reachable and reporting ready. An orchestrator
uses the first to decide whether to restart the gateway, the second whether to
send it traffic."""

from __future__ import annotations

import asyncio
import json
import threading

import pytest

from prometheus.webgateway.app import GatewayConfig, WebGatewayService
from prometheus.webgateway.proxy import UpstreamResponse, UpstreamUnavailableError
from tests.unit.test_webgateway_app import DASHBOARD, JOBS, request, request_async


class Backends:
    def __init__(self, *, jobs=200, dashboard=200, down=()):
        self.statuses = {"jobs": jobs, "dashboard": dashboard}
        self.down = set(down)
        self.calls: list[str] = []

    def request(self, method, url, headers, body, *, timeout):
        self.calls.append(url)
        name = "jobs" if url.startswith(JOBS) else "dashboard"
        if name in self.down:
            raise UpstreamUnavailableError("upstream unavailable")
        return UpstreamResponse(self.statuses[name], (), b"{}")


@pytest.fixture
def dist(tmp_path):
    (tmp_path / "index.html").write_text("<html/>")
    return tmp_path


def app_for(dist, backends, clock=None):
    return WebGatewayService(
        dist,
        JOBS,
        DASHBOARD,
        backends,
        config=GatewayConfig(rate_limit_per_second=0),
        clock=clock or (lambda: 0.0),
    )


def test_ready_when_both_backends_answer(dist) -> None:
    backends = Backends()
    resp = request(app_for(dist, backends), "GET", "/health/ready")
    assert resp.status == 200 and resp.json() == {"status": "ready"}
    assert sorted(backends.calls) == [f"{JOBS}/health/ready", f"{DASHBOARD}/health/live"]


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"down": ["jobs"]}, ["jobs"]),
        ({"down": ["dashboard"]}, ["dashboard"]),
        ({"down": ["jobs", "dashboard"]}, ["dashboard", "jobs"]),
        ({"jobs": 503}, ["jobs"]),
        ({"dashboard": 500}, ["dashboard"]),
    ],
)
def test_not_ready_names_which_backend_is_unavailable_and_nothing_more(
    dist, kwargs, expected
) -> None:
    resp = request(app_for(dist, Backends(**kwargs)), "GET", "/health/ready")
    assert resp.status == 503
    body = resp.json()
    assert body["status"] == "not_ready" and sorted(body["unavailable"]) == expected
    assert resp.headers["retry-after"] == "1"
    assert "127.0.0.1" not in resp.body.decode() and "8765" not in resp.body.decode()


def test_the_liveness_probe_does_not_depend_on_the_backends(dist) -> None:
    backends = Backends(down=["jobs", "dashboard"])
    assert request(app_for(dist, backends), "GET", "/health/live").status == 200
    assert backends.calls == []


def test_probes_are_coalesced_for_a_second(dist) -> None:
    now = [100.0]
    backends = Backends()
    app = app_for(dist, backends, clock=lambda: now[0])
    for _ in range(5):
        assert request(app, "GET", "/health/ready").status == 200
    assert len(backends.calls) == 2, "five probes inside one second must cost two backend calls"
    now[0] += 1.5
    request(app, "GET", "/health/ready")
    assert len(backends.calls) == 4


def test_a_recovered_backend_is_noticed_after_the_cache_expires(dist) -> None:
    now = [0.0]
    backends = Backends(down=["jobs"])
    app = app_for(dist, backends, clock=lambda: now[0])
    assert request(app, "GET", "/health/ready").status == 503
    backends.down.clear()
    now[0] += 2.0
    assert request(app, "GET", "/health/ready").status == 200


def test_ready_is_get_and_head_only_and_carries_the_security_headers(dist) -> None:
    app = app_for(dist, Backends())
    assert request(app, "POST", "/health/ready").status == 405
    head = request(app, "HEAD", "/health/ready")
    assert head.status == 200 and head.body == b""
    assert head.headers["x-content-type-options"] == "nosniff"
    assert head.headers["cache-control"] == "no-store"


def test_a_hanging_backend_cannot_hang_the_probe_or_the_loop(dist) -> None:
    release = threading.Event()

    class Hanging:
        def request(self, method, url, headers, body, *, timeout):
            assert release.wait(10)
            return UpstreamResponse(200, (), b"{}")

    app = app_for(dist, Hanging())

    async def scenario():
        probe = asyncio.create_task(request_async(app, "GET", "/health/ready"))
        await asyncio.sleep(0.2)
        live = await asyncio.wait_for(request_async(app, "GET", "/health/live"), timeout=3)
        release.set()
        return live, await probe

    live, ready = asyncio.run(scenario())
    assert live is not None and live.status == 200
    assert ready is not None and ready.status == 200


def test_the_probe_is_rate_limited_like_any_other_request(dist) -> None:
    app = WebGatewayService(
        dist,
        JOBS,
        DASHBOARD,
        Backends(),
        config=GatewayConfig(rate_limit_per_second=1, rate_limit_burst=2),
        clock=lambda: 0.0,
    )
    statuses = [request(app, "GET", "/health/ready").status for _ in range(4)]
    assert statuses == [200, 200, 429, 429]
    assert request(app, "GET", "/health/live").status == 200


def test_the_body_never_leaks_json_the_backend_returned(dist) -> None:
    class Chatty(Backends):
        def request(self, method, url, headers, body, *, timeout):
            return UpstreamResponse(200, (), json.dumps({"secret": "internal"}).encode())

    resp = request(app_for(dist, Chatty()), "GET", "/health/ready")
    assert "internal" not in resp.body.decode()


def test_concurrent_probes_share_one_refresh_and_never_report_a_false_outage(dist) -> None:
    """Five probes arriving together must cost two backend calls, not trip the probe
    executor's cap and answer 503 for a healthy system."""
    release = threading.Event()
    calls: list[str] = []

    class Slow:
        def request(self, method, url, headers, body, *, timeout):
            calls.append(url)
            assert release.wait(10)
            return UpstreamResponse(200, (), b"{}")

    app = app_for(dist, Slow())

    async def scenario():
        probes = [asyncio.create_task(request_async(app, "GET", "/health/ready")) for _ in range(5)]
        await asyncio.sleep(0.3)
        release.set()
        return await asyncio.gather(*probes)

    replies = asyncio.run(scenario())
    assert all(r is not None and r.status == 200 for r in replies)
    assert len(calls) == 2
