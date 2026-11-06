import asyncio
import hashlib
import json
import logging
import sqlite3
import threading
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode

import pytest
from jsonschema import Draft202012Validator, FormatChecker

from prometheus.evidence.integrity import verify_artifact_integrity
from prometheus.jobs.artifacts import ArtifactStore
from prometheus.jobs.store import JobStore, QueuePolicy
from prometheus.jobs.worker import Worker
from prometheus.orchestration.recipes import RUNNERS, default_recipe
from prometheus.service.application import ResearchService, ServicePolicy
from prometheus.service.auth import CredentialStore
from prometheus.service.schema import job_schema, openapi_document, submission_schema

ALICE, BOB, READER = "a" * 43, "b" * 43, "r" * 43


def auth_entry(token, owner, scopes):
    return {
        "subject": owner + "-" + token[0],
        "owner": owner,
        "scopes": scopes,
        "token_sha256": hashlib.sha256(token.encode()).hexdigest(),
    }


@pytest.fixture
def app(tmp_path):
    auth = tmp_path / "auth"
    auth.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "credentials": [
                    auth_entry(ALICE, "alice", ["read", "write"]),
                    auth_entry(BOB, "bob", ["read", "write"]),
                    auth_entry(READER, "alice", ["read"]),
                ],
            }
        )
    )
    auth.chmod(0o600)
    return ResearchService(
        JobStore(tmp_path / "jobs.sqlite3"),
        ArtifactStore(tmp_path / "artifacts"),
        CredentialStore(auth),
    )


async def request_async(
    app,
    method="GET",
    path="/v1/jobs",
    *,
    body=b"",
    token=ALICE,
    headers=None,
    messages=None,
    client=("127.0.0.1", 1234),
    scheme="http",
):
    if isinstance(body, dict):
        body = json.dumps(body).encode()
    pairs = [(b"host", b"localhost")]
    if token is not None:
        pairs.append((b"authorization", ("Bearer " + token).encode()))
    pairs.extend(headers or [])
    sent = []
    delivered = iter(messages or [{"type": "http.request", "body": body, "more_body": False}])

    async def receive():
        return next(delivered)

    async def send(message):
        sent.append(message)

    path, _, query = path.partition("?")
    await app(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "path": path,
            "query_string": query.encode(),
            "headers": pairs,
            "client": client,
            "scheme": scheme,
        },
        receive,
        send,
    )
    if not sent:
        return None
    status = sent[0]["status"]
    response_headers = dict(sent[0]["headers"])
    raw = b"".join(item.get("body", b"") for item in sent[1:])
    assert int(response_headers[b"content-length"]) == len(raw)
    assert response_headers[b"cache-control"] == b"no-store"
    response = json.loads(raw)
    if status >= 400:
        assert response["error"]["request_id"].encode() == response_headers[b"x-request-id"]
        Draft202012Validator(openapi_document()["components"]["schemas"]["Error"]).validate(
            response
        )
    return status, response, response_headers


def request(app, *args, **kwargs):
    return asyncio.run(request_async(app, *args, **kwargs))


def submit(app, *, token=ALICE, key="sample", config=None, **extra):
    return request(
        app,
        "POST",
        body={"kind": "economy", "config": config or default_recipe("economy"), **extra},
        token=token,
        headers=[(b"content-type", b"application/json"), (b"idempotency-key", key.encode())],
    )


def test_async_submit_idempotency_scope_status_cancel_and_trace_logs(app, caplog):
    caplog.set_level(logging.INFO, logger="prometheus.service.audit")
    status, job, headers = submit(app)
    assert status == 202 and job["status"] == "queued"
    Draft202012Validator(job_schema(), format_checker=FormatChecker()).validate(job)
    assert headers[b"location"] == f"/v1/jobs/{job['job_id']}".encode()
    assert submit(app)[1]["job_id"] == job["job_id"]
    changed = default_recipe("economy")
    changed["seed"] += 1
    assert submit(app, config=changed)[0] == 409
    foreign = submit(app, token=BOB)[1]
    assert foreign["job_id"] != job["job_id"]
    path = f"/v1/jobs/{job['job_id']}"
    assert request(app, path=path, token=BOB)[0] == 404
    assert request(app, "POST", path + "/cancel", token=BOB)[0] == 404
    assert request(app, path=path + "/artifact", token=BOB)[0] == 404
    assert request(app, path=path + "/artifact")[0] == 409
    assert request(app, path=path, token=READER)[1]["job_id"] == job["job_id"]
    assert submit(app, token=READER)[0] == 403
    assert request(app, "POST", path + "/cancel", token=READER)[0] == 403
    assert request(app, "POST", path + "/cancel")[1]["status"] == "cancelled"
    assert request(app, "POST", path + "/cancel")[1]["status"] == "cancelled"
    events = [json.loads(record.message) for record in caplog.records]
    assert any(
        e["job_id"] == job["job_id"] and e["job_trace_id"] == job["trace_id"] for e in events
    )
    assert ALICE not in caplog.text and BOB not in caplog.text
    assert "payroll_target" not in caplog.text


def test_real_worker_output_served_only_after_full_job_binding_and_integrity(app):
    job = submit(app)[1]
    done = Worker(app.jobs, app.artifacts, worker_id="http-integration").run_once()
    assert done.status == "succeeded"
    path = f"/v1/jobs/{job['job_id']}/artifact"
    status, artifact, headers = request(app, path=path)
    assert status == 200
    assert verify_artifact_integrity(artifact, require=True, expected_sha256=done.artifact_sha256)
    encoded = json.dumps(artifact, sort_keys=True, allow_nan=False).encode()
    assert headers[b"etag"] == ('"' + hashlib.sha256(encoded).hexdigest() + '"').encode()
    assert request(app, path=path)[1] == artifact
    assert request(app, path=path, token=BOB)[0] == 404
    original = app.artifacts.get
    app.artifacts.get = lambda digest: {
        **original(digest),
        "job_context": {},
    }  # verified store boundary fault
    assert request(app, path=path)[1]["error"]["code"] == "artifact_unavailable"


@pytest.mark.parametrize(
    "body,status,code",
    [
        (b'{"kind":"economy","kind":"simulation"}', 400, "invalid_json"),
        (b'{"x":1e9999}', 400, "invalid_json"),
        (b'{"x":NaN}', 400, "invalid_json"),
        (b"\xff", 400, "invalid_json"),
        (b"[]", 422, "invalid_kind"),
        (b'{"kind":"shell"}', 422, "invalid_kind"),
        (b'{"kind":"economy","config":{}}', 422, "schema_error"),
    ],
)
def test_malformed_json_and_wire_schema_fail_before_queue_mutation(app, body, status, code):
    result = request(
        app,
        "POST",
        body=body,
        headers=[(b"content-type", b"application/json"), (b"idempotency-key", b"sample")],
    )
    assert result[0] == status and result[1]["error"]["code"] == code
    assert request(app)[1]["jobs"] == []


def test_owner_injection_dates_currencies_precision_and_work_are_rejected(app):
    assert submit(app, owner="bob")[0] == 422
    raw = default_recipe("economy")
    raw["start_date"] = "2026-02-30"
    result = submit(app, config=raw)
    assert result[0] == 422 and result[1]["error"]["field"] == "config.start_date"
    raw = default_recipe("economy")
    raw["firm_capital"]["currency"] = "EUR"
    assert submit(app, config=raw)[0] == 422
    raw = default_recipe("economy")
    raw["n_steps"] = True
    assert submit(app, config=raw)[1]["error"]["code"] == "schema_error"
    raw["n_steps"] = 241
    assert submit(app, config=raw)[1]["error"]["code"] == "resource_limit"
    raw["n_steps"] = 2**64
    assert submit(app, config=raw)[1]["error"]["code"] == "resource_limit"
    assert request(app)[1]["jobs"] == []


@pytest.mark.parametrize(
    "headers,status",
    [
        ([], 415),
        ([(b"content-type", b"text/plain")], 415),
        ([(b"content-type", b"application/json")], 400),
        ([(b"content-length", b"99999999")], 413),
        ([(b"content-length", b"-1")], 400),
        ([(b"content-length", b"2"), (b"transfer-encoding", b"chunked")], 400),
        ([(b"content-encoding", b"gzip")], 400),
        ([(b"host", b"second")], 400),
        ([(b"authorization", b"Bearer another")], 400),
        ([(b"x-bad", b"secret\r\n")], 400),
    ],
)
def test_header_media_framing_and_idempotency_errors(app, headers, status):
    assert request(app, "POST", body=b"{}", headers=headers)[0] == status


def test_authentication_tls_forwarded_header_spoof_and_no_query_credentials(app):
    assert request(app, token=None)[0] == 401
    assert request(app, token="x" * 43)[0] == 401
    assert request(app, token=None)[2][b"www-authenticate"] == b"Bearer"
    assert request(app, path="/v1/jobs?token=" + ALICE, token=None)[0] == 401
    assert (
        request(app, client=("192.0.2.1", 1), headers=[(b"x-forwarded-proto", b"https")])[0] == 403
    )
    assert request(app, client=("192.0.2.1", 1), scheme="https")[0] == 200
    app.policy = replace(app.policy, allow_loopback_http=False)
    assert request(app)[0] == 403


def test_cursor_pagination_never_crosses_owner_scope(app):
    ids = [submit(app, key=f"page-{n}")[1]["job_id"] for n in range(3)]
    first = request(app, path="/v1/jobs?limit=2")[1]
    assert [job["job_id"] for job in first["jobs"]] == ids[:2]
    query = urlencode({"limit": 2, "cursor": first["next_cursor"]})
    last = request(app, path="/v1/jobs?" + query)[1]
    assert [job["job_id"] for job in last["jobs"]] == ids[2:] and last["next_cursor"] is None
    assert request(app, path="/v1/jobs?" + query, token=BOB)[0] == 400
    for query in (
        "limit=0",
        "limit=101",
        "limit=1&limit=2",
        "unknown=x",
        "cursor=bad",
        "owner=alice",
    ):
        assert request(app, path="/v1/jobs?" + query)[0] == 400


def test_liveness_survives_dependencies_and_readiness_does_not_recreate_database(app):
    assert request(app, path="/health/live", token=None)[1] == {"status": "live"}
    assert request(app, path="/health/ready", token=None)[0] == 200
    app.jobs.path.unlink()
    assert request(app, path="/health/ready", token=None)[0] == 503
    assert not app.jobs.path.exists()
    assert request(app, path="/health/live", token=None)[0] == 200


def test_readiness_checks_writer_contention_and_policy_without_mutation(app):
    connection = sqlite3.connect(app.jobs.path, isolation_level=None)
    connection.execute("BEGIN IMMEDIATE")
    try:
        assert request(app, path="/health/ready", token=None)[0] == 503
    finally:
        connection.close()
    assert request(app, path="/health/ready", token=None)[0] == 200
    with closing(sqlite3.connect(app.jobs.path, isolation_level=None)) as connection:
        connection.execute("UPDATE settings SET value='changed' WHERE key='policy'")
    assert request(app, path="/health/ready", token=None)[0] == 503


def test_rotation_and_missing_credentials_fail_closed_but_liveness_survives(app):
    config = json.loads(app.credentials.path.read_text())
    config["credentials"] = config["credentials"][1:]
    app.credentials.path.write_text(json.dumps(config))
    assert request(app)[0] == 401
    assert request(app, token=BOB)[0] == 200
    app.credentials.path.unlink()
    assert request(app, token=BOB)[0] == 503
    assert request(app, path="/health/ready", token=None)[0] == 503
    assert request(app, path="/health/live", token=None)[0] == 200


def test_body_limits_slow_reads_disconnect_and_large_headers(app):
    app.policy = replace(
        app.policy, max_body_bytes=8, max_headers=4, max_header_bytes=512, body_timeout_seconds=0.01
    )
    assert request(app, body=b"123456789")[0] == 413
    assert request(app, body=b"x", headers=[(b"content-length", b"2")])[0] == 400
    assert request(app, headers=[(b"x-large", b"x" * 512)])[0] == 431
    assert request(app, headers=[(b"x-a", b"1"), (b"x-b", b"1"), (b"x-c", b"1")])[0] == 431
    assert request(app, messages=[{"type": "http.disconnect"}]) is None

    async def slow_read():
        sent = []

        async def receive():
            await asyncio.sleep(1)

        async def send(message):
            sent.append(message)

        await app(
            {
                "type": "http",
                "method": "GET",
                "path": "/health/live",
                "headers": [],
                "query_string": b"",
                "scheme": "http",
                "client": ("127.0.0.1", 1),
            },
            receive,
            send,
        )
        assert sent[0]["status"] == 408

    asyncio.run(slow_read())


def test_rel_10_capacity_quotas_reject_with_distinct_transparent_reasons(app, tmp_path):
    """REL-10: "define capacity reservation and user quota policies ...
    requests exceeding quota rejected with transparent reason." Two
    DIFFERENT quota mechanisms already exist in this service --
    per-owner request-RATE quota (`ServicePolicy.requests_per_owner`)
    and per-owner PENDING-QUEUE quota (`QueuePolicy.
    max_pending_per_owner`) -- states that claim explicitly rather than
    inferring it from the scattered pre-existing tests below: each is
    rejected with its OWN distinct, named error code (not one generic
    "rejected"), so a caller can tell WHICH quota it exceeded, and a
    request within either quota still succeeds."""
    rate_limited_service = ResearchService(
        app.jobs, app.artifacts, app.credentials, policy=ServicePolicy(requests_per_owner=1)
    )
    assert request(rate_limited_service)[0] == 200
    rate_rejection = request(rate_limited_service, token=READER)
    assert rate_rejection[1]["error"]["code"] == "rate_limited"

    queue_jobs = JobStore(tmp_path / "rel10.sqlite3", policy=QueuePolicy(max_pending_per_owner=1))
    queue_limited_service = ResearchService(queue_jobs, app.artifacts, app.credentials)
    assert submit(queue_limited_service)[0] == 202
    queue_rejection = submit(queue_limited_service, key="second")
    assert queue_rejection[1]["error"]["code"] == "quota_exceeded"

    assert rate_rejection[1]["error"]["code"] != queue_rejection[1]["error"]["code"]


def test_process_local_rate_and_pending_queue_quotas_have_distinct_errors(app, tmp_path):
    clock = [0.0]
    limited = ResearchService(
        app.jobs,
        app.artifacts,
        app.credentials,
        policy=ServicePolicy(requests_per_owner=1),
        clock=lambda: clock[0],
    )
    assert request(limited)[0] == 200
    assert request(limited, token=READER)[1]["error"]["code"] == "rate_limited"
    assert request(limited, token=BOB)[0] == 200
    clock[0] += 60
    assert request(limited)[0] == 200
    jobs = JobStore(tmp_path / "limited.sqlite3", policy=QueuePolicy(max_pending_per_owner=1))
    queue_limited = ResearchService(jobs, app.artifacts, app.credentials)
    assert submit(queue_limited)[0] == 202
    assert submit(queue_limited)[0] == 202  # Idempotent retry at queue capacity.
    assert submit(queue_limited, key="second")[1]["error"]["code"] == "quota_exceeded"


def test_global_rate_budget_counts_rejected_authentication_and_recovers_after_window(app):
    clock = [0.0]
    limited = ResearchService(
        app.jobs,
        app.artifacts,
        app.credentials,
        policy=ServicePolicy(requests_global=2),
        clock=lambda: clock[0],
    )
    assert request(limited, token=None)[0] == 401
    assert request(limited, token="x" * 43)[0] == 401
    rejected = request(limited)
    assert rejected[0] == 429 and rejected[1]["error"]["code"] == "rate_limited"
    assert int(rejected[2][b"retry-after"]) >= 1
    clock[0] += 60
    assert request(limited)[0] == 200


def test_cancelled_http_caller_does_not_release_capacity_while_thread_still_commits(
    app, monkeypatch
):
    async def exercise():
        original = app.jobs.list_jobs
        entered, release = threading.Event(), threading.Event()

        def blocked(**kwargs):
            entered.set()
            assert release.wait(3)
            return original(**kwargs)

        monkeypatch.setattr(app.jobs, "list_jobs", blocked)
        app.admission.policy = replace(app.policy, max_inflight=1)
        task = asyncio.create_task(request_async(app))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert app.admission.inflight == 1
            overloaded = await request_async(app)
            assert overloaded[0] == 503 and overloaded[1]["error"]["code"] == "overloaded"
        finally:
            release.set()
            if app.pending:
                await asyncio.gather(*app.pending)
        assert app.admission.inflight == 0

    asyncio.run(exercise())


def test_contract_all_nine_default_recipes_and_exact_research_only_route_surface(app):
    document = openapi_document()
    fixture = Path(__file__).resolve().parents[2] / "docs/api/openapi-v1.json"
    assert json.loads(fixture.read_text()) == document
    Draft202012Validator.check_schema(submission_schema())
    assert document["openapi"] == "3.1.1"
    validator = Draft202012Validator(submission_schema(), format_checker=FormatChecker())
    for kind in RUNNERS:
        validator.validate({"kind": kind, "config": default_recipe(kind)})
    assert set(document["paths"]) == {
        "/health/live",
        "/health/ready",
        "/v1/openapi.json",
        "/v1/jobs",
        "/v1/jobs/{job_id}",
        "/v1/jobs/{job_id}/cancel",
        "/v1/jobs/{job_id}/artifact",
    }
    assert request(app, path="/v1/openapi.json")[1] == document
    for path in ("/v1/orders", "/v1/payments", "/v1/trades", "/v1/jobs/not-a-uuid"):
        assert request(app, path=path)[0] == 404
    assert request(app, "DELETE")[2][b"allow"] == b"GET, POST"


def test_internal_error_is_correlated_without_exposing_exception_or_recipe(
    app, monkeypatch, caplog
):
    caplog.set_level(logging.INFO, logger="prometheus.service.audit")

    def broken(*args, **kwargs):
        raise RuntimeError("private-infrastructure-detail")

    monkeypatch.setattr(app, "_dispatch", broken)
    response = request(app)
    assert response[0] == 500 and response[1]["error"]["code"] == "internal_error"
    assert "private-infrastructure-detail" not in json.dumps(response[1]) + caplog.text
    event = json.loads(caplog.records[-1].message)
    assert event["diagnostic_id"] == response[1]["error"]["diagnostic_id"]


def test_lifespan_drain_and_websocket_denial(app):
    async def exercise():
        messages = iter([{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}])
        sent = []

        async def receive():
            return next(messages)

        async def send(message):
            sent.append(message)

        await app({"type": "lifespan"}, receive, send)
        assert [message["type"] for message in sent] == [
            "lifespan.startup.complete",
            "lifespan.shutdown.complete",
        ]
        assert (await request_async(app))[0] == 503
        assert (await request_async(app, path="/health/live", token=None))[0] == 200
        await app({"type": "websocket"}, receive, send)
        assert sent[-1] == {"type": "websocket.close", "code": 1008}

    asyncio.run(exercise())
