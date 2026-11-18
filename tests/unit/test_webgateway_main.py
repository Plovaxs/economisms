"""Only argument validation is unit-tested here, the same discipline
`test_dashboard_main.py` documents: `serve` starts a real uvicorn
listener outside of the validation checked below, which is mocked out
rather than actually bound -- `serve` was additionally verified for
real by actually running the full local stack (worker, jobs API,
dashboard, gateway) and submitting a real job all the way through it;
see CHECKLIST_STATUS.md's PR-187 entry.
"""

from __future__ import annotations

import pytest

from prometheus.httpsec.server import uvicorn_options
from prometheus.webgateway.__main__ import main


@pytest.fixture
def dist_root(tmp_path):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html>spa shell</html>")
    return root


def _mock_uvicorn_run(monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.append({"app": app, **kwargs}))
    return calls


def test_default_loopback_binding_is_accepted(dist_root, monkeypatch) -> None:
    calls = _mock_uvicorn_run(monkeypatch)
    exit_code = main(["serve", "--dist", str(dist_root)])
    assert exit_code == 0
    assert calls[0]["host"] == "127.0.0.1"


def test_non_loopback_without_tls_or_the_flag_is_rejected(dist_root, monkeypatch) -> None:
    _mock_uvicorn_run(monkeypatch)
    with pytest.raises(SystemExit):
        main(["serve", "--dist", str(dist_root), "--host", "0.0.0.0"])


def test_non_loopback_with_the_explicit_flag_is_accepted(dist_root, monkeypatch) -> None:
    calls = _mock_uvicorn_run(monkeypatch)
    exit_code = main(
        [
            "serve",
            "--dist",
            str(dist_root),
            "--host",
            "0.0.0.0",
            "--allow-non-loopback-without-tls",
        ]
    )
    assert exit_code == 0
    assert calls[0]["host"] == "0.0.0.0"


def test_non_loopback_with_tls_is_accepted_without_the_flag(
    dist_root, tmp_path, monkeypatch
) -> None:
    calls = _mock_uvicorn_run(monkeypatch)
    cert, key = tmp_path / "cert.pem", tmp_path / "key.pem"
    exit_code = main(
        [
            "serve",
            "--dist",
            str(dist_root),
            "--host",
            "0.0.0.0",
            "--tls-cert",
            str(cert),
            "--tls-key",
            str(key),
        ]
    )
    assert exit_code == 0
    assert calls[0]["ssl_certfile"] == str(cert)


def test_mismatched_tls_cert_and_key_is_rejected(dist_root, tmp_path, monkeypatch) -> None:
    _mock_uvicorn_run(monkeypatch)
    with pytest.raises(SystemExit):
        main(["serve", "--dist", str(dist_root), "--tls-cert", str(tmp_path / "cert.pem")])


def test_a_dist_root_that_was_never_built_is_rejected(tmp_path, monkeypatch) -> None:
    _mock_uvicorn_run(monkeypatch)
    with pytest.raises(SystemExit):
        main(["serve", "--dist", str(tmp_path / "never-built")])


def test_the_shipped_uvicorn_options_are_hardened(dist_root, monkeypatch) -> None:
    calls = _mock_uvicorn_run(monkeypatch)
    assert main(["serve", "--dist", str(dist_root)]) == 0
    options = calls[0]
    assert options["server_header"] is False
    assert options["proxy_headers"] is False
    assert options["access_log"] is False
    assert options["ws"] == "none"
    assert options["workers"] == 1
    assert options["limit_concurrency"] == 128
    assert options["timeout_keep_alive"] == 5
    assert options["ssl_certfile"] is None


def test_uvicorn_options_are_one_shared_function_so_tests_run_the_shipped_config() -> None:
    options = uvicorn_options(
        host="127.0.0.1", port=0, tls_cert=None, tls_key=None, max_connections=7
    )
    assert options["limit_concurrency"] == 7
    assert options["server_header"] is False


def test_tuning_flags_reach_the_app_config(dist_root, monkeypatch) -> None:
    calls = _mock_uvicorn_run(monkeypatch)
    main(
        [
            "serve",
            "--dist",
            str(dist_root),
            "--max-connections",
            "9",
            "--max-request-body-bytes",
            "2048",
            "--max-response-bytes",
            "4096",
            "--upstream-timeout",
            "7.5",
            "--max-upstream-inflight",
            "3",
            "--rate-limit-per-second",
            "2.5",
            "--rate-limit-burst",
            "11",
            "--trusted-proxy-hops",
            "2",
        ]
    )
    config = calls[0]["app"].config
    assert calls[0]["limit_concurrency"] == 9
    assert config.max_request_body_bytes == 2048
    assert config.max_response_bytes == 4096
    assert config.upstream_timeout_seconds == 7.5
    assert config.max_upstream_inflight == 3
    assert config.rate_limit_per_second == 2.5
    assert config.rate_limit_burst == 11
    assert config.trusted_proxy_hops == 2


def test_rate_limiting_is_on_by_default_and_trusts_no_proxy(dist_root, monkeypatch) -> None:
    calls = _mock_uvicorn_run(monkeypatch)
    main(["serve", "--dist", str(dist_root)])
    app = calls[0]["app"]
    assert app.limiter is not None
    assert app.config.trusted_proxy_hops == 0


@pytest.mark.parametrize(
    "bad",
    [
        ["--max-connections", "0"],
        ["--trusted-proxy-hops", "99"],
        ["--rate-limit-per-second", "-1"],
        ["--rate-limit-burst", "0"],
        ["--upstream-timeout", "0"],
        ["--max-request-body-bytes", "0"],
        ["--jobs-url", "http://user:pw@127.0.0.1:1"],
        ["--dashboard-url", "ftp://127.0.0.1:1"],
    ],
)
def test_nonsense_tuning_values_are_rejected_at_startup(dist_root, monkeypatch, bad) -> None:
    _mock_uvicorn_run(monkeypatch)
    with pytest.raises(SystemExit):
        main(["serve", "--dist", str(dist_root), *bad])
