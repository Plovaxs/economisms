import asyncio
import hashlib
import json
import time

import pytest

from prometheus.evidence.slo_definitions import ServiceLevelObjective, slo_is_met
from prometheus.experiments.latency_benchmark import build_load_report
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


def _metadata_slo() -> ServiceLevelObjective:
    return ServiceLevelObjective(
        service_name="prometheus-research-service",
        sli_description="p95 latency of GET /v1/jobs (job metadata listing)",
        endpoint="GET /v1/jobs",
        target_p95_seconds=1.0,
        workload_assumption="up to 8 concurrent requests from a single owner, in-process ASGI",
        approved_by="alice",
    )


def test_rejects_an_empty_service_name() -> None:
    with pytest.raises(ValueError, match="service_name"):
        ServiceLevelObjective("", "p95 latency", "GET /x", 1.0, "some load", "alice")


def test_rejects_an_empty_sli_description() -> None:
    with pytest.raises(ValueError, match="sli_description"):
        ServiceLevelObjective("svc", "", "GET /x", 1.0, "some load", "alice")


def test_rejects_an_empty_endpoint() -> None:
    with pytest.raises(ValueError, match="endpoint"):
        ServiceLevelObjective("svc", "p95 latency", "", 1.0, "some load", "alice")


def test_rejects_a_non_positive_target() -> None:
    with pytest.raises(ValueError, match="target_p95_seconds"):
        ServiceLevelObjective("svc", "p95 latency", "GET /x", 0.0, "some load", "alice")


def test_rejects_an_empty_workload_assumption() -> None:
    """REL-01's own acceptance criterion: "approved SLO sheet contains
    workload assumptions" -- a missing one is rejected outright, not
    silently defaulted."""
    with pytest.raises(ValueError, match="workload_assumption"):
        ServiceLevelObjective("svc", "p95 latency", "GET /x", 1.0, "", "alice")


def test_rejects_an_empty_approver() -> None:
    with pytest.raises(ValueError, match="approved_by"):
        ServiceLevelObjective("svc", "p95 latency", "GET /x", 1.0, "some load", "")


def test_slo_is_met_rejects_a_report_for_a_different_endpoint() -> None:
    slo = _metadata_slo()
    report = build_load_report("POST /v1/jobs", {"POST /v1/jobs": 1}, 1, [0.01])
    with pytest.raises(ValueError, match="own endpoint"):
        slo_is_met(slo, report)


def test_a_real_load_report_against_the_metadata_endpoint_meets_its_own_slo(real_service) -> None:
    """Closes the loop with REL-02: a genuine `LoadReport` measured
    against the real `ResearchService` ASGI application's GET /v1/jobs
    endpoint, at the SAME workload shape (concurrency 8) the SLO's own
    `workload_assumption` names, is confirmed to meet it -- not a
    fabricated report built to pass."""
    concurrency = 8
    n_batches = 10
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
    assert slo_is_met(_metadata_slo(), report) is True
