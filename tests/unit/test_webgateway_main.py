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

from prometheus.webgateway.__main__ import main


@pytest.fixture
def dist_root(tmp_path):
    root = tmp_path / "dist"
    root.mkdir()
    (root / "index.html").write_text("<html>spa shell</html>")
    return root


def _mock_uvicorn_run(monkeypatch):
    calls = []
    monkeypatch.setattr("uvicorn.run", lambda app, **kwargs: calls.append(kwargs))
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
