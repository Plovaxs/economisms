# Local research jobs

PR-046 supplies a trusted-operator Linux backend for the nine existing
research runners. It adds no HTTP listener, authentication authority,
broker connection, arbitrary-code runner or payment/order action. The full
blueprint remains in [the implementation plan](./IMPLEMENTATION_PLAN.md).
PR-047 now supplies a separate [authenticated HTTP boundary](./RESEARCH_API.md)
on top of this backend. The CLI continues to trust its OS operator.

## Submit, inspect and execute

Use a dedicated private local state directory:

```bash
python -m prometheus.orchestration.recipes --kind economy
python -m prometheus.jobs --root .prometheus/demo submit \
  --kind economy --owner local --idempotency-key economy-example-v1
python -m prometheus.jobs --root .prometheus/demo work --once
python -m prometheus.jobs --root .prometheus/demo list --owner local
python -m prometheus.jobs --root .prometheus/demo audit
```

Use the returned UUID in `show JOB_ID --owner local`,
`cancel JOB_ID --owner local`, or
`artifact JOB_ID --owner local --output evidence/my_job.json`, after the
same `--root` option. `work` without `--once` polls until interrupted.
Custom `--recipe` input is the complete flat configuration for its `--kind`,
not a bundle or the surrounding admission-plan report. The plan report's
`config` member contains that configuration.

The CLI trusts the OS caller. `--owner` scopes application lookups and
idempotency; it does not authenticate the caller. A future authenticated
service must derive owner from its principal and must not trust a
client-supplied owner. State directories must not be shared with hostile
local users or placed on network filesystems.

## Admission and identity

`orchestration.recipes` is the one immutable allowlist/typed dispatch table
for local jobs and replay. Unsupported kinds cannot select arbitrary
Python modules. Complete existing dataclass decoders reject missing or
unknown fields and invalid units/dates. No user Python or shell is run.

Service admission additionally bounds encoded bytes, nodes/depth, strings,
integer precision, steps, households, training/evaluation paths, epochs,
batches, seed/scenario counts and bootstrap resamples. Aggregate estimates
bound path values, training work, evaluation work, nested bootstrap work
and economic clearing/initialization work. Nested estimates account for
crossed rows, macro banks and conditional paths. Limits are not a calibrated
runtime model, an exact memory forecast or hard RSS/cgroup enforcement.

A detached canonical recipe and its kind receive a SHA-256 identity.
Idempotency binds the normalized request and execution timeout within an
owner namespace. Concurrent retries with the same key return one job;
changed requests conflict. Policy is persisted alongside schema version 1;
a different policy or unknown schema requires an explicit migration/new
store instead of silent reinterpretation.

## State and recovery

The state machine is:

```text
queued -> running -> succeeded | failed | timed_out
queued -> cancelled
running + cancellation_requested -> cancelled after worker stop/recovery
expired running lease -> queued for retry, or failed at attempt limit
```

Default policy permits 16 pending jobs per owner, 128 total pending jobs,
two running attempts, three attempts and a 300-second maximum wall budget.
Each claim has a new private token and expiration. Heartbeats extend only a
current unexpired token. A recovered/stale worker cannot finalize a newer
attempt. Cancellation fences success; queued cancellation is immediate and
running cancellation is confirmed after stopping execution. Computation is
at-least-once; publication has a current-token commit point. Exactly-once
computation is not claimed.

All mutation/event writes share a SQLite transaction. The implementation
uses explicit transactions, placeholders and FULL synchronization with
rollback journaling. These choices follow the transaction facilities in
[Python's sqlite3 reference](https://docs.python.org/3.14/library/sqlite3.html).
[SQLite's WAL documentation](https://www.sqlite.org/wal.html) describes its
single-host/shared-memory and version considerations; this local backend
uses rollback mode and rejects another journal mode. SQLite is a single-host
metadata store here, not a distributed queue or failover database.

Every submitted job records observed package/dependency/runtime provenance.
A mismatch before execution fails the job instead of silently running a
queued request under changed code. These observations are not a dependency
lock, signed code identity or complete numeric-environment capture. Updating
code may require submitting a new job/idempotency key. Old completed
artifacts retain their original provenance and can be numerically replayed
under the existing replay/runtime-drift contract.

## Process boundary

Each attempt uses a fresh `sys.executable` process, fixed module entry
point, file-based JSON request and `shell=False`. Sessions/process groups
support bounded termination as described in [Python's subprocess
reference](https://docs.python.org/3.14/library/subprocess.html). The parent
never invokes training, so Torch global RNG mutations stay in the child.
An allowlist forwards needed runtime variables and excludes service tokens.
This is not a complete OS/container sandbox for hostile code.

The child applies a fractional wall timer, CPU limit, file-size limit and
zero core-dump limit. Signal dispositions are restored before setting the
deadline, including when its parent ignored ALRM. See [Python's signal
reference](https://docs.python.org/3.14/library/signal.html). The parent also
uses a monotonic deadline and polls cancellation while renewing the lease.

Linux `PR_SET_PDEATHSIG` kills a child after its creating parent thread
terminates. The child sets it after exec and checks parent PID to close the
startup race; the [Linux manual](https://man7.org/linux/man-pages/man2/PR_SET_PDEATHSIG.2const.html)
documents that thread-specific behavior. Workers reject unsupported
platforms rather than promise this control there. Real tests use a dedicated
subreaper supervisor to inject parent death and reap children without
leaving test-host zombies.

Known inactive attempt directories can be cleaned. Cleanup checks both job
identity and token; it preserves current attempts, unknown entries and
symlinks. Parent/child deadlines and token fencing still apply while a
stale attempt is being removed. Unknown files are not automatically deleted.

## Artifact publication and audit

Artifacts are fully sealed and metadata-audited before publication. The
parent verifies runner kind, job/trace/recipe/attempt context and runtime.
Successful execution and scientific validity are distinct: an invalid
simulation gets failed status with its invalid evidence retained. An
inconclusive benchmark can finish execution successfully. Neither changes
R0's NO-GO gate.

Objects use content-addressed paths with no-clobber hard-link publication,
file/directory sync, readonly files and a local cross-process quota lock.
Defaults cap an object at 128 MiB and total object bytes at 1 GiB. Verified
existing objects deduplicate even at capacity; corrupted objects are never
silently replaced. Quota accounting includes orphan publisher files. Only a
committed current job references successful output; a database failure may
leave an unreferenced valid object. Garbage collection, retention policy,
state-root provisioning durability and power-failure/restore exercises are
not completed by these tests.

Append-only application events form a global hash chain. Audit checks chain
continuity and its job-state projection, including submitted recipe/runtime/
resource fingerprints and final artifact/result/error associations. Owner
and trace correlation are retained. `audit --expected-head-sha256 HASH`
can compare an externally trusted checkpoint. A privileged database owner
can rewrite/truncate history and its hashes; signatures or external trusted
checkpoints are needed to establish stronger authenticity.

Hard RSS/cgroup quotas, per-period compute credits, credential rate limits,
SSO/OIDC and deployed HTTP controls, distributed execution, signed builds/audit
checkpoints, backup/restore, SLO validation and independent promotion
reviews remain explicit requirements. The local CLI is an implementation
foundation, not industrial/production approval.
