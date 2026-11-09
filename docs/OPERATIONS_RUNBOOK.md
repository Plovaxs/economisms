# Operational runbooks and rollback process

This indexes the real, tested incident-response and rollback mechanics
that exist in this codebase today (OPS-11, DRI-02/03/04, part of DOC-08).
Every runbook below is backed by an executable module with a real
simulated drill producing a real timestamped timeline — not a prose
checklist nobody has run. Where a gap exists, it's stated here rather than
implied covered.

## Incident runbooks (OPS-11, DRI-02/03/04)

[`prometheus.evidence.runbook_catalog`](../src/prometheus/evidence/runbook_catalog.py)
runs a real simulated on-call drill for each of this project's named
failure categories, all producing a `DrillReport` in the same comparable
`DrillStep`/timeline shape:

- **`solver_failure`** →
  [`evidence.numerical_integrity_runbook`](../src/prometheus/evidence/numerical_integrity_runbook.py)
  (DRI-02): isolate the affected numerical path, invalidate results
  produced while it was compromised, re-evaluate.
- **`credential_compromise`** →
  [`evidence.credential_rotation_drill`](../src/prometheus/evidence/credential_rotation_drill.py)
  (DRI-03): `rotate_credential` (the real rotation action) composed with
  `run_credential_rotation_drill` (the real verification that the old
  credential no longer authenticates and the new one does).
- **Corrupt-data / point-in-time leak** →
  [`evidence.pit_leak_response`](../src/prometheus/evidence/pit_leak_response.py)
  (DRI-04): the response procedure when a point-in-time violation
  (future data observed by a decision that shouldn't have seen it) is
  detected.

`DrillReport.passed` is a real outcome, not a hardcoded constant — this
module's own tests include a drill that genuinely fails (a persistently
failing numerical call; a credential check against the wrong new token)
alongside one that genuinely succeeds, so "the drill passed" means the
simulated procedure was actually exercised against both outcomes.

## Backup / restore (DRI-07/08)

[`prometheus.recovery.snapshot`](../src/prometheus/recovery/snapshot.py):
streamed AES-256-GCM encrypted local snapshots; a restore drill decrypts
and authenticates fully into private staging before any metadata is
parsed, and publishes a new state root only once verified. See
[docs/SECURITY_AND_DATA_HANDLING.md § Data at rest](./SECURITY_AND_DATA_HANDLING.md#data-at-rest)
for what this does and does not cover (offsite transfer and production
RPO/RTO are explicitly out of scope of this local mechanism).

## Model registry: invalidation vs. rollback — what's actually demonstrated

[`prometheus.evidence.model_registry`](../src/prometheus/evidence/model_registry.py)
(MLO-08) enforces a code-level transition policy:
`candidate → evaluated → approved → staged → retired` is the only forward
path, and **any** non-retired state may additionally move directly to
`retired` — an emergency pull is legitimate at any stage. This gives a
real, tested **invalidation** mechanism (pull a bad model out of service
immediately, from any state).

**What this registry does NOT do, by explicit design**: any *backward*
transition (e.g. `staged → approved`, reinstating a previously-approved
model as the active one after a bad promotion) is rejected by
`is_allowed_transition` with `IllegalTransitionError`, the same as any
other illegal transition. The state machine's own docstring is explicit
about this being a deliberate choice, not an oversight.

**Honest status**: invalidation (pull) is implemented and tested.
Reinstating a specific prior version as the one actively serving traffic —
the stronger "versioned rollback" claim in the blueprint's `LCH-10`
("demonstrate versioned rollback and model invalidation") — is **not**
separately demonstrated by this registry. A real rollback in this system
today means: retire the bad `staged`/`approved` entry, then promote a
different (e.g. previously packaged) `ModelPackage` through
`candidate → evaluated → approved` from scratch, which re-runs the full
provenance/validation gate (`promote_to_approved`, MLO-10) rather than
silently reactivating an old approval. This is arguably the more
conservative, defensible behavior (no model re-enters service without
re-clearing the gate), but it is not the same thing as a one-step
"revert" operation, and this document says so rather than implying one
exists. See `CHECKLIST_STATUS.md`'s `LCH` category for `LCH-10`'s current
status.

## Deploy manifests (CIQ-11)

[`prometheus.service.deploy_manifest`](../src/prometheus/service/deploy_manifest.py)
stores complete deploy manifests, configuration, and feature flags —
the record a rollback-by-redeploy would actually read from.
