"""Trusted-operator CLI for durable local research jobs.

Owner filters isolate lookups; this local CLI relies on OS permissions and
is not an authenticated HTTP service. It exposes no trading/payment actions.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from prometheus.evidence.contracts import read_evidence_bundle
from prometheus.evidence.export import export_evidence_bundle
from prometheus.evidence.jsonio import strict_json_loads
from prometheus.jobs.artifacts import ArtifactStore
from prometheus.jobs.store import Job, JobStore
from prometheus.jobs.worker import Worker
from prometheus.orchestration.recipes import RUNNERS, default_recipe


def job_response(job: Job) -> dict[str, Any]:
    return {
        "job_id": job.job_id,
        "trace_id": job.trace_id,
        "kind": job.kind,
        "status": job.status,
        "created_at": datetime.fromtimestamp(job.created_ns / 1e9, UTC).isoformat(),
        "updated_at": datetime.fromtimestamp(job.updated_ns / 1e9, UTC).isoformat(),
        "recipe_sha256": job.recipe_sha256,
        "attempts": job.attempts,
        "cancel_requested": job.cancel_requested,
        "timeout_seconds": job.timeout_seconds,
        "resource_estimate": strict_json_loads(job.estimate_json),
        "artifact_sha256": job.artifact_sha256,
        "result_hash": job.result_hash,
        "error_code": job.error_code,
        "diagnostic_id": job.diagnostic_id,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    commands = parser.add_subparsers(dest="action", required=True)
    submit = commands.add_parser("submit")
    submit.add_argument("--kind", required=True, choices=sorted(RUNNERS))
    submit.add_argument("--recipe", type=Path)
    submit.add_argument("--owner", required=True)
    submit.add_argument("--idempotency-key")
    submit.add_argument("--timeout", type=float)
    for name in ("show", "cancel", "artifact"):
        command = commands.add_parser(name)
        command.add_argument("job_id")
        command.add_argument("--owner", required=True)
        if name == "artifact":
            command.add_argument("--output", required=True, type=Path)
    listing = commands.add_parser("list")
    listing.add_argument("--owner", required=True)
    listing.add_argument("--limit", type=int, default=50)
    listing.add_argument("--cursor")
    work = commands.add_parser("work")
    work.add_argument("--once", action="store_true")
    work.add_argument("--worker-id", default=f"worker-{uuid.uuid4().hex}")
    audit = commands.add_parser("audit")
    audit.add_argument("--expected-head-sha256")
    args = parser.parse_args(argv)
    try:
        store = JobStore(args.root / "jobs.sqlite3")
        artifacts = ArtifactStore(
            args.root / "artifacts",
            max_bytes=store.policy.max_artifact_bytes,
            max_total_bytes=store.policy.max_store_bytes,
        )
        if args.action == "submit":
            raw = (
                default_recipe(args.kind)
                if args.recipe is None
                else read_evidence_bundle(args.recipe)
            )
            report = job_response(
                store.submit(
                    args.kind,
                    raw,
                    owner=args.owner,
                    idempotency_key=args.idempotency_key,
                    timeout_seconds=args.timeout,
                )
            )
        elif args.action == "show":
            report = job_response(store.get(args.job_id, owner=args.owner))
        elif args.action == "cancel":
            report = job_response(store.cancel(args.job_id, owner=args.owner))
        elif args.action == "list":
            jobs, cursor = store.list_jobs(owner=args.owner, limit=args.limit, cursor=args.cursor)
            report = {"jobs": [job_response(job) for job in jobs], "next_cursor": cursor}
        elif args.action == "artifact":
            job = store.get(args.job_id, owner=args.owner)
            if job.artifact_sha256 is None:
                raise ValueError("job has no published artifact")
            bundle = artifacts.get(job.artifact_sha256)
            if bundle.get("job_context", {}).get("job_id") != job.job_id:
                raise ValueError("artifact is not associated with this job")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            export_evidence_bundle(bundle, args.output)
            report = {"artifact_sha256": job.artifact_sha256, "output": str(args.output)}
        elif args.action == "audit":
            report = {
                "valid": True,
                "audit_head_sha256": store.verify_audit_chain(
                    expected_head=args.expected_head_sha256
                ),
            }
        else:
            worker = Worker(store, artifacts, worker_id=args.worker_id)
            while True:
                processed = worker.run_once()
                if args.once:
                    report = {
                        "processed": processed is not None,
                        "job": job_response(processed) if processed else None,
                    }
                    break
                if processed is None:
                    time.sleep(0.5)
    except KeyboardInterrupt:
        return 130
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
