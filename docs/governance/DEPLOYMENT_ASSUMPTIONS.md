# Jurisdiction and entity deployment assumptions

GOV-10: document jurisdiction and entity deployment assumptions;
acceptance — "deployment form lists location, user type and activity."

This is a statement of what actually exists today, not a hypothetical
deployment plan for a system that isn't deployed.

| Field | Value |
|---|---|
| **Deploying entity** | None. This is an unincorporated, single-maintainer open-source research repository, not a deployed service operated by any legal entity. |
| **Hosting location** | Wherever the maintainer or a user runs it locally (`prometheus.service`, loopback-bound by default per `docs/RESEARCH_API.md`) — no hosted/cloud deployment exists. |
| **User type** | Researchers and engineers running the code themselves. No end-user-facing product exists. |
| **Activity** | Research and simulation only — see
  [README.md § Status & disclaimers](../../README.md#status--disclaimers).
  No live trading, no order routing, no real brokerage connection, no
  real financial advice, enforced at the gate-record level (see
  `evidence/gate_report_r0.json`'s `scope_prohibited`). |
| **Applicable jurisdiction** | Not determined — there is no deploying entity for a jurisdiction to attach to. See `docs/compliance/` for the technical NIST mapping work already done; actual jurisdiction-specific legal applicability (CMP-06/07/08) requires real counsel review this repository does not have, and is explicitly left open there. |

**If this project is ever deployed by a real entity**, this document
must be updated BEFORE that deployment, not after — the same
"disclose before you build on it" discipline this project applies to
every other assumption (see `CONTRIBUTING.md`).
