# PR-047 local validation — 2026-11-03

Scope: versioned authenticated research-job ASGI API, private hashed service
credentials, owner-derived read/write scopes, bounded HTTP admission,
OpenAPI contract and typed synchronous SDK. The worker backend remains
single-host Linux. Work is local/uncommitted; the full blueprint and
industrial production acceptance remain unfinished. R0 remains **NO-GO**.

| Check | Observed result |
|-------|-----------------|
| `.venv/bin/ruff check src tests` | Passed |
| `.venv/bin/mypy --strict src` | Passed; 98 source files |
| Full pytest with coverage, final run | 1,298 passed in 40.47 seconds; 94% line coverage; no warnings |
| New service/test formatting | Nine files passed |
| `git diff --check` | Passed |
| Tracked OpenAPI vs generated contract | Exact equality; all nine complete default recipes validate |
| Real TCP ASGI server + typed SDK + separate worker | Submit/status/artifact/cancel/pages succeeded |
| Idempotent HTTP retry | Original job ID returned |
| Strict numerical replay | Exact result; no runtime changes |
| Parent Torch RNG across worker execution | Unchanged |
| Wrong-owner / read-only write / revoked credential | 404 / 403 / 401 observed through real SDK |
| Pending artifact / conflicting key | Distinct structured 409 errors observed |
| Request/job/trace/diagnostic correlation | 19 captured request events; errors correlate to diagnostic IDs |
| Token and raw recipe in captured request logs | Absent |
| Offline audit of all five new/current sealed API/gate bundles | Passed; runtime matches observed source/dependencies |
| Full requirement register | 374 items, 29 categories; 108 IDs with notes; zero independently accepted |

The first full run passed with a ResourceWarning from a test SQLite
connection. The test now explicitly closes it; the complete final run above
is clean. No production-source change was needed for that test warning.
Coverage does not collect spawned interpreter execution (`jobs/child.py`
still appears at 0% despite actual subprocess integration tests), and does
not establish scientific correctness or security acceptance.

## Recorded environment and contract

Observed Python 3.14.7, NumPy 2.5.4, SciPy 1.18.1, PyTorch 2.15.0+cpu,
Uvicorn 0.54.0 and jsonschema 4.26.0. Reference/replay/receipt/log/gate
bundles share package source digest:

```text
635fb2536e6d0699c136bfed4c79bd6bb8dbf5156cbb1b5e5dcc037b3c407568
```

The byte SHA-256 of [openapi-v1.json](../docs/api/openapi-v1.json), API
version 1.0.0 / OpenAPI 3.1.1, is:

```text
46605e47703aaef59715f456cafc539871c5f28e8851d8e3e7dce2101879ac2b
```

The core runtime record observes numerical dependencies, not every service
dependency or a build lock. The service dependency versions above are
additionally retained in the API receipt. No reproducible dependency/build
lock or supply-chain attestation is claimed by this slice. CI installation
now includes `[dev,service]`; no remote CI execution is claimed.

## Reference execution and retained artifacts

[api_execution_pr047.json](./api_execution_pr047.json) retains the full
synthetic benchmark recipe, completed/cancelled job snapshots, resource
estimate, artifact audit, idempotent retry identity, observed service
versions, correlated rejection IDs, replay result and local queue audit head.
The test used a pre-bound loopback socket inherited by a real Uvicorn
process, with the actual application and SDK. The server was terminated and
reaped after validation; the saved loopback origin is historical, not a
running or published endpoint. Credentials and the SQLite database remain
only in the temporary private local directory named in the receipt and may
be removed by host cleanup; they are not repository deliverables.

[api_reference.json](./api_reference.json) is the artifact actually fetched
through the SDK after worker completion. Its content pin is:

```text
139b568a741fd6cbb6a1e1be0527dc15b083467d59a5adca7e97ec2ef6549c2b
```

Its computational result is identical to PR-046's same-recipe local fits:

```text
2937b8194e9c7a5b62d925c332aa8b377bd7a4b3753f6f16897ce606f874e022
```

[api_replay.json](./api_replay.json) retains the actual rerun and comparison;
[api_request_log_pr047.json](./api_request_log_pr047.json) seals the 19
captured structured request events, including request/job/trace/diagnostic
links. [api_artifact_audit_pr047.json](./api_artifact_audit_pr047.json) is
raw auditor CLI output, not a sealed evidence bundle. The current
[gate_report_r0.json](./gate_report_r0.json) is regenerated from code.

Pins and the queue audit checkpoint were observed locally. Their agreement
does not authenticate authorship or establish independent review/trust.
The benchmark is deliberately small and synthetic; successful execution
does not assert that its learned policy beats delta or is fit for deployment.

## Reproduction

```bash
.venv/bin/python -m prometheus.evidence.verify evidence/api_reference.json \
  --expected-content-sha256 139b568a741fd6cbb6a1e1be0527dc15b083467d59a5adca7e97ec2ef6549c2b
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/api_reference.json --require-integrity \
  --output /tmp/prometheus-pr047-replay.json
.venv/bin/python -m prometheus.evidence.verify evidence/api_execution_pr047.json
.venv/bin/python -m prometheus.evidence.verify evidence/api_request_log_pr047.json
.venv/bin/python -m pytest -q --cov=prometheus --cov-report=term-missing
```

For fresh service/worker execution use [RESEARCH_API.md](../docs/RESEARCH_API.md).
The actual reference recipe is `api_execution_pr047.json` →
`api_validation.recipe`. Use a new private state directory and real generated
credentials; old reference IDs/origins are not reusable live credentials.
The tracked receipt contains no plaintext tokens.

## Failure coverage and remaining requirements

Tests reject anonymous access, foreign-owner reads/cancellation/artifacts,
read-only writes, owner injection, malformed/missing credentials, duplicate
digests, unsafe modes/symlinks/FIFOs, live revocation, spoofed forwarding,
nonlocal cleartext, unsafe SDK origins, redirects and environment proxies.
Wire tests reject duplicate JSON keys, non-finite/overflowing values, invalid
dates/currencies/precision/fields/work, ambiguous framing, unsupported media,
oversized headers/body and slow/disconnected reads before queue mutation.

Backpressure tests distinguish process-local owner/global request rate,
in-flight capacity and durable pending-job quotas. A cancelled HTTP caller
cannot prematurely release capacity while its thread still runs. Readiness
tests exercise missing database, writer contention, policy drift and missing
credentials while preserving liveness. Error tests verify correlation and
absence of exception/token/recipe text. Real TCP tests and retained reference
exercise the SDK/server/backend/worker/artifact path. Existing worker timeout,
parent-death, cancellation, lease recovery and artifact integrity tests remain
in the complete suite.

SSO/OIDC/MFA, vault-backed secrets, externally verified TLS and at-rest
encryption, durable external logs/checkpoints, worker/disk readiness,
distributed rate/compute limits, hard RSS/cgroups, reproducible locked builds,
retention/backup/restore, failover, load/SLO validation, market-data/report
APIs and independent acceptance remain open. SDK socket-operation timeouts
are not absolute response wall deadlines. The full inventory preserves all
374 acceptance targets; implementation notes are not completed criteria.
