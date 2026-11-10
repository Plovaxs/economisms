# Release classes, change management, and no-go escalation

GOV-02 (release classes/promotion authority), GOV-13 (change management/
rollback authority), GOV-14 (no-go escalation) — three closely related
governance processes, documented together.

## Release classes (GOV-02)

This project uses a single real, generated gate today: **R0**, produced
by `evidence.gate_report`/`evidence.repository_status` and published at
[`evidence/gate_report_r0.json`](../../evidence/gate_report_r0.json).
Its `scope_prohibited` field is the real, enforced floor every class
inherits: **live trading, order routing, or any brokerage connection is
excluded at every release class, unconditionally** — not a default that
a later class relaxes.

| Class | Meaning here | Status |
|---|---|---|
| R0 | Internal research state, no external users | **Real, current.** `evidence/gate_report_r0.json`, decision = `NO-GO` |
| R1 | Reviewed internal candidate | Not defined — no criteria exist yet distinguishing it from R0 |
| R2 | External-facing research release (still paper-only) | Referenced by name in several blueprint items (DRI-01, LCH-04) but no gate criteria defined in this repository |
| R3 | Not used | Undefined |

**Promotion authority**: `evidence.gate_report.GateDecisionForm` already
enforces, in code, that a `GO`/`CONDITIONAL` decision cannot be
constructed without naming `scientific_approval` and
`security_ops_approval` (see `CHECKLIST_STATUS.md`'s LCH-12 entry) —
this IS the promotion-authority mechanism for whichever class reaches a
GO decision. What's genuinely missing: distinct, named criteria for
R1/R2/R3 as separate classes, and named individuals authorized to grant
each. **GOV-02 is marked partial**: the paper-only-default and
live-trading-exclusion half is real and enforced; the full R0-R3 ladder
with distinct promotion authority per class is not built.

## Change management and rollback authority (GOV-13)

Reuses two real, already-evidenced mechanisms rather than defining a
third, parallel one:

- **Breaking changes**: `service.deploy_manifest.BreakingChangeNotice`
  (CIQ-12) — a breaking change cannot be recorded without a named
  `owner_approved_by`, a maintenance window, a change-log URL, and at
  least one named affected client.
- **Rollback**: `evidence.model_serving.ModelServingSlot.rollback_to`/
  `deploy_if_not_retired` (MLO-12/MGR-12) — a real, tested, content-
  addressed rollback with stale-cache purge, and a refusal to redeploy
  a retired model.

**Rollback authority**: in this single-maintainer repository, that is
the project maintainer — see `CONTRIBUTING.md`. No second, distinct
emergency-approver role exists to name, for the same honest reason
GOV-03 is open.

## No-go escalation (GOV-14)

The route, stated plainly:

1. **Stop-work**: any contributor (today, the maintainer) who finds a
   P0-severity issue (`evidence.severity_matrix`, DRI-01) halts further
   release-track work on the affected scope immediately — there is no
   "finish the PR first" exception for a P0.
2. **Notification**: a P0 routes through the existing
   `evidence.alert_routing.route_alert("P0", ...)` primitive (OPS-10) —
   the same real routing mechanism `data_ingestion.egress_allowlist`
   and `evidence.incident_management.page` already use, reused rather
   than a fourth parallel escalation path.
3. **Risk sign-off**: the gate decision itself is the sign-off record —
   `evidence.gate_report.GateDecisionForm` with `decision="NO-GO"` is
   precisely this project's own real, current no-go record (see
   `evidence/gate_report_r0.json`), not a hypothetical process that has
   never actually been exercised. This project IS, right now, in its
   own no-go escalation state, continuously, since R0 was first
   generated.

This closes GOV-14's three named pieces (stop-work, notification, risk
sign-off) using real, already-tested primitives — no new code was
needed, only naming the real route explicitly.
