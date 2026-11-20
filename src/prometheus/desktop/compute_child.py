"""Fixed child-process entry point for the explorers' computations.

The window never computes anything itself. For an explorer it starts this module in a fresh
process, hands it one JSON object on stdin, and reads one JSON object from stdout:

    in :  {"explorer": "<name>", "params": {...}, "timeout": <seconds>}
    out:  {"ok": true, "payload": {...}}   or   {"ok": false, "error": "<one line>"}

The child trusts nothing in the request: the explorer must be a registered one, and every
parameter is parsed and range-checked again by `explorers.validate` (the same call the window
makes), so a caller that skipped validation -- a bug, a tampered request -- still cannot ask for a
50-gigabyte array. It dies with its parent (the kernel is told to SIGKILL it when the window
goes), has a CPU limit and no core dumps, and reports every failure as one short line rather than
a traceback, because a traceback is for the developer and the window shows this text to a person.
"""

from __future__ import annotations

import json
import math
import sys

MAX_INPUT_BYTES = 65_536
MAX_OUTPUT_BYTES = 16 * 1024 * 1024
MAX_TIMEOUT_SECONDS = 600.0
CPU_BACKSTOP_FLOOR_SECONDS = 30
CPU_BACKSTOP_FACTOR = 8


def _fail(message: str) -> int:
    sys.stdout.write(json.dumps({"ok": False, "error": message[:300]}) + "\n")
    return 2


def _limit_resources(timeout: float) -> None:
    if sys.platform != "linux":
        return
    import ctypes
    import resource
    import signal

    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int] + [ctypes.c_ulong] * 4
    libc.prctl.restype = ctypes.c_int
    libc.prctl(1, signal.SIGKILL, 0, 0, 0)  # PR_SET_PDEATHSIG: die with the window
    # A backstop, not the time limit: the caller enforces the wall clock. CPU time is summed over
    # threads, so a limit equal to the wall limit would kill a many-core calculation within a
    # fraction of it (a 0.2 s limit became 1 CPU-second, which 20 BLAS threads spend in 50 ms).
    cpu = max(CPU_BACKSTOP_FLOOR_SECONDS, math.ceil(timeout) * CPU_BACKSTOP_FACTOR)
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


def main() -> int:
    raw = sys.stdin.buffer.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        return _fail("the request is too large")
    from prometheus.evidence.jsonio import strict_json_loads

    try:
        request = strict_json_loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        return _fail("the request is not valid JSON")
    if not isinstance(request, dict) or set(request) - {"explorer", "params", "timeout"}:
        return _fail("the request has the wrong shape")
    name, params, timeout = request.get("explorer"), request.get("params"), request.get("timeout")
    if not isinstance(params, dict) or not isinstance(name, str):
        return _fail("the request has the wrong shape")
    if (
        isinstance(timeout, bool)
        or not isinstance(timeout, (int, float))
        or not 0 < timeout <= MAX_TIMEOUT_SECONDS
    ):
        return _fail("the time limit is missing or out of range")
    _limit_resources(float(timeout))

    from prometheus.desktop import explorers
    from prometheus.experiments.manifest import json_default

    try:
        known = {spec.name for spec in explorers.EXPLORERS}
        if name not in known:
            return _fail(f"unknown explorer {name!r}")
        fields = {spec.key for spec in explorers.explorer(name).fields}
        if set(params) != fields:
            return _fail("the parameters do not match the explorer's fields")
        checked, errors = explorers.validate(name, {(key,): value for key, value in params.items()})
        if errors:
            where, message = next(iter(errors.items()))
            return _fail(f"{'.'.join(where) or 'parameters'} {message}")
        payload = explorers.compute(name, checked)
        text = json.dumps({"ok": True, "payload": payload}, default=json_default, allow_nan=False)
    except Exception as exc:  # one line for the person; the type is enough for the developer
        return _fail(f"{type(exc).__name__}: {exc}")
    if len(text) > MAX_OUTPUT_BYTES:
        return _fail("the result is too large to show")
    sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
