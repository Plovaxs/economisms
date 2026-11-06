# Full-blueprint implementation scope

The user requested the entire master blueprint, including industrial
engineering quality. The authoritative requirement inventory is
[blueprint_register.json](./implementation/blueprint_register.json),
extracted from the repository PDF and linked to current repository notes.
The supplied Downloads PDF has the same SHA-256 as the repository copy.

This plan preserves all 374 items in 29 categories. It does not redefine
completion around the existing toy scenarios or passing tests. Existing
implementation notes and local artifacts are evidence to assess; every
requirement still needs its actual acceptance criterion satisfied. No
independent approval has been inferred from source code or test counts.

| Workstream | Categories | Items | Work still required for acceptance |
|------------|------------|-------|------------------------------------|
| Ownership, traceability and review | GOV, AUD, DOC, MGR | 52 | requirement-to-test/artifact links, durable lineage, assigned accountable roles, documented review and independent model challenge |
| Financial/economic correctness | ECO, LED, SDE, PRI, RISK, OPT, VAL | 92 | close each specified model/accounting gap, independent reference cases, extremes/invariants, integration across portfolio/market/economic states |
| Data, vintages and experiment design | DAT, PRV, EXP | 40 | licensed data inventory, versioned ingestion/known-at views, immutable splits, explicit endpoint protocols and credible uncertainty validation |
| Learned model families | MAR, NSD, PDE, HDG | 53 | specified agent families, neural SDE/PDE/BSDE ladders, causal features, constraints, negative controls and held-out benchmarks |
| Research service and user interfaces | API, UIX | 24 | typed bounded job APIs, status/cancellation, authenticated read/write roles, usable evidence/risk/lineage interfaces and end-to-end tests |
| Operational/release engineering | MLO, SEC, CIQ, REL, OPS, DRI | 77 | reproducible locked builds, model registry/lifecycle, threat controls, observability/SLOs, backup/restore/failover and incident exercises |
| Compliance and release gates | CMP, LCH | 24 | documented applicability/ownership, retention/licensing controls, reproducible release evidence and actual scoped review decisions |
| Separately gated live extension | EXT | 12 | institution-approved prerequisites, independent authorization and controlled validation; no live orders are authorized by this plan |
| Total | all 29 categories | 374 | assess each acceptance criterion individually |

The workstreams are dependency groups, not a claim that a group is
complete or a fixed delivery date. Existing local work spans multiple
groups. Implement reversible software work autonomously; record human
review/authorization requirements as outstanding until supplied. Do not
invent signatories, silently mark checklist items accepted or treat a
self-consistent checksum as proof of provenance/authorship.

PR-046 adds common typed recipe/resource admission, durable local
artifact/job storage and fenced Linux job lifecycle controls. PR-047 adds
an authenticated ASGI/OpenAPI service boundary and typed SDK, with private
service tokens and owner-derived read/write scopes. SSO/OIDC and deployed
identity/transport validation remain open. PR-048 adds hash-locked Python/build
profiles, independent wheel rebuild checks and authenticated encrypted local
snapshot/restore. Container/OS rebuild, signed provenance, offsite custody,
retention policy and approved recovery/failover objectives remain open.
Further priorities include operational observability/capacity controls and
the remaining numerical, data and learned-model workstreams.
These do not replace remaining numerical, learned-model, data, interface
or independent-review requirements.

Regenerate the scope register after changing checklist notes:

```bash
python -m prometheus.evidence.requirements \
  --pdf docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf \
  --checklist CHECKLIST_STATUS.md \
  --output docs/implementation/blueprint_register.json
```

Each registry item includes exact source requirement and acceptance text,
PDF page, retained layout rows, category/track, current unreviewed note
links, and explicit NOT VERIFIED acceptance status. Items without notes
remain in the inventory. A linked row can be partial; note presence is not
a completion percentage. CI checks that the PDF parses to all 374 unique
items and that the tracked registry reflects current PDF/checklist inputs.
