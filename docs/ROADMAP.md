# Roadmap to a trustworthy 1.0

The project does not need more features to be more credible; it needs more evidence. This roadmap follows the
milestones of the 24 November 2026 technical audit, in its order, and says where each stands. The detail, item by
item, is in the [audit response register](./audit/REGISTER.md); the plan for the science is the
[confirmatory protocol](./CONFIRMATORY_PROTOCOL.md).

| Milestone | Gate (the audit's wording) | Where it stands |
| --- | --- | --- |
| **M0 freeze** | Commit SHA, source manifest, issue register and score rubric. | **Done**: [audit/BASELINE.md](./audit/BASELINE.md). |
| **M1 reliability** | Independent leakage checks, replay tolerance, critical-path tests. | Partial: data QA report, data-use audit, resilience and parity tests, a mutation check. Independent leakage review and cross-machine replay need other people and machines. |
| **M2 science** | Preregister and run confirmatory experiments. | Partial and waiting for the maintainer: the protocol, the analysis code, the power note, the locked CPI data and the freeze guard exist. Open: confirm the margins, choose the S&P source, decide the multiplicity family, design E4, freeze, anchor externally. Then run. |
| **M3 math** | Convergence, error and compute benchmarks. | Partial: Monte Carlo calibration and error rate, grid-solver orders. Not done: strong convergence, dimension scaling at matched error. |
| **M4 desktop** | AppImage/DEB, Linux matrix, recovery and UX. | Partial: a clean-install matrix runs on fresh machines ([SUPPORT_MATRIX.md](./SUPPORT_MATRIX.md)). AppImage/DEB not built: the maintainer's decision. No task results from new users. |
| **M5 release** | Security review, provenance, documentation. | Partial: a signed build-provenance attestation step, a verification guide and a runbook exist; the attestation ran on release 0.5.4 and all its files verify; no independent security review. |
| **M6 dissemination** | External replication, citation and archival release. | Partial: `CITATION.cff`, a replication guide and a report form. No DOI, no external report, no paper. |

## Policy while this lasts: a feature freeze

No new model, runner or dataset unless it (a) is needed to answer a question in the confirmatory protocol, or (b)
closes a reliability or integrity gap in the register. A new runner comes with its classical baseline, a power
note and a test that it reproduces something known. A new finding is reported with what it does not show.

## Non-goals for 1.0 (from the audit, and kept)

- Live trading, brokerage integration, or anything that would route an order. The gate decision stays **NO-GO**.
- A forced Windows or macOS port: Linux is the supported platform; the web demo runs anywhere.
- Feature-count targets, or artificial pressure to make a deep-learning or quantum model win. A negative result with
  rigorous evidence is a successful outcome.
- Chasing GitHub stars. Three independent replications are worth more.

## What only other people can supply

External replication of at least two frozen findings, a domain economist's review, a statistician's review of the
margins and the power notes, an independent security assessment, and five new users completing install,
experiment and export without help. The [replication guide](./REPLICATION_GUIDE.md) is how they would start.
