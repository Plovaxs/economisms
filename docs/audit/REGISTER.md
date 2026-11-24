# Audit response register

*Generated from `register.json` by `python -m prometheus.evidence.audit_register render`; do not edit.*

The review: **ECONOSIM Full Technical Research Audit**, 2026-11-24, of version 0.5.2 (commit `05905835`). It was documentation-based review: repository documentation and recent commit metadata, not an executed audit, source-code inspection, security test or peer review; the scores are the reviewer's judgments.

This register records, for each of the audit's work packages, what exists in the repository and what does
not. **It does not change any score**: see the rule below. Evidence levels follow the audit's scale:

- **E0**: proposed, no evidence
- **E1**: documented claim
- **E2**: inspectable test and artifact
- **E3**: independently executed on a clean environment
- **E4**: replicated by an external reviewer with a published protocol

Statuses:

- **done**: the audit's gate is met, with inspectable evidence in this repository
- **partial**: some of the gate is met; `remaining` says what is not
- **not_started**: nothing yet
- **needs_maintainer**: only the maintainer can decide or do it
- **needs_external**: needs a person or party outside the project
- **declined**: decided against by the maintainer, with the reasons recorded; revisit only if a real need appears

**58 items: 6 done, 42 partial, 5 needs external, 4 not started, 1 declined.** No item is above evidence level E2.

## Scientific redesign (SCI)

| ID | Item | Status | Level | Evidence | What is missing | Who |
| --- | --- | --- | --- | --- | --- | --- |
| SCI-01 | Literature map and research gap | partial | E1 | `docs/LITERATURE_MAP.md` | A draft protocol, a 20-work comparator matrix and a scoped novelty statement exist (abstract-level, web lookups). The protocol has not been run: no database search, screening or full-text reading. | external |
| SCI-02 | Prospective protocol | partial | E2 | `docs/CONFIRMATORY_PROTOCOL.md`<br>`docs/confirmatory/DATA_USE_AUDIT.md`<br>`docs/confirmatory/power_note.json`<br>`src/prometheus/confirmatory/freeze.py` | Draft is complete except the maintainer's part: confirm every margin, choose the S&P source, decide the multiplicity family, design E4, freeze and anchor externally (OSF or a DOI). Binds nothing until then. | maintainer |
| SCI-03 | Temporal holdout | partial | E2 | `docs/confirmatory/DATA_USE_AUDIT.md`<br>`tests/unit/test_confirmatory_e3.py` | E1-E3 are covered: frozen pipelines, a data-use audit, a guard on untouched data, and a differential test that E3's forecaster equals the study's. Split manifests of the older studies have not been audited. | maintainer |
| SCI-04 | Statistical analysis | partial | E2 | `src/prometheus/confirmatory/intervals.py`<br>`src/prometheus/experiments/forecast_comparison.py`<br>`docs/confirmatory/power_note.json`<br>`tests/unit/test_confirmatory_intervals.py`<br>`tests/unit/test_forecast_comparison.py` | Paired block-bootstrap intervals, Bonferroni, equivalence margins, exact binomial intervals and power notes exist for the confirmatory endpoints, and a Diebold-Mariano test (Harvey-Leybourne-Newbold correction, Bartlett long-run variance) is implemented and tested for size, power and the repair of serial dependence. Exploratory use: on Finding 18's Q1 (277 months, absolute error, 11 lags) it gives -5.84 (p = 1.5e-8), agreeing with the bootstrap interval. The earlier findings use no multiplicity control, and the test is not part of the confirmatory protocol. | assistant |
| SCI-05 | Robustness | not started | E0 | `docs/CONFIRMATORY_PROTOCOL.md` | E4 (neural SDE under several shocks) is left open on purpose pending a data-use audit; one country and one market throughout. | maintainer |
| SCI-06 | External replication | needs external | E1 | `docs/REPLICATION_GUIDE.md`<br>`.github/ISSUE_TEMPLATE/replication-report.yml` | The guide and the report form exist. No one else has run anything. | external |
| SCI-07 | Economic validity | needs external | E0 | none | Needs a domain economist; nothing here can stand in for one. | external |
| SCI-08 | Publication package | partial | E1 | `CITATION.cff`<br>`docs/FINAL_PAPER.md`<br>`docs/release/VERIFYING.md`<br>`confirmatory_data/README.md` | CITATION.cff, tagged releases with checksums, an SBOM, locked confirmatory data and a draft paper exist. No DOI (the maintainer must connect an archive) and no submitted paper. | maintainer |

## Mathematical verification (M)

| ID | Item | Status | Level | Evidence | What is missing | Who |
| --- | --- | --- | --- | --- | --- | --- |
| M-01 | SDE strong/weak convergence | done | E2 | `tests/unit/test_sde_integrators_known_solution.py`<br>`tests/unit/test_stochastica_convergence.py` | The repository's two integrators (Euler-Maruyama and the drift-corrected stochastic Heun scheme) were run unchanged on geometric Brownian motion against its exact solution on the same Brownian path: strong order 0.486 and 0.489 (expected 1/2 for Euler-type noise), seed-to-seed spread 0.001, and the mean of each scheme equals the closed form of what it computes within Monte Carlo error, the corrected scheme about 15-25 times closer to the exact mean. Heston's weak order is measured separately. No Milstein scheme exists to test, and Heston's strong convergence is not measured. | assistant |
| M-02 | Monte Carlo diagnostics | done | E2 | `tests/unit/test_numerical_verification.py` | Standard errors are calibrated (z spread 0.98-1.02, 94.5-95.3% coverage over 4,000 replications), error slope -0.505, control variate about 2.6x. Antithetic variates are not implemented. | assistant |
| M-03 | PDE residuals | partial | E2 | `tests/unit/test_numerical_verification.py`<br>`tests/unit/test_pde_grid.py` | Closed-form comparison and observed orders (space 2.00; time 1.08-1.53 for a kinked payoff). Interior residuals and boundary/terminal errors are not measured directly. | assistant |
| M-04 | Dimension scaling | partial | E1 | `docs/RESULTS_AND_LIMITATIONS.md` | Finding 6 measures 1D and the grid's M^d mechanism; matched-error runtime and memory at d = 2, 3 and above are not measured. | assistant |
| M-05 | Option constraints | done | E2 | `tests/unit/test_black_scholes.py`<br>`tests/unit/test_greeks_fd.py`<br>`tests/property/test_metamorphic_suite.py` | Bounds, put-call parity (Black-Scholes, Heston, Merton), monotonicity, and Greeks against finite differences are tested; mutation check covers the closed forms. | assistant |
| M-06 | Economy invariants | done | E2 | `tests/property/test_ledger_invariants.py`<br>`tests/unit/test_ledger.py`<br>`tools/mutation_check.py` | Property tests plus six ledger mutations, each caught. | assistant |
| M-07 | Risk validation | partial | E2 | `tests/unit/test_risk_metrics.py`<br>`tests/unit/test_confirmatory_e3.py` | Kupiec, Christoffersen and conditional coverage, pinball and QLIKE losses exist and are tested; six risk-metric mutations are caught. Tail dependence and stress regimes are not diagnosed beyond Finding 15. | assistant |
| M-08 | Sensitivity | partial | E1 | `src/prometheus/volterra/identifiability.py` | An identifiability module and a multi-solver study exist; failure domains are not published. | assistant |

## Data and leakage (D)

| ID | Item | Status | Level | Evidence | What is missing | Who |
| --- | --- | --- | --- | --- | --- | --- |
| D-01 | Dataset registry | partial | E2 | `docs/data/dataset_registry.json`<br>`src/prometheus/data_ingestion/dataset_registry.py`<br>`tests/unit/test_dataset_registry.py` | Generated from the files, drift-tested, no snapshot lacks metadata. The French-factor snapshot's download date was never recorded (its metadata says so and records a full comparison with the library's file on 25 Nov 2026: all 1,203 months identical); units are only as declared in the metadata. | maintainer |
| D-02 | Release-aware alignment | partial | E2 | `src/prometheus/econosim/pit.py`<br>`docs/DATA_DICTIONARY.md` | A fixed-lag point-in-time convention with leak tests exists; a per-feature audit is not automated. The GDP look-ahead is the proof that one was needed. | external |
| D-03 | Historical vintages | partial | E1 | `docs/data/dataset_registry.json` | Every snapshot is labelled revised-only in the registry. ALFRED is not reachable from the development environment, so no real-time vintage was used. | maintainer |
| D-04 | Pipeline isolation | partial | E2 | `src/prometheus/orchestration/market_risk_study.py` | Chronological splits and a per-forecaster leak test exist in the studies that have them; no repository-wide audit. | external |
| D-05 | Cross-market validation | not started | E0 | none | US data only. | maintainer |
| D-06 | Data QA | partial | E2 | `docs/data/data_qa_report.json`<br>`tests/unit/test_dataset_registry.py` | Missingness, outliers, duplicate and out-of-order dates, gaps and header drift are reported and pinned; revisions are quantified only for CPI (the vintage overlap). | assistant |
| D-07 | Independent leakage review | needs external | E1 | `docs/confirmatory/DATA_USE_AUDIT.md` | The assistant audited the confirmatory windows; an independent rebuild from raw data is not done. | external |
| D-08 | Immutable artifacts | partial | E2 | `data_cache/MANIFEST.sha256.json`<br>`confirmatory_data/README.md`<br>`src/prometheus/confirmatory/bls_fetch.py` | A digest manifest with an integrity check, locked confirmatory data and a write-once fetch tool exist; Kaggle acquisition needs the maintainer's token. | maintainer |

## Linux release engineering (L)

| ID | Item | Status | Level | Evidence | What is missing | Who |
| --- | --- | --- | --- | --- | --- | --- |
| L-01 | AppImage + DEB | declined | E0 | `scripts/install-linux.sh` | Decided against by the maintainer on 25 Nov 2026 after weighing it: the bundle would be gigabytes (PyTorch and Qt), bundling Qt brings LGPL obligations (license texts, a source offer, replaceable libraries), glibc compatibility and other distributions cannot be tested here, and the audit itself advises against extra formats until a real need appears. The install script and its clean-machine test remain the supported route. Revisit with an AppImage only (no DEB) if someone cannot use the script. | maintainer |
| L-02 | Support matrix | partial | E2 | `docs/SUPPORT_MATRIX.md`<br>`.github/workflows/installer-smoke.yml` | Ubuntu 22.04 (clean refusal: Python 3.10), Ubuntu 24.04 and Debian 12 on x86-64, X11 via Xvfb. No Wayland, no Arm. | assistant |
| L-03 | Clean install | partial | E2 | `.github/workflows/installer-smoke.yml`<br>`scripts/installer-smoke.sh` | Fresh GitHub-hosted VMs and a container, every run. No independent physical machine. | external |
| L-04 | CPU / optional CUDA | partial | E1 | `scripts/install-linux.sh` | The installer uses the CPU build of PyTorch and every lab runs on it. CUDA is not validated and not documented as supported. | maintainer |
| L-05 | Offline workflow | not started | E0 | none | The installer needs the network (PyTorch and others). The datasets are committed, so the labs themselves run offline once installed; this is not documented as a workflow. | assistant |
| L-06 | Upgrade and uninstall | partial | E2 | `tests/unit/test_install_script.py`<br>`scripts/installer-smoke.sh` | A data-loss hazard (the installer used the application's results directory as its own) was found and fixed; upgrade keeping results and a clean uninstall are tested on fresh VMs. No rollback to the previous version. | assistant |
| L-07 | Desktop reliability | partial | E2 | `tests/unit/test_desktop_session.py`<br>`tests/unit/test_job_worker.py`<br>`scripts/installer-smoke.sh` | Offscreen tests cover run, cancel, export, reopen and crash recovery; the window runs 20 s on Xvfb. Launch from a real menu and desktop icon has not been observed on a real desktop. | external |
| L-08 | Release integrity | partial | E1 | `docs/release/VERIFYING.md`<br>`.github/workflows/release.yml`<br>`docs/release/dependency-sbom.cdx.json` | SBOM, SHA-256 and a signed build-provenance attestation are published; release 0.5.4 was the first, and all seven of its files verify with `gh attestation verify` (24 Nov 2026). Earlier releases carry checksums only. Attestation proves where bytes came from, not that the code is safe; no independent review. | maintainer |
| L-09 | Accessibility | partial | E2 | `docs/UIX_ACCESSIBILITY_TEST_PLAN.md`<br>`tests/unit/test_desktop_ui_window.py` | Accessible names, focus and computed contrast are tested; no assistive-technology or user testing. | external |

## Quality, security and UX

| ID | Item | Status | Level | Evidence | What is missing | Who |
| --- | --- | --- | --- | --- | --- | --- |
| Q-1 | Testing | partial | E2 | `tools/mutation_check.py`<br>`tests/unit/test_mutation_catalogue.py`<br>`tests/property/test_ledger_invariants.py`<br>`.github/workflows/mutation-check.yml` | For five critical modules (ledger, Black-Scholes, risk metrics, hedging accounting, block bootstrap): 100% statement and branch coverage by their own guarding tests, enforced weekly; 24 mutations, all caught on the CI reference profile; property tests for ledger invariants and put-call parity. The mutations found three real test gaps and the branch report found untested validation and funding-schedule code, all now covered. The five modules were chosen by the assistant; the Heston and Merton pricers, the PDE solvers, calibration and the neural models are not in the catalogue. | assistant |
| Q-2 | Cross-machine replay | partial | E1 | `docs/REPLICATION_GUIDE.md`<br>`data_cache/MANIFEST.sha256.json` | Input hashes are enforced; output replay is exact on one machine only and the guide states the tolerance policy in words. No tolerance-based replay checker, and no second machine. | external |
| Q-3 | Security | partial | E2 | `docs/THREAT_MODEL.md`<br>`SECURITY.md`<br>`.github/workflows/security.yml`<br>`.github/workflows/release.yml` | Scanning, SBOM, a threat model, size and resource limits and an attestation step exist. No independent review; malformed-input fuzzing is limited to the existing sandbox tests. | external |
| Q-4 | Job resilience | partial | E2 | `tests/unit/test_job_artifacts.py`<br>`tests/unit/test_job_worker.py` | Disk-full and I/O-error injection into the artifact store (nothing half-written, no debris), plus existing cancel, timeout and parent-death tests. A worker crash mid-write of the job store is not injected. | assistant |
| Q-5 | API / desktop parity | partial | E2 | `tests/unit/test_surface_parity.py` | The direct runner, the job engine behind the web API and the desktop session give the same sealed result on two recipes. The HTTP layer itself and the CLI wrapper are not in the comparison. | assistant |
| Q-6 | Usability | needs external | E0 | `docs/REPLICATION_GUIDE.md` | Needs five people. The replication form asks for friction notes. | external |
| Q-7 | Research export | partial | E1 | `docs/EXPERIMENT_GUIDE.md` | Results export with sealed manifests; round-trip import and publication-ready plot formats are not verified here. | maintainer |
| Q-8 | Maintainability | partial | E1 | `docs/EXTENSION_POINTS.md`<br>`docs/release/RELEASE_RUNBOOK.md` | Extension points, compatibility and the release runbook are written down. The job store has no migrations (it refuses any other schema version); no complexity review. | maintainer |

## v1.0 roadmap milestones

| ID | Item | Status | Level | Evidence | What is missing | Who |
| --- | --- | --- | --- | --- | --- | --- |
| RM-0 | M0 / freeze | done | E2 | `docs/audit/BASELINE.md`<br>`docs/audit/register.json`<br>`docs/audit/REGISTER.md` | The audited commit, a source manifest, this register and the score rubric (with a recomputation test) are committed. | assistant |
| RM-1 | M1 / reliability | partial | E2 | `docs/data/data_qa_report.json`<br>`tests/unit/test_surface_parity.py` | Data QA, the data-use audit, resilience and parity tests exist; independent checks and cross-machine replay do not. | external |
| RM-2 | M2 / science | partial | E2 | `docs/CONFIRMATORY_PROTOCOL.md` | Everything up to the freeze is built; nothing has been preregistered or run on untouched data. | maintainer |
| RM-3 | M3 / math | partial | E2 | `tests/unit/test_numerical_verification.py` | Monte Carlo and grid-solver rates measured; strong convergence and dimension scaling are not. | assistant |
| RM-4 | M4 / desktop | partial | E2 | `.github/workflows/installer-smoke.yml`<br>`docs/SUPPORT_MATRIX.md` | Linux matrix and clean-install evidence exist; AppImage/DEB deliberately not built (declined, see L-01); no user task results. | maintainer |
| RM-5 | M5 / release | partial | E1 | `docs/release/VERIFYING.md`<br>`.github/workflows/release.yml`<br>`docs/release/RELEASE_RUNBOOK.md` | Attestation step, verification guide and runbook exist and the attestation ran on release 0.5.4 (all files verified); no independent security review. | maintainer |
| RM-6 | M6 / dissemination | partial | E1 | `CITATION.cff`<br>`docs/REPLICATION_GUIDE.md` | Citation metadata and the replication package exist; no archival DOI, no external reports, no paper submission. | maintainer |

## Risk register

| ID | Item | Status | Level | Evidence | What is missing | Who |
| --- | --- | --- | --- | --- | --- | --- |
| R-1 | Undetected temporal leakage (Critical) | needs external | E1 | `docs/confirmatory/DATA_USE_AUDIT.md` | Open. The audit found one real exposure (INFLATIONCAST already scored the 2023-2026 CPI) but is the assistant's, not independent. | external |
| R-2 | Post-hoc model selection (High) | partial | E2 | `docs/CONFIRMATORY_PROTOCOL.md` | Mitigation built (frozen pipelines, guard, locked data); active only after the freeze. | maintainer |
| R-3 | False equivalence claim (High) | partial | E2 | `src/prometheus/confirmatory/intervals.py`<br>`docs/confirmatory/power_note.json` | Margins and power notes exist; a statistics reviewer has not seen them. | external |
| R-4 | Weak generalization (High) | not started | E0 | none | One market, one country; E4 open. | maintainer |
| R-5 | Shared test/code blind spot (High) | partial | E2 | `tests/unit/test_confirmatory_e3.py`<br>`tests/unit/test_confirmatory_e2.py`<br>`tools/mutation_check.py` | Differential tests against the studies' own code and mutation checks (which found real gaps) exist; no external derivation. | external |
| R-6 | Linux installation failure (High) | partial | E2 | `.github/workflows/installer-smoke.yml` | Fresh-VM matrix runs on every installer change and weekly; it already found a Debian-12 validator error and a data-loss hazard. | maintainer |
| R-7 | Misinterpreted demo outputs (Medium) | done | E2 | `frontend/src/demo/demo.ts`<br>`frontend/src/demo/demo.test.ts` | A banner on every page and refusal of settings that were not recorded, tested against the real recording. | assistant |
| R-8 | Supply-chain compromise (High) | partial | E2 | `.github/workflows/security.yml`<br>`.github/workflows/release.yml`<br>`docs/release/VERIFYING.md` | Hash-locked dependencies, pinned actions, scanning, a secret scan and, from 0.5.4, verified build-provenance attestations. Anyone who can push a tag can still make a validly attested release; account security and review are the real protection. | maintainer |
| R-9 | Single-maintainer dependence (High) | partial | E1 | `CONTRIBUTING.md`<br>`docs/release/RELEASE_RUNBOOK.md`<br>`docs/REPLICATION_GUIDE.md` | A contributor guide, a release runbook and a replication guide exist. There is still one maintainer and no external reviewer. | external |
| R-10 | Scope creep (High) | partial | E1 | `docs/ROADMAP.md` | A written freeze policy and the audit's non-goals are in the roadmap; whether it holds is the maintainer's discipline. | maintainer |

## Scorecard (the reviewer's baseline)

Formula: `sum(weight * score) / sum(weight)` = **8.118**, recomputed from the table. The scores are the reviewer's baseline and are NOT changed here. Per the audit, re-score the 20 criteria from actual evidence after each milestone; no criterion moves toward 10 without E3 or E4 evidence for it, and nothing in this repository is E3 or E4 yet.

| Criterion | Weight | Score | What prevents 10 |
| --- | --- | --- | --- |
| Mathematical foundations | 7% | 9.3 | SDE, PDE, BSDE, pricing and risk models are documented; require explicit assumptions, derivations, convergence and validity domains. |
| Numerical correctness | 6% | 8.8 | Analytic and numerical cross-checks are reported; independently rederive edge cases and test error bounds. |
| Scientific novelty | 7% | 7.0 | Negative results and evidence discipline are valuable; novelty against prior literature is not established. |
| Research methodology | 7% | 8.0 | Multi-seed and ablation practices; retrospective hypothesis freeze limits confirmatory claims. |
| Statistical rigor | 6% | 7.5 | Bootstrap and proper scoring reported; dependence-aware inference, power, multiplicity and equivalence need explicit audits. |
| Economic validity | 5% | 7.5 | Real indicators and accounting framework; synthetic economy and calibration assumptions limit external validity. |
| Dataset quality | 5% | 7.5 | Verified snapshots; historical vintages, licensing and international harmonization need broader coverage. |
| Leakage prevention | 5% | 8.5 | GDP look-ahead corrected; independently audit every feature release timestamp and preprocessing step. |
| Benchmark quality | 5% | 8.0 | Strong negative-result culture; budget-match and use independent baselines per task. |
| Generalizability | 5% | 6.8 | Multiple datasets in some tasks, but shock-specific and small-sample findings require new holdouts. |
| Software architecture | 5% | 9.0 | Separated engine, job queue, web gateway and Qt UI; validate boundaries, migrations and extension contracts. |
| Code quality | 4% | 9.2 | Strict typing and lint reported; full code audit and complexity hotspot review not performed. |
| Automated testing | 5% | 9.3 | Large suite and mutation checks reported; test count is not coverage of independent failure modes. |
| Reproducibility | 5% | 9.0 | Pinned dependencies, hashes and replay; cross-machine floating-point variation requires tolerance policy. |
| Security architecture | 4% | 8.5 | Threat model, scanning, TLS and least privilege documented; external assessment and signing remain gates. |
| Documentation | 4% | 9.4 | Research limitations, PR ledger and guides; sync version-sensitive claims and verify onboarding. |
| Linux distribution | 4% | 8.0 | Source installer headless check reported; AppImage/DEB assets and independent graphical install not verified. |
| User experience | 3% | 8.0 | Labs, explorers, findings and history documented; evaluate task completion with new users. |
| Computational performance | 3% | 8.0 | Scaling comparisons reported; profile CPU/GPU, RAM, cancellation and regression budgets. |
| Independent validation | 5% | 5.5 | Single maintainer; external reproduction, review and usability evidence are the largest gap. |
