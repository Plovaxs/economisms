"""Fixed child-process entry point for allowlisted research recipes only."""

from __future__ import annotations

import argparse
import math
import os
import signal
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--timeout", required=True, type=float)
    parser.add_argument("--max-file-bytes", required=True, type=int)
    parser.add_argument("--parent-pid", required=True, type=int)
    args = parser.parse_args(argv)
    if sys.platform != "linux":
        parser.error("the isolated research worker requires Linux process controls")
    if not math.isfinite(args.timeout) or args.timeout <= 0 or args.max_file_bytes < 1:
        parser.error("invalid process resource budgets")
    import ctypes
    import resource

    # Set after exec, then close the race where the parent died before prctl.
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int] + [ctypes.c_ulong] * 4
    libc.prctl.restype = ctypes.c_int
    if libc.prctl(1, signal.SIGKILL, 0, 0, 0) != 0 or os.getppid() != args.parent_pid:
        return 1
    for event in (signal.SIGALRM, signal.SIGXCPU, signal.SIGTERM):
        signal.signal(event, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, args.timeout)
    cpu = max(1, math.ceil(args.timeout))
    resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (args.max_file_bytes, args.max_file_bytes))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    error_path = args.output.with_suffix(".error.json")
    try:
        from prometheus.evidence.contracts import read_evidence_bundle
        from prometheus.evidence.export import export_evidence_bundle
        from prometheus.orchestration.recipes import ResourceLimits, execute_recipe

        request = read_evidence_bundle(args.input)
        limits = ResourceLimits(**request["limits"])
        result = execute_recipe(request["kind"], request["config"], limits=limits)
        result.evidence_bundle["job_context"] = request["job_context"]
        export_evidence_bundle(result.evidence_bundle, args.output)
        return 0
    except Exception as exc:
        import json

        code = (
            "infrastructure_error"
            if isinstance(exc, OSError)
            else "model_error"
            if isinstance(exc, (ValueError, ArithmeticError, RuntimeError))
            else "worker_failed"
        )
        error_path.write_text(json.dumps({"error_code": code}), encoding="utf-8")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
