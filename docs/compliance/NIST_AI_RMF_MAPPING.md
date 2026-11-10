# NIST AI RMF applicability matrix

CMP-01: map selected controls to NIST AI RMF Govern/Map/Measure/Manage;
acceptance — "applicability matrix cites specific outcomes; not faux
certification."

**This is a technical self-assessment, not a certification, an audit,
or a legal compliance determination.** No regulator or accredited body
has reviewed this repository against the NIST AI Risk Management
Framework (AI RMF 1.0). It maps this repository's own real, already-
evidenced controls (cited to `CHECKLIST_STATUS.md` IDs and source
files) against the Framework's four functions, so a reader doing real
due diligence has a starting point — not a claim that this repository
is "NIST AI RMF compliant," a phrase the Framework itself does not
define.

## Govern

| AI RMF outcome (representative) | This repository's control | Status |
|---|---|---|
| Policies, processes and procedures are in place for AI risk management | `CONTRIBUTING.md`, `docs/PROBLEM_STATEMENT.md`, `CHECKLIST_STATUS.md`'s evidence discipline | Documented |
| Risk management roles and responsibilities are established | `docs/THREAT_MODEL.md`, `evidence.risk_register` (GOV-12) | Partial — single-maintainer repository; no RACI with distinct deputies (GOV-03 explicitly open) |
| Mechanisms exist to inventory AI systems and assess risk | `evidence.model_inventory` (MGR-01), `evidence.model_registry` (MLO-08) | Documented |
| Policies address third-party AI risk (data, software, models) | `docs/LICENSE_INVENTORY.md` (PRV-01/07), `docs/SECURITY_AND_DATA_HANDLING.md` | Documented |

## Map

| AI RMF outcome (representative) | This repository's control | Status |
|---|---|---|
| Context, intended purposes, and limitations are documented | `docs/PROBLEM_STATEMENT.md`, `README.md` § Status & disclaimers | Documented |
| AI system categorization reflects risk | `evidence.model_inventory`'s `materiality_tier` (every entry "research," none production) | Documented |
| Impacts to individuals, groups, and society are characterized | `docs/DATA_PROCESSING_INVENTORY.md` (no personal/financial-individual data processed) | Documented |

## Measure

| AI RMF outcome (representative) | This repository's control | Status |
|---|---|---|
| Appropriate methods/metrics identify AI risks | `docs/EXPERIMENT_GUIDE.md`, `evidence.champion_challenger` (MLO-14), proper scoring rules (NSD-08) | Documented |
| AI systems are evaluated for trustworthy characteristics (validity, reliability, safety) | `docs/RESULTS_AND_LIMITATIONS.md` — including negative/null findings, not just favorable ones | Documented |
| Mechanisms for tracking identified risks over time are in place | `evidence.retraining_trigger`/`model_monitoring` (MLO-13/OPS-08) | Documented |

## Manage

| AI RMF outcome (representative) | This repository's control | Status |
|---|---|---|
| Risks are prioritized and responded to based on impact | `evidence.risk_register` (GOV-12), `evidence.alert_routing` (OPS-10) | Documented |
| Mechanisms are in place for safe decommissioning | `evidence.model_serving.deploy_if_not_retired` (MGR-12), `evidence.model_registry`'s retirement state | Documented |
| Incidents are responded to, managed, and communicated | `docs/OPERATIONS_RUNBOOK.md`, `evidence.runbook_catalog` | Documented |

## Known gaps (not addressed by any control above)

Independent third-party assessment, a formal AI risk committee, and
production deployment-specific controls (since this is NO-GO for
production) — see `CHECKLIST_STATUS.md`'s `GOV`/`MGR`/`LCH` categories
for the exact open items this honestly maps to.
