"""The thread that works through the queue while the window stays responsive.

`Worker.run_once` blocks for the whole life of a job (it polls the child process), so it cannot run
on the window's own thread. This is that thread, and nothing else: it holds no state about what is
running -- the window asks the `LocalSession` -- and it never runs model code itself, because
`run_once` hands each job to a child process.

Two behaviours matter more than they look:

- an exception inside one `run_once` must not kill the thread, or the window would show a queue
  that never moves; it is recorded in `last_error` for the window to display, and the loop goes on;
- `stop()` cancels the running job first. Otherwise closing the window would wait out a job that
  can take half an hour, or leave one running with nobody watching.
"""

from __future__ import annotations

import contextlib
import threading

from prometheus.desktop.session import JobsUnavailableError, LocalSession


class WorkerLoop:
    def __init__(self, session: LocalSession, *, idle_seconds: float = 0.25) -> None:
        self._session = session
        self._idle = idle_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.last_error: str | None = None
        self.processed = 0

    @property
    def alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.alive:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="econosim-worker", daemon=True)
        self._thread.start()

    def stop(self, *, timeout: float = 15.0, cancel_running: bool = True) -> bool:
        """Ask the loop to end; True if it has. A running job is cancelled first (see above)."""
        self._stop.set()
        if cancel_running:
            self._cancel_running()
        thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def _cancel_running(self) -> None:
        with contextlib.suppress(Exception):  # closing must not fail because the store is busy
            for summary in self._session.summaries():
                if summary.status == "running":
                    self._session.cancel(summary.job_id)

    def _run(self) -> None:
        while not self._stop.is_set():
            if not self._step():
                self._stop.wait(self._idle)

    def _step(self) -> bool:
        try:
            job = self._session.work_once()
        except JobsUnavailableError as exc:
            self.last_error = str(exc)
            self._stop.set()  # nothing will ever change on this platform
            return False
        except Exception as exc:  # the thread must outlive any one job's failure
            self.last_error = f"{type(exc).__name__}: {exc}"
            return False
        if job is None:
            return False
        self.processed += 1
        return True
