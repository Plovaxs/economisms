"""A real gateway process, a real SIGTERM. `docker stop`, systemd and every
orchestrator ask a service to stop with SIGTERM and then wait: a gateway that
dies on the spot turns each deploy into a burst of failed requests. This runs
the shipped entry point as a subprocess, parks a request inside a slow backend,
terminates the process, and checks the request still completes, the process
exits cleanly well inside its grace period, and nothing new is accepted afterwards."""

from __future__ import annotations

import http.client
import http.server
import signal
import socket
import subprocess
import sys
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals")


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class _Slow(http.server.BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        if self.path == "/slow":
            time.sleep(1.5)
        body = b'{"ok": true}'
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args: object) -> None:
        pass


def _get(port: int, path: str, timeout: float = 10.0) -> tuple[int, bytes]:
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        return response.status, response.read()
    finally:
        connection.close()


def test_sigterm_drains_the_in_flight_request_then_exits_cleanly(tmp_path) -> None:
    backend = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Slow)
    threading.Thread(target=backend.serve_forever, daemon=True).start()
    backend_url = f"http://127.0.0.1:{backend.server_port}"
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<title>x</title>")
    port = _free_port()
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "prometheus.webgateway",
            "serve",
            "--dist",
            str(dist),
            "--jobs-url",
            backend_url,
            "--dashboard-url",
            backend_url,
            "--port",
            str(port),
            "--rate-limit-per-second",
            "0",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        deadline = time.monotonic() + 30
        while True:
            try:
                if _get(port, "/health/live", timeout=1.0)[0] == 200:
                    break
            except OSError:
                pass
            assert process.poll() is None, "the gateway exited during startup"
            assert time.monotonic() < deadline, "the gateway never came up"
            time.sleep(0.1)

        result: dict[str, object] = {}

        def slow_call() -> None:
            try:
                result["reply"] = _get(port, "/api/jobs/slow", timeout=15.0)
            except Exception as exc:  # recorded so the assertion below can show it
                result["error"] = repr(exc)

        caller = threading.Thread(target=slow_call)
        caller.start()
        time.sleep(0.5)  # the request is now parked inside the slow backend
        started = time.monotonic()
        process.send_signal(signal.SIGTERM)
        caller.join(15)
        assert "error" not in result, result
        assert result["reply"] == (200, b'{"ok": true}'), "the in-flight request must complete"
        # uvicorn re-raises the captured signal once the drain is complete (so a supervisor
        # sees the conventional "terminated by SIGTERM" status); a hard crash or a hang would
        # be any other code, or no exit at all.
        status = process.wait(timeout=20)
        assert status in (0, -signal.SIGTERM), f"unexpected exit status {status}"
        assert time.monotonic() - started < 12, "shutdown must not sit out its whole grace period"
        with pytest.raises(OSError):
            socket.create_connection(("127.0.0.1", port), timeout=1).close()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(10)
        backend.shutdown()
        backend.server_close()
