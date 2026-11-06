import io
import json
import socket
import subprocess
import sys
import time
from email.message import Message
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from prometheus.jobs.artifacts import ArtifactStore
from prometheus.jobs.store import JobStore
from prometheus.jobs.worker import Worker
from prometheus.orchestration.recipes import default_recipe
from prometheus.service.__main__ import main, provision_credentials
from prometheus.service.client import (
    ClientProtocolError,
    ClientTransportError,
    JobSnapshot,
    ResearchClient,
    ServiceError,
)


@pytest.fixture
def network_service(tmp_path):
    credentials, token_file = tmp_path / "auth", tmp_path / "token"
    provision_credentials(credentials, token_file, owner="alice", read_only=False)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(32)
    origin = f"http://127.0.0.1:{listener.getsockname()[1]}"
    script = """
import pathlib,socket,sys,uvicorn
from prometheus.jobs.store import JobStore
from prometheus.jobs.artifacts import ArtifactStore
from prometheus.service.application import ResearchService
from prometheus.service.auth import CredentialStore
root=pathlib.Path(sys.argv[1])
app=ResearchService(JobStore(root/'jobs.sqlite3'),ArtifactStore(root/'artifacts'),CredentialStore(root/'auth'))
config=uvicorn.Config(app,log_level='critical',access_log=False,proxy_headers=False,lifespan='on',http='h11',ws='none')
uvicorn.Server(config).run(sockets=[socket.socket(fileno=int(sys.argv[2]))])
"""
    log = (tmp_path / "server.log").open("wb")
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path), str(listener.fileno())],
        pass_fds=(listener.fileno(),),
        stdout=log,
        stderr=log,
    )
    listener.close()
    client = ResearchClient(origin, token_file.read_text().strip(), timeout_seconds=0.5)
    try:
        until = time.monotonic() + 10
        while True:
            assert process.poll() is None, (tmp_path / "server.log").read_text()
            try:
                client.list_jobs()
                break
            except ClientTransportError:
                assert time.monotonic() < until, (tmp_path / "server.log").read_text()
                time.sleep(0.02)
        yield client, tmp_path
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        log.close()


def test_real_socket_typed_sdk_submission_worker_artifact_and_revocation(network_service):
    client, root = network_service
    config = default_recipe("economy")
    config["n_steps"] = 2
    config["productivity_shock_step"] = None
    job = client.submit("economy", config, idempotency_key="socket-reference", timeout_seconds=20)
    assert isinstance(job, JobSnapshot) and job.status == "queued"
    assert (
        client.submit(
            "economy", config, idempotency_key="socket-reference", timeout_seconds=20
        ).job_id
        == job.job_id
    )
    assert client.get_job(job.job_id).created_at.tzinfo is not None
    with pytest.raises(TypeError):
        job.resource_estimate["steps"] = 999
    config["seed"] += 1
    with pytest.raises(ServiceError) as conflict:
        client.submit("economy", config, idempotency_key="socket-reference", timeout_seconds=20)
    assert conflict.value.status == 409 and conflict.value.code == "idempotency_conflict"
    with pytest.raises(ServiceError) as pending:
        client.get_artifact(job.job_id)
    assert pending.value.code == "artifact_pending"
    completed = Worker(
        JobStore(root / "jobs.sqlite3"),
        ArtifactStore(root / "artifacts"),
        worker_id="socket-worker",
    ).run_once()
    assert completed.status == "succeeded"
    assert client.get_job(job.job_id).result_hash == completed.result_hash
    artifact = client.get_artifact(job.job_id)
    assert artifact["job_context"]["trace_id"] == job.trace_id
    second = client.submit("economy", config, idempotency_key="cancel-reference")
    assert client.cancel_job(second.job_id).status == "cancelled"
    page = client.list_jobs(limit=1)
    assert page.jobs[0].job_id == job.job_id and page.next_cursor
    assert client.list_jobs(limit=1, cursor=page.next_cursor).jobs[0].job_id == second.job_id
    config = json.loads((root / "auth").read_text())
    config["credentials"][0]["token_sha256"] = "0" * 64
    (root / "auth").write_text(json.dumps(config))
    with pytest.raises(ServiceError) as denied:
        client.list_jobs()
    assert denied.value.status == 401
    assert len(denied.value.diagnostic_id) == len(denied.value.request_id) == 32
    assert client._token not in str(denied.value)


@pytest.mark.parametrize(
    "origin",
    [
        "http://192.0.2.1",
        "http://example.com",
        "ftp://127.0.0.1",
        "https://token@example.com",
        "https://example.com/path",
        "https://example.com?token=secret",
        "https://example.com#fragment",
        "https://example.com\n",
    ],
)
def test_client_rejects_unsafe_origins(origin):
    with pytest.raises(ValueError):
        ResearchClient(origin, "a" * 43)


class FakeResponse(io.BytesIO):
    def __init__(self, body, *, content_type="application/json", length=None):
        super().__init__(body)
        self.headers = Message()
        self.headers["Content-Type"] = content_type
        self.headers["Content-Length"] = str(len(body) if length is None else length)


@pytest.mark.parametrize(
    "response",
    [
        lambda: FakeResponse(b"[]"),
        lambda: FakeResponse(b'{"x":NaN}'),
        lambda: FakeResponse(b'{"x":1,"x":2}'),
        lambda: FakeResponse(b"{}", content_type="text/plain"),
        lambda: FakeResponse(b"{}", length=10),
        lambda: FakeResponse(b"{}", length=999),
        lambda: FakeResponse(b"{}", length="-1"),
    ],
)
def test_client_bounds_and_strictly_decodes_response(response):
    client = ResearchClient("http://127.0.0.1", "a" * 43, max_response_bytes=16)
    client._opener = SimpleNamespace(open=lambda *a, **kw: response())
    with pytest.raises(ClientProtocolError):
        client.list_jobs()


def test_client_refuses_redirects_and_does_not_inherit_environment_proxies(monkeypatch):
    from urllib.request import HTTPRedirectHandler

    monkeypatch.setenv("HTTP_PROXY", "http://127.0.0.1:1")
    client = ResearchClient("http://127.0.0.1", "a" * 43)
    redirect = next(
        handler for handler in client._opener.handlers if isinstance(handler, HTTPRedirectHandler)
    )
    assert redirect.redirect_request(None, None, 302, "Found", {}, "https://other.example") is None
    assert not any(
        hasattr(handler, "proxies") and handler.proxies for handler in client._opener.handlers
    )

    def failed(*args, **kwargs):
        headers = Message()
        headers["Content-Type"] = "application/json"
        raise HTTPError("http://127.0.0.1", 302, "Found", headers, io.BytesIO(b"{}"))

    client._opener = SimpleNamespace(open=failed)
    with pytest.raises(ClientProtocolError):
        client.list_jobs()


def test_cli_provisioning_schema_no_secret_output_and_nonlocal_tls_enforcement(tmp_path, capsys):
    auth, token = tmp_path / "auth", tmp_path / "token"
    assert (
        main(
            [
                "init-auth",
                "--credentials",
                str(auth),
                "--token-file",
                str(token),
                "--owner",
                "alice",
            ]
        )
        == 0
    )
    assert token.read_text().strip() not in capsys.readouterr().out
    schema = tmp_path / "openapi.json"
    assert main(["openapi", "--output", str(schema)]) == 0
    assert json.loads(schema.read_text())["info"]["version"] == "1.0.0"
    with pytest.raises(SystemExit):
        main(["serve", "--root", str(tmp_path), "--credentials", str(auth), "--host", "0.0.0.0"])


def test_cli_server_uses_explicit_protocol_and_proxy_configuration(tmp_path, monkeypatch):
    import uvicorn

    auth, token = tmp_path / "auth", tmp_path / "token"
    provision_credentials(auth, token, owner="alice", read_only=True)
    observed = {}
    monkeypatch.setattr(uvicorn, "run", lambda app, **kwargs: observed.update(kwargs))
    assert main(["serve", "--root", str(tmp_path), "--credentials", str(auth)]) == 0
    assert observed["host"] == "127.0.0.1" and observed["workers"] == 1
    assert observed["proxy_headers"] is False and observed["access_log"] is False
    assert observed["http"] == "h11" and observed["ws"] == "none"
    assert observed["limit_concurrency"] == 32
