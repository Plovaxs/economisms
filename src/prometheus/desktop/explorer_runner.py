"""Run an explorer's computation in a child process, with a time limit and a way to cancel it.

`run_explorer` is the blocking call (what tests and scripts use). `ExplorerTask` is the same call
on a background thread, for a window that must not freeze: start it, poll `done`, read `payload`
or `error`, or `cancel()` it. Cancelling kills the child's whole process group, so nothing it
started can linger.
"""

from __future__ import annotations

import contextlib
import json
import os
import signal
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from typing import Any

from prometheus.desktop.compute_child import MAX_OUTPUT_BYTES
from prometheus.evidence.jsonio import strict_json_loads
from prometheus.jobs.worker import _child_environment

DEFAULT_TIMEOUT_SECONDS = 60.0
_POLL_SECONDS = 0.05


class ExplorerError(RuntimeError):
    """The computation failed, timed out, or was cancelled; the message is fit to show."""


def _kill(process: subprocess.Popen[bytes]) -> None:
    with contextlib.suppress(ProcessLookupError):  # it may have just finished on its own
        os.killpg(process.pid, signal.SIGKILL)
    process.communicate()  # reap it, and close the pipes


def run_explorer(
    name: str,
    params: Mapping[str, Any],
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    cancel: threading.Event | None = None,
) -> dict[str, Any]:
    """Compute explorer `name` for `params` and return its payload.

    Raises `ExplorerError` on a failure the child reported, on timeout, and on cancellation.
    """
    request = json.dumps(
        {"explorer": name, "params": dict(params), "timeout": timeout}, allow_nan=False
    ).encode()
    # S603: argv is [sys.executable, -m, a fixed module]; the request travels on stdin, never in
    # argv, and the environment is the scrubbed one the job worker uses.
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "prometheus.desktop.compute_child"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
        env=_child_environment(),
    )
    deadline = time.monotonic() + timeout
    pending: bytes | None = request
    while True:
        if cancel is not None and cancel.is_set():
            _kill(process)
            raise ExplorerError("cancelled")
        if time.monotonic() >= deadline:
            _kill(process)
            raise ExplorerError(f"timed out after {timeout:g} seconds")
        try:
            output, _ = process.communicate(pending, timeout=_POLL_SECONDS)
            break
        except subprocess.TimeoutExpired:
            pending = None
    return _read_reply(output, process.returncode)


def _how_it_ended(status: int) -> str:
    """`-24` is not a message a person can act on; the signal's name is."""
    if status < 0:
        try:
            return f"was stopped by the system ({signal.Signals(-status).name})"
        except ValueError:
            return f"was stopped by the system (signal {-status})"
    return f"stopped unexpectedly (exit status {status})"


def _read_reply(output: bytes, status: int) -> dict[str, Any]:
    if len(output) > MAX_OUTPUT_BYTES + 1024:
        raise ExplorerError("the result is too large to show")
    try:
        reply = strict_json_loads(output.decode("utf-8"))
    except (ValueError, UnicodeError):
        raise ExplorerError(f"the calculation {_how_it_ended(status)}") from None
    if not isinstance(reply, dict) or not isinstance(reply.get("ok"), bool):
        raise ExplorerError("the calculation returned something unreadable")
    if not reply["ok"]:
        raise ExplorerError(str(reply.get("error", "the calculation failed")))
    payload = reply.get("payload")
    if not isinstance(payload, dict):
        raise ExplorerError("the calculation returned something unreadable")
    return payload


class ExplorerTask:
    """`run_explorer` on a background thread."""

    def __init__(
        self, name: str, params: Mapping[str, Any], *, timeout: float = DEFAULT_TIMEOUT_SECONDS
    ) -> None:
        self.name = name
        self._params = dict(params)
        self._timeout = timeout
        self._cancel = threading.Event()
        self._thread = threading.Thread(target=self._run, name=f"explorer-{name}", daemon=True)
        self._started = 0.0
        self._finished = threading.Event()
        self.payload: dict[str, Any] | None = None
        self.error: str | None = None

    def start(self) -> None:
        self._started = time.monotonic()
        self._thread.start()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def done(self) -> bool:
        return self._finished.is_set()

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self._started if self._started else 0.0

    def wait(self, timeout: float | None = None) -> bool:
        return self._finished.wait(timeout)

    def _run(self) -> None:
        try:
            self.payload = run_explorer(
                self.name, self._params, timeout=self._timeout, cancel=self._cancel
            )
        except ExplorerError as exc:
            self.error = str(exc)
        except Exception as exc:  # the thread must always finish, or the window waits forever
            self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self._finished.set()
