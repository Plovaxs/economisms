# NIST CSF 2.0 profile

CMP-03: map security outcomes to NIST CSF 2.0 as needed; acceptance —
"profile lists current/target state and evidence."

**Technical self-assessment, not a certification or audit.** A current-
state profile against the Cybersecurity Framework 2.0's six functions
(Govern, Identify, Protect, Detect, Respond, Recover), scoped to what
this repository's source tree can actually prove — not an organization-
wide profile (this repository is not an organization; see
`CONTRIBUTING.md`).

| Function | Current state | Evidence | Target state |
|---|---|---|---|
| **Govern** | Partial | `docs/THREAT_MODEL.md`, `evidence.risk_register`, `SECURITY.md` | Named second-party security owner (needs real organizational growth) |
| **Identify** | Largely in place | `docs/THREAT_MODEL.md` § Assets/Trust boundaries, `docs/DATA_PROCESSING_INVENTORY.md`, `evidence.model_inventory` | Live dependency-vulnerability inventory (RV.3 gap, see `NIST_SSDF_MAPPING.md`) |
| **Protect** | Partial | `service.auth` (token hashing), TLS-or-loopback-only binding, `data_ingestion.egress_allowlist` (SEC-10, wired into real connectors), hash-pinned reproducible builds | Branch protection / MFA on the hosting account (SEC-02/03, outside this repo's source tree) |
| **Detect** | Partial | `evidence.security_scan` (secret/license/PII scans, run pre-commit), `evidence.numerical_event_monitor` | Live CVE/dependency-advisory scanning (not currently queryable from this hermetic environment) |
| **Respond** | In place | `evidence.runbook_catalog` (real drilled runbooks for solver failure, credential compromise, PIT leaks), `docs/OPERATIONS_RUNBOOK.md` | — |
| **Recover** | Partial | `recovery.snapshot` (AES-256-GCM local restore, drilled under DRI-08) | Offsite transfer, production RPO/RTO (explicitly out of scope of the local mechanism) |

## What "current state" means here

Every "in place" / "partial" cell above traces to a real test or a
real, committed document — not an unverified self-rating. "Partial"
cells name the specific missing half in the Target-state column rather
than leaving it implicit. No cell claims "complete": this repository's
own standing position (see `README.md`) is that no independent review
of any security claim here has happened.
