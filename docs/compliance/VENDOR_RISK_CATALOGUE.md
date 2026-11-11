# Third-party/vendor risk control catalogue

CMP-10: define third-party/vendor risk control catalogue; acceptance —
"due diligence, concentration and exit plans reviewed."

**Technical self-assessment, not a procurement/legal review.** This
repository has no paid vendor contract of any kind — see
`docs/DATA_PROCESSING_INVENTORY.md`'s own PRV-08 section, which already
confirms every external DATA source this project calls (FRED, World
Bank Open Data, the Kenneth French Data Library) is free, public and
requires no contract or processor agreement. This catalogue extends
that same confirmed-not-applicable finding to this repository's actual
INFRASTRUCTURE dependencies — the things a real vendor-risk program
would ask about even for a project with no paid vendor relationship —
rather than silently assuming CMP-10 doesn't apply at all.

| Dependency | Relationship | Due diligence | Concentration risk | Exit plan |
|---|---|---|---|---|
| **GitHub** (`github.com/Plovaxs/economisms`) | Free-tier code hosting + CI runner; no payment, no SLA | Public company, widely audited infrastructure; no credentials or secrets are stored there beyond what `evidence.security_scan.secret_scan` already confirms absent | Single point of failure for hosting and CI today — no mirror currently maintained | Git is fully distributed by design: every local clone (including the one this repository was developed in) already IS a complete mirror of history; moving to another host is a `git remote` change and a push, not a migration project |
| **PyPI / the Python package ecosystem** (NumPy, SciPy, PyTorch, uvicorn, etc.) | Open-source dependencies, each with its own maintainers | `docs/LICENSE_INVENTORY.md` records every direct dependency's real license (machine-generated from installed package metadata, not hand-typed); `evaluate_release_gate` blocks release on an unapproved high/critical scan finding | Hash-pinned via `requirements/bootstrap.txt` (`--require-hashes`) and `uv.lock` — a compromised future PyPI release cannot silently substitute itself for a pinned version already recorded | Pinned versions mean no forced-upgrade exposure; the exact set of wheels this project depends on could be vendored into a private mirror if PyPI became unavailable, without any code change |
| **FRED, World Bank Open Data, Kenneth French Data Library** | Free, public, no-authentication data republication | Already reviewed under PRV-08 (`docs/DATA_PROCESSING_INVENTORY.md`) | Each source is used independently (e.g. `DAT-04` uses Treasury directly, not FRED, specifically because FRED has proven unreachable from this environment — an already-disclosed, already-worked-around concentration risk, not a hidden one) | No contract to exit; a source going offline is a data-availability problem for a specific connector, not a vendor-lock-in problem |
| **Any paid API, SaaS, or data vendor** | None exists today | — | — | If one is ever introduced, a real security/contract review is required before that integration ships (`docs/DATA_PROCESSING_INVENTORY.md`'s own stated policy) — this catalogue existing and being checked is the mechanism that would catch an unreviewed addition, the same pattern PRV-05/PRV-08 already use |

## What this is, and is not

This is a real, accurate inventory of this repository's actual
infrastructure dependencies and an honest technical assessment of
each one's concentration risk and exit cost — not a claim that a
formal procurement due-diligence process, a signed vendor contract
review, or a legal exit-clause negotiation has happened, because none
of those apply to free, unpaid, open-source infrastructure in the
first place. If a future paid vendor relationship is introduced, this
table is the place that change must be recorded, reviewed, and (for
anything material) escalated to real legal/procurement review before
it ships.
