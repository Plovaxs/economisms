"""The gateway under REAL TLS: a throwaway certificate, a real uvicorn built
from the production options, and a real TLS client -- so what `--tls-cert` /
`--tls-key` actually negotiate, and what the application then sends over that
channel (HSTS and `upgrade-insecure-requests` exist ONLY here), is observed
rather than assumed. The entry-point tests elsewhere only prove the flags are
accepted; none of them ever completed a handshake."""

from __future__ import annotations

import datetime
import http.client
import ipaddress
import socket
import ssl
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest
import uvicorn
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from prometheus.httpsec.server import uvicorn_options
from prometheus.webgateway.app import GatewayConfig, WebGatewayService


@dataclass
class Tls:
    port: int
    cert: Path
    config: uvicorn.Config


def _self_signed(directory: Path) -> tuple[Path, Path]:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    cert_path, key_path = directory / "cert.pem", directory / "key.pem"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return cert_path, key_path


@pytest.fixture(scope="module")
def tls(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Tls]:
    root = tmp_path_factory.mktemp("tls")
    cert, key = _self_signed(root)
    dist = root / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>shell</title>")
    app = WebGatewayService(
        dist,
        "http://127.0.0.1:1",
        "http://127.0.0.1:1",
        config=GatewayConfig(rate_limit_per_second=0),
    )
    options = uvicorn_options(
        host="127.0.0.1", port=0, tls_cert=cert, tls_key=key, max_connections=16
    )
    config = uvicorn.Config(app, log_level="warning", **options)
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "TLS gateway failed to start"
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield Tls(port, cert, config)
    server.should_exit = True
    thread.join(15)


def _client(tls: Tls, **context_kwargs) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=str(tls.cert))
    for name, value in context_kwargs.items():
        setattr(context, name, value)
    return context


def _get(tls: Tls, path: str, context: ssl.SSLContext) -> tuple[int, dict[str, str], str]:
    connection = http.client.HTTPSConnection("127.0.0.1", tls.port, context=context, timeout=8)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        version = connection.sock.version() if connection.sock else ""
        return response.status, {k.lower(): v for k, v in response.getheaders()}, version or ""
    finally:
        connection.close()


def test_a_real_handshake_completes_and_the_app_answers_over_it(tls) -> None:
    status, headers, version = _get(tls, "/health/live", _client(tls))
    assert status == 200
    assert version in ("TLSv1.2", "TLSv1.3")
    assert headers["x-content-type-options"] == "nosniff"


def test_hsts_and_upgrade_insecure_requests_appear_only_over_https(tls) -> None:
    status, headers, _ = _get(tls, "/", _client(tls))
    assert status == 200
    assert "max-age=63072000" in headers["strict-transport-security"]
    assert headers["content-security-policy"].endswith("; upgrade-insecure-requests")


def test_tls_1_3_is_negotiated_by_a_modern_client(tls) -> None:
    context = _client(tls, minimum_version=ssl.TLSVersion.TLSv1_3)
    assert _get(tls, "/health/live", context)[2] == "TLSv1.3"


def test_tls_1_2_is_still_accepted(tls) -> None:
    context = _client(tls, maximum_version=ssl.TLSVersion.TLSv1_2)
    assert _get(tls, "/health/live", context)[2] == "TLSv1.2"


def test_the_server_context_refuses_anything_below_tls_1_2(tls) -> None:
    """Checked on the context uvicorn actually builds from the shipped options: a
    TLS 1.0/1.1 CLIENT cannot be used for this (modern OpenSSL builds refuse to
    speak those at all, so a failed handshake would prove nothing about the
    server)."""
    assert tls.config.ssl is not None  # built by the running server from the shipped options
    assert tls.config.ssl.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_a_client_that_does_not_trust_the_certificate_is_refused(tls) -> None:
    with pytest.raises(ssl.SSLCertVerificationError):
        _get(tls, "/health/live", ssl.create_default_context())


def test_cleartext_http_on_the_tls_port_is_not_answered_as_http(tls) -> None:
    with socket.create_connection(("127.0.0.1", tls.port), timeout=5) as sock:
        sock.sendall(b"GET /health/live HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n")
        sock.settimeout(5)
        try:
            data = sock.recv(4096)
        except (ConnectionResetError, TimeoutError):
            data = b""
    assert not data.startswith(b"HTTP/1.1 200"), data[:60]
    assert b"live" not in data


def test_the_server_never_offers_the_deprecated_protocol_versions(tls) -> None:
    assert tls.config.ssl is not None
    assert not (tls.config.ssl.options & ssl.OP_NO_TLSv1_2)
