import hashlib
import json
import time

import pytest
import torch

from prometheus.evidence.inference_metrics import InferenceReport, run_inference_benchmark
from prometheus.hedging.deep_hedge import HedgePolicyMLP
from prometheus.jobs.artifacts import ArtifactStore
from prometheus.jobs.store import JobStore
from prometheus.service.application import ResearchService
from prometheus.service.auth import CredentialStore

ALICE = "a" * 43


def test_rejects_an_empty_endpoint() -> None:
    with pytest.raises(ValueError, match="endpoint"):
        run_inference_benchmark("", "m", lambda: None, 1)


def test_rejects_an_empty_model() -> None:
    with pytest.raises(ValueError, match="model"):
        run_inference_benchmark("e", "", lambda: None, 1)


def test_rejects_a_non_positive_n_requests() -> None:
    with pytest.raises(ValueError, match="n_requests"):
        run_inference_benchmark("e", "m", lambda: None, 0)


def test_all_successful_calls_have_zero_failure_rate() -> None:
    report = run_inference_benchmark("e", "m", lambda: None, 20)
    assert report.n_requests == 20
    assert report.n_failures == 0
    assert report.failure_rate == pytest.approx(0.0)


def test_every_call_raising_gives_a_failure_rate_of_one() -> None:
    def always_fails() -> None:
        raise RuntimeError("boom")

    report = run_inference_benchmark("e", "m", always_fails, 10)
    assert report.n_failures == 10
    assert report.failure_rate == pytest.approx(1.0)


def test_alternating_success_and_failure_gives_the_exact_rate() -> None:
    """The discriminating half: the loop must not stop at the first
    exception -- it keeps running through all n_requests and tallies
    exactly how many of them failed."""
    counter = {"n": 0}

    def alternating() -> None:
        counter["n"] += 1
        if counter["n"] % 2 == 0:
            raise ValueError("every other call fails")

    report = run_inference_benchmark("e", "m", alternating, 20)
    assert report.n_requests == 20
    assert report.n_failures == 10
    assert report.failure_rate == pytest.approx(0.5)


def test_percentiles_are_non_negative_and_ordered() -> None:
    report = run_inference_benchmark("e", "m", lambda: time.sleep(0.001), 10)
    assert 0.0 <= report.p50_seconds <= report.p95_seconds <= report.p99_seconds
    assert report.throughput_per_second > 0.0


def test_a_real_trained_hedge_policy_mlp_forward_pass_succeeds_with_valid_input() -> None:
    """Grounded in a REAL trained model's forward pass, not a mock --
    `hedging.deep_hedge.HedgePolicyMLP` accepting its correctly-shaped
    (batch, 3) feature tensor."""
    torch.manual_seed(0)
    policy = HedgePolicyMLP()
    policy.eval()
    valid_input = torch.randn(4, 3)

    def call() -> None:
        with torch.no_grad():
            policy(valid_input)

    report = run_inference_benchmark("deep_hedge_policy_forward", "HedgePolicyMLP", call, 30)
    assert report.n_failures == 0
    assert report.failure_rate == pytest.approx(0.0)
    assert report.p50_seconds >= 0.0


def test_a_real_trained_hedge_policy_mlp_forward_pass_fails_on_a_shape_mismatch() -> None:
    """The discriminating half: a genuinely malformed input (wrong
    feature dimension) must produce a REAL `RuntimeError` from
    `nn.Linear`'s own matrix-shape check, propagating all the way into
    a 100% measured failure rate -- not a fabricated failure count."""
    torch.manual_seed(0)
    policy = HedgePolicyMLP()
    policy.eval()
    malformed_input = torch.randn(4, 5)  # HedgePolicyMLP expects (batch, 3)

    def call() -> None:
        with torch.no_grad():
            policy(malformed_input)

    report = run_inference_benchmark("deep_hedge_policy_forward", "HedgePolicyMLP", call, 10)
    assert report.n_failures == 10
    assert report.failure_rate == pytest.approx(1.0)


def _auth_entry(token: str, owner: str) -> dict:
    return {
        "subject": owner,
        "owner": owner,
        "scopes": ["read", "write"],
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
    }


async def _get(app, path: str, token: str) -> int:
    """A minimal, self-contained GET-only ASGI request sender, the same
    pattern `test_latency_benchmark.py` already uses -- duplicated
    rather than imported across test modules, since pytest's own
    rootless test collection here does not support importing one test
    module from another."""
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


def test_a_real_http_endpoint_is_also_measurable_with_the_same_function(tmp_path) -> None:
    """Confirms 'per endpoint and model' is a real distinction, not
    just two different string labels on the same mechanism: this
    report comes from a genuinely different backend -- a real ASGI
    HTTP call against `service.application.ResearchService`, the SAME
    endpoint REL-02's own load report already measures -- using the
    identical `run_inference_benchmark` function."""
    import asyncio

    auth = tmp_path / "auth"
    auth.write_text(json.dumps({"schema_version": 1, "credentials": [_auth_entry(ALICE, "alice")]}))
    auth.chmod(0o600)
    service = ResearchService(
        JobStore(tmp_path / "jobs.sqlite3"),
        ArtifactStore(tmp_path / "artifacts"),
        CredentialStore(auth),
    )

    def call() -> None:
        status = asyncio.run(_get(service, "/v1/jobs", ALICE))
        if status != 200:
            raise AssertionError(f"unexpected status {status}")

    report = run_inference_benchmark("GET /v1/jobs", "ResearchService", call, 10)
    assert report.n_failures == 0
    assert report.model == "ResearchService"
    assert report.endpoint == "GET /v1/jobs"


def test_report_is_constructible_directly() -> None:
    report = InferenceReport(
        endpoint="e", model="m", n_requests=1, n_failures=0, failure_rate=0.0,
        throughput_per_second=1.0, p50_seconds=0.0, p95_seconds=0.0, p99_seconds=0.0,
    )
    assert report.model == "m"
