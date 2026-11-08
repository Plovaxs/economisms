import asyncio
import hashlib
import json
import time

import pytest

from prometheus.experiments.latency_benchmark import build_load_report, meets_p95_target
from prometheus.jobs.artifacts import ArtifactStore
from prometheus.jobs.store import JobStore
from prometheus.service.application import ResearchService
from prometheus.service.auth import CredentialStore

ALICE = "a" * 43


def _auth_entry(token: str, owner: str) -> dict:
    return {
        "subject": owner,
        "owner": owner,
        "scopes": ["read", "write"],
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
    }


@pytest.fixture
def real_service(tmp_path):
    auth = tmp_path / "auth"
    auth.write_text(json.dumps({"schema_version": 1, "credentials": [_auth_entry(ALICE, "alice")]}))
    auth.chmod(0o600)
    return ResearchService(
        JobStore(tmp_path / "jobs.sqlite3"),
        ArtifactStore(tmp_path / "artifacts"),
        CredentialStore(auth),
    )


async def _get(app, path: str, token: str) -> int:
    """A minimal, self-contained GET-only ASGI request sender -- the
    same wire protocol `tests/unit/test_service_http.py`'s own
    `request_async` drives, trimmed to just the metadata reads this
    benchmark needs (duplicated rather than imported across test
    modules, since pytest's own rootless test collection here does not
    support importing one test module from another)."""
    sent: list[dict] = []
    delivered = iter([{"type": "http.request", "body": b"", "more_body": False}])

    async def receive():
        return next(delivered)

    async def send(message):
        sent.append(message)

    await app(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "path": path,
            "query_string": b"",
            "headers": [(b"host", b"localhost"), (b"authorization", ("Bearer " + token).encode())],
            "client": ("127.0.0.1", 1234),
            "scheme": "http",
        },
        receive,
        send,
    )
    status: int = sent[0]["status"]
    return status


def test_build_load_report_rejects_an_empty_endpoint() -> None:
    with pytest.raises(ValueError, match="endpoint"):
        build_load_report("", {"GET /v1/jobs": 1}, concurrency=1, latencies_seconds=[0.01])


def test_build_load_report_rejects_an_empty_request_mix() -> None:
    with pytest.raises(ValueError, match="request_mix"):
        build_load_report("GET /v1/jobs", {}, concurrency=1, latencies_seconds=[0.01])


def test_build_load_report_rejects_a_non_positive_concurrency() -> None:
    with pytest.raises(ValueError, match="concurrency"):
        build_load_report(
            "GET /v1/jobs", {"GET /v1/jobs": 1}, concurrency=0, latencies_seconds=[0.01]
        )


def test_build_load_report_rejects_empty_latencies() -> None:
    with pytest.raises(ValueError, match="latencies_seconds"):
        build_load_report("GET /v1/jobs", {"GET /v1/jobs": 1}, concurrency=1, latencies_seconds=[])


def test_percentiles_are_computed_from_real_known_latencies() -> None:
    """Not an estimate: the exact percentiles of a deliberately simple,
    known latency sample (0.0, 0.01, ..., 0.99 seconds, 100 values)."""
    latencies = [i / 100 for i in range(100)]
    report = build_load_report(
        "GET /v1/jobs", {"GET /v1/jobs": 100}, concurrency=1, latencies_seconds=latencies
    )
    assert report.p50_seconds == pytest.approx(0.495, abs=0.01)
    assert report.p95_seconds == pytest.approx(0.9405, abs=0.01)
    assert report.n_requests == 100


def test_meets_p95_target_discriminates_pass_and_fail() -> None:
    report = build_load_report(
        "GET /v1/jobs", {"GET /v1/jobs": 10}, concurrency=1, latencies_seconds=[0.1] * 10
    )
    assert meets_p95_target(report, max_p95_seconds=0.2) is True
    assert meets_p95_target(report, max_p95_seconds=0.05) is False


def test_rel_02_real_metadata_api_load_report_on_this_reference_hardware(real_service) -> None:
    """REL-02's own acceptance criterion: "load report includes request
    mix and concurrency," grounded in a REAL p95 measurement against
    the actual `ResearchService` ASGI application's metadata endpoint
    (GET /v1/jobs), not a synthetic latency array -- at a genuine
    concurrency of 8 simultaneous requests, exercised via
    `asyncio.gather` against the same in-process ASGI protocol
    `test_service_http.py` itself drives. "Reference hardware" here
    means this machine, honestly labeled as such, not a claimed
    production benchmark."""
    concurrency = 8
    n_batches = 15
    latencies: list[float] = []

    async def timed_request() -> float:
        start = time.perf_counter()
        status = await _get(real_service, "/v1/jobs", ALICE)
        elapsed = time.perf_counter() - start
        assert status == 200
        return elapsed

    async def run() -> None:
        for _ in range(n_batches):
            batch = await asyncio.gather(*(timed_request() for _ in range(concurrency)))
            latencies.extend(batch)

    asyncio.run(run())

    report = build_load_report(
        endpoint="GET /v1/jobs",
        request_mix={"GET /v1/jobs": len(latencies)},
        concurrency=concurrency,
        latencies_seconds=latencies,
    )
    assert report.n_requests == concurrency * n_batches
    assert report.concurrency == concurrency
    # A generous target for an in-process, no-network ASGI call on local
    # hardware -- published as this run's own number, not assumed to
    # generalize to a deployed, networked environment.
    assert meets_p95_target(report, max_p95_seconds=1.0)
