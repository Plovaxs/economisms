# PR-046 local validation — 2026-11-03

Scope: bounded recipe admission, durable single-host job state, isolated Linux
execution, fenced publication and local artifact/audit storage. All work is
local and uncommitted. This is not completion of the 374-item blueprint or
production approval. R0 remains **NO-GO**.

| Check | Observed result |
|-------|-----------------|
| `.venv/bin/ruff check src tests` | Passed |
| `.venv/bin/mypy --strict src` | Passed; 92 source files |
| Complete pytest suite with coverage | 1,226 passed in 33.99 seconds; 95% parent-process line coverage |
| Formatting of 12 new backend/registry/test files | Passed |
| `git diff --check` | Passed |
| Registry checks after final checklist edits | 4 passed; all 374 IDs retained |
| Two simultaneous fresh-process benchmark executions | Both succeeded; one attempt each; exact same computational result |
| Repeated submission with the same idempotency key | Returned the original job UUID |
| Parent Torch RNG before/after worker execution | Unchanged |
| Strict sealed numerical replay | Exact result; no observed runtime changes |
| Offline content-pinned artifact audit | Passed |
| Queue audit against locally recorded head | Passed; job/event projection consistent |
| Full-scope inventory | 29 categories; 100 IDs with unreviewed notes, 274 without; zero accepted items |

The coverage run does not collect execution inside spawned child interpreters:
`jobs/child.py` is reported at 0% despite real process integration tests.
Coverage is not a measure of scientific correctness or production readiness.
Remote CI, Python-version matrix execution, load testing, power-loss testing
and independent review have not been performed here.

## Recorded reference

The complete sealed local receipt is [job_execution_pr046.json](./job_execution_pr046.json).
It retains the full recipe, both job/trace IDs, resource estimates, outcomes,
artifact audits, observed environment and local audit checkpoint. The queue
database lives in a temporary local directory identified in that receipt;
it is not a durable repository deliverable and may be removed by host cleanup.
The exported reference and replay remain self-contained in the repository.

Python 3.14.7, NumPy 2.5.4, SciPy 1.18.1, PyTorch 2.15.0+cpu and SQLite
3.53.4 were observed. Both workers, the exported reference and replay used
this observed package source digest:

```text
131bc8c869f6e69814728815c05eba0ee22048cb6938f78805362bfe9c848688
```

Both independent fits produced computational result:

```text
2937b8194e9c7a5b62d925c332aa8b377bd7a4b3753f6f16897ce606f874e022
```

The exported [job_reference.json](./job_reference.json) has content pin:

```text
a5d7fd39c53e2563eaaac54bdb7ca36530c38bedfc1b6844dd1afdfe849608a1
```

The second job has a different complete-artifact pin because its job/trace
context and run metadata differ. A new execution should preserve the
computational result under the same environment but acquire new complete
artifact/run identities. These pins were observed locally and do not
authenticate authorship or establish an independently trusted checkpoint.

## Reproduction

```bash
.venv/bin/python -m prometheus.evidence.verify evidence/job_reference.json \
  --expected-content-sha256 a5d7fd39c53e2563eaaac54bdb7ca36530c38bedfc1b6844dd1afdfe849608a1
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/job_reference.json --require-integrity \
  --output /tmp/prometheus-pr046-replay.json
.venv/bin/python -m prometheus.evidence.verify evidence/job_execution_pr046.json
.venv/bin/python -m pytest -q --cov=prometheus --cov-report=term-missing
```

[job_replay.json](./job_replay.json) retains the actual recomputed bundle
and comparison. [job_artifact_audit_pr046.json](./job_artifact_audit_pr046.json)
is raw auditor CLI output, not a sealed evidence bundle. The current sealed
[gate_report_r0.json](./gate_report_r0.json) has been regenerated from code.
The reference is deliberately small and synthetic; benchmark execution
success does not assert that its learned policy beats the baseline.

For new queue executions and full operational details, see
[LOCAL_JOBS.md](../docs/LOCAL_JOBS.md). Its CLI examples use a separate local
state directory. The reference recipe is available at
`job_execution_pr046.json` → `job_validation.recipe`; pass that complete
flat object to `submit --recipe`, rather than passing the enclosing receipt.

## Exercised failures and limits

The suite exercises sixteen concurrent idempotent submissions, quotas,
exclusive claims, stale-token rejection, retries/attempt exhaustion,
cancelled queued/running jobs, actual wall timeout, actual Linux parent
death with reaping, environment mismatch before launch, wrong-job artifact
rejection, failed simulation evidence retention, ignored-parent alarm
disposition, safe staging cleanup, corrupt/no-clobber artifacts, symlinks,
byte caps and event/state tampering. Existing replay and numerical tests
remain part of the full suite.

Recipe estimates bound admitted work; they do not enforce hard RAM limits
or predict runtime. The CLI trusts the OS operator: owner filters are not
authentication. SQLite/locks and Linux process controls are single-host
facilities. Checksums and append-only SQL triggers do not prevent a
privileged administrator rewriting data. A valid unreferenced object may
remain after publication followed by database failure.

Authenticated HTTP/OpenAPI, hard RSS/cgroup isolation, distributed workers,
per-period compute credits, reproducible locked builds, retention/garbage
collection, backup/restore, failover/SLO validation, signed provenance and
independent reviews remain outstanding. Full requirement scope remains in
[the implementation plan](../docs/IMPLEMENTATION_PLAN.md) and its generated
register; no acceptance or reviewer has been invented.
