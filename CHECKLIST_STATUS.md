# Checklist status

This tracks real status against the blueprint's own checklist IDs
(`docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf`, section
14 — 374 items across 29 categories, all of which the document itself marks
`[ ] NOT VERIFIED`). Per the blueprint's own protocol: "To set [x], link an
immutable artifact (PR, commit, report, ...) and obtain appropriate review."
No independent review has happened here yet, so nothing below is marked
`[x]` — evidence is linked to a test, which is the strongest claim a single
contributor can honestly make before review.

Requirements without evidence notes remain unverified and in the full scope.
This file grows alongside the implementation and its actual validation.

## ECONOSIM-X final-project addendum (FP-01..FP-24)

Starting at PR-055, this repository also tracks against
`docs/PROMETHEUS_X_Final_Project_Integrated_Blueprint.md` ("PROMETHEUS-X",
version 1.1, 04 November 2026), a final-project-specific addendum layered
on top of the original 374-item blueprint above without replacing it. It
adds a ten-subsystem architecture (ECONOSIM-X, MACROCORE, RECESSIONNET,
INFLATIONCAST, CONTAGION-GNN, STOCHASTICA, VOLTERRA, DEEP HEDGING,
POLICYLAB-RL, TITAN) and its own 24-item acceptance checklist (FP-01..
FP-24). The combined project is referred to as **ECONOSIM** going
forward. FP-NN IDs use a 2-letter prefix, which the automated blueprint-
register extractor (`prometheus.evidence.requirements`, which only
matches 3-4 letter prefixes against the ORIGINAL PDF) does not and should
not pick up -- FP-NN status is tracked by hand in this section only, and
`docs/implementation/blueprint_register.json`'s counts remain exclusively
about the original 374-item register.

| ID | Status | Evidence |
|----|--------|----------|
| FP-01 | NOT VERIFIED | Title/hypotheses not yet formally frozen in a dedicated document; this file and `README.md` currently serve that role informally. |
| FP-02 | VERIFIED-BY-TEST (closed PR-060) | PR-055 built the schema mechanism only ("no REAL external dataset has been licensed or ingested yet"); PR-060 closes that gap for the three fields that generalize across sources: `data_ingestion.worldbank` ingests a REAL dataset (World Bank Open Data, CC-BY-4.0, confirmed live) with a real `raw_hash` (SHA256 of the actual fetched bytes) and a real `published_at` (the API's own `lastupdated` field), all flowing through `econosim.pit.MacroObservation` end to end. `vintage_at` specifically remains unpopulated for this one source -- World Bank's bulk indicator API has no true per-observation vintage concept the way ALFRED does, a source-specific limitation, not a gap in the schema itself (which has carried `vintage_at` since PR-055 and would populate it for a source that provides one). |
| FP-03 | VERIFIED-BY-TEST (PR-055) | `econosim.pit.build_feature_vector`/`require_eligible` raise `FutureDataError` (fail closed on the WHOLE request) rather than silently returning partial data, confirmed by `test_build_feature_vector_rejects_unavailable_features_instead_of_partial_data`. Builds on the pre-existing `PointInTimeStore.as_of`/`all_eligible_as_of` predicate (already tested since the original PR-003), now additionally gated on an `asof_eligible_at` internal-ingestion-lag field, not just source `published_at`. |
| FP-04 | VERIFIED-BY-TEST (PR-056) | `macrocore.baselines` implements Persistence, AR(p) (standing in for "ARIMA" -- see its module docstring for the deliberate scope cut against a full differenced/MA Box-Jenkins ARIMA) and VAR(p), all OLS-fit with closed-form Gaussian forecast intervals; `macrocore.evaluation`'s rolling-origin backtest harness runs all three reproducibly (fixed seed, deterministic OLS) through `econosim.pit`'s point-in-time store end to end, with MAE/RMSE/CRPS/coverage reported via `summarize_scores`. |
| FP-05 | NOT VERIFIED | MACROCORE (shared temporal encoder) does not exist. |
| FP-06 | NOT VERIFIED | RECESSIONNET does not exist. |
| FP-07 | NOT VERIFIED | INFLATIONCAST does not exist. |
| FP-08 | NOT VERIFIED | No shared-vs-independent encoder ablation; no encoder exists. |
| FP-09 | VERIFIED-BY-TEST (pre-existing, confirmed PR-057) | `tests/property/test_ledger_invariants.py::test_random_action_sequences_preserve_identities_and_total_equity` is a Hypothesis property test (100 generated examples, 1-40 randomized actions each, drawn from 9 action kinds: income/consume/wages/loan/repay/tax/transfer/gov_loan/gov_repay) that calls `check_integrity()` after EVERY action and asserts total equity equals exactly the sum of exogenous injections -- this is literally "transaction and stock-flow identities pass" under randomized sequences, not hand-picked examples, which is what the FP-09 wording asks for. |
| FP-10 | NOT VERIFIED | CONTAGION-GNN does not exist (the original blueprint's `titan.contagion` synthetic-bank-network module is a different, non-GNN primitive -- see RISK-11 above). |
| FP-11 | PARTIAL (narrowed PR-057) | GBM has `test_gbm.py::test_paths_are_always_positive`; Heston has `test_heston.py::test_variance_path_never_negative` and `test_price_path_never_negative_or_nan`. Jump-diffusion (`stochastica.jump_diffusion`) had NO explicit positivity/finiteness test before PR-057 -- only moment-matching (`test_simulator_with_zero_jump_intensity_matches_pure_gbm_moments`); PR-057 adds one (`test_jump_diffusion_paths_are_always_positive_and_finite`), closing that specific gap. "Numerical" diagnostics beyond positivity (e.g. a formal convergence-rate study) remain separately tracked at SDE-05 below. |
| FP-12 | VERIFIED-BY-TEST (closed PR-058) | Price benchmarks exist for all 5 pricers. Greeks now exist for Black-Scholes, American options (pre-existing), and -- new in PR-058 -- Heston, Merton, barrier and geometric-average Asian, each cross-checked against Black-Scholes' own independently-computed analytical Greeks in a degenerate or exact limit. The one remaining, explicitly scoped-out gap: arithmetic-average Asian Greeks are NOT implemented, because that variant's Monte Carlo pricer has no common-random-numbers machinery, so a naive bump-and-reprice would have unknown and likely unreliable precision -- `asian_greeks.py` raises rather than silently returning a noisy number. "Matches benchmark tolerances" is satisfied for every pricer that has Greeks at all; the Asian scope cut is disclosed, not hidden. |
| FP-13 | NOT VERIFIED | VOLTERRA-GEN (conditional scenario generator) does not exist. |
| FP-14 | VERIFIED-BY-TEST (pre-existing, confirmed PR-057) | `hedging.baseline.apply_no_trade_band` (the cost-aware threshold policy, HDG-03) is directly compared against `black_scholes_delta_hedge_ratios` (HDG-02) on the SAME underlying simulated paths, with HDG-03's own CHECKLIST_STATUS.md evidence note already stating it empirically cuts turnover/cost by roughly 30% -- a genuinely matched, cost-aware baseline comparison, not just two baselines existing independently. |
| FP-15 | NOT VERIFIED | POLICYLAB-RL does not exist. |
| FP-16 | NOT VERIFIED (corrected PR-057) | An earlier draft of this row claimed `titan.risk_metrics`/`titan.portfolio` "already report horizon/units/costs," which an audit found to be inaccurate: `historical_var`/`parametric_var`/`historical_expected_shortfall`/`max_drawdown` all return a bare `float` (horizon/alpha are INPUT parameters, never carried in an output report object); `VarCoverageResult`'s fields are `n_observations, n_exceptions, expected_exception_rate, observed_exception_rate, p_value` -- no horizon, units or cost; `StressTestReport`'s fields (`scenario_results, worst_case, value_at_risk_threshold, worst_case_exceeds_var`) carry no units/cost either. No TITAN output literally carries horizon + units + cost together, which is what this FP item and the original blueprint's own section-02 `RiskReport` integration contract both call for. Corrected from PARTIAL to NOT VERIFIED rather than left overstated. |
| FP-17 | NOT VERIFIED | No forecasting task exists yet to have train/validation/test splits. |
| FP-18 | NOT VERIFIED | No trained model exists yet to report seeds/CIs for. |
| FP-19 | NOT VERIFIED | No end-to-end replay trace spanning the new DL subsystems exists (the pre-existing `MacroTimeEngine`/`StepHooks` replay covers only the original five blocks). |
| FP-20 | PARTIAL (narrowed PR-057) | `RunManifest` (`experiments/manifest.py`) fields were, before PR-057: `run_id, created_at, seed, config, result_hash` -- a `code_hash`/`data_hash` could at most be embedded inside the opaque `config` mapping (not a named field), and there was NO `model_id` field at all (consistent with no trained model existing anywhere in this repository). PR-057 adds explicit optional `code_hash`, `data_hash` and `model_id` fields (all `str | None = None`, so every pre-existing caller is unaffected), exercised by a test with representative hash-shaped values -- but `model_id` is still never populated by any real trained model, since FP-05/06/07 (MACROCORE/RECESSIONNET/INFLATIONCAST) remain NOT VERIFIED. Mechanism now exists; still not exercised by a real model. |
| FP-21 | NOT VERIFIED | No dashboard exists. |
| FP-22 | NOT VERIFIED | No final paper exists yet. |
| FP-23 | VERIFIED-BY-TEST (pre-existing, reconfirmed PR-056) | `pytest -q` (1480 tests as of PR-056), `ruff check`, and `mypy --strict` all pass from a clean checkout, confirmed after every PR including this one. |
| FP-24 | Ongoing discipline, not a one-time check | This file and `README.md` are the running record that no module is declared complete on the strength of either blueprint document alone -- every row above states exactly what evidence (or absence of it) backs its status. |

Current FP score (updated PR-060): 7 fully VERIFIED-BY-TEST (FP-02 as of
PR-060, FP-03, FP-04, FP-09, FP-12 as of PR-058, FP-14, FP-23), 2 PARTIAL
(FP-11/FP-20, narrowed by PR-057's audit), 14 NOT VERIFIED (FP-16 moved
here from PARTIAL after an audit found no TITAN output actually carries
horizon+units+cost together), and FP-24 itself (which is a standing
discipline this file and README.md follow on every PR, not a single
check to complete once). This is a documentary snapshot,
not a completion percentage, matching the addendum's own "0/24 verified"
starting convention -- six of the ten named subsystems (MACROCORE,
RECESSIONNET, INFLATIONCAST, CONTAGION-GNN, VOLTERRA-GEN, POLICYLAB-RL)
do not exist in this repository yet; FP-04's classical baselines are the
reference point those subsystems' eventual learned models must beat
(section 09/E01), not a replacement for building them.

---

As of PR-060, table ID columns contain 128 distinct blueprint checklist IDs,
including partial entries and repeated IDs across slices. PR-049 (multi-
creditor insolvency waterfall) adds the first evidence anywhere in this
repository for LED-07, a previously-unevidenced ID (`write_off_loan`,
PR-043, is a single-creditor primitive and was never itself LED-07
evidence). PR-050 (factor-model covariance shrinkage target) strengthens
OPT-05/RISK-05/RISK-07, already evidenced since PR-024/027, rather than
adding a new ID. PR-051 (Heston characteristic-function pricer) adds the
first evidence anywhere in this repository for PRI-04 and for VAL-14
(partial), both previously unevidenced. PR-052 (Merton jump-diffusion)
adds the first evidence anywhere in this repository for SDE-08,
previously unevidenced; its pricer reuses already-evidenced PRI-01/PRI-04,
VAL-14 and PRI-03. PR-053 (barrier options with discretization correction)
adds the first evidence anywhere in this repository for PRI-08, previously
unevidenced; it reuses already-evidenced PRI-01/PRI-03 (parity) and VAL-14.
PR-054 (Asian options with a Kemna-Vorst control variate) adds the first
evidence anywhere in this repository for PRI-09, previously unevidenced;
it reuses already-evidenced PRI-01/PRI-03/PRI-06 and VAL-14. PR-055
(point-in-time schema/fixture extension) strengthens the already-
evidenced DAT-07 (partial) rather than adding a new original-blueprint
ID; its new coverage is tracked under the ECONOSIM-X addendum section
above (FP-02/FP-03), not in this count. PR-056 (classical forecasting
baselines) adds no original-blueprint ID either -- its FP-04 coverage is
tracked in the addendum section only; an earlier draft briefly and
incorrectly tagged VAL-01/VAL-03/VAL-14 to it (none of which actually
match AR/VAR forecasting or CRPS scoring), caught via the register's
count jumping from 124 to 126 unexpectedly and corrected before being
committed to anywhere permanent -- see PR-056's own section below for
the full account. PR-057 adds the first evidence anywhere in this
repository for SDE-05 and VAL-03, both previously unevidenced -- this
time a genuine match (a Heston weak-convergence study IS a "convergence
check for a stochastic integrator"), legitimately bringing the count
from 124 to 126, confirmed by regenerating the register and checking the
jump matched expectations exactly (2 new IDs, not more) before trusting
it. PR-058 (Greeks for Heston/Merton/barrier/geometric-Asian) adds no
new original-blueprint ID -- it strengthens the already-evidenced
PRI-07 and VAL-05, confirmed by regenerating the register and checking
the count stayed at exactly 126. PR-059 (portfolio-level Greeks
aggregation) adds the first evidence anywhere in this repository for
PRI-10, previously unevidenced, bringing the count to 127. PR-060 (the
first real, live-verified external data connector) strengthens the
already-evidenced DAT-07 and adds the first evidence anywhere in this
repository for DAT-08 (narrowly: the specific "no forward-fill... without
justification" clause, via skipping rather than fabricating missing
World Bank values -- the broader cross-source revision-policy half of
DAT-08 is not covered), bringing the count to 128. Deliberately NOT
claimed despite being adjacent: DAT-01 (a single connector's docstring is
not an approved, organization-wide source catalog), DAT-02 (that ID is
specifically FRED-MD/QD, a different source entirely from World Bank),
DAT-06/DAT-12/DAT-13/DAT-14 (no storage layers, no normalized/feature
hashing, no release gating, no dataset card exist) -- a direct
application of the lesson from the VAL-01/03/14 misattempt two PRs ago:
proximity to a requirement's SUBJECT MATTER is not the same as satisfying
its literal text.
Historical counts:
PR-020 corrected the count to 69 by excluding the separate R-03 risk-register
mitigation; PR-021 added partial HDG-10 evidence, bringing it to 70. No count is a completion percentage
or review acceptance count. PR-022 (risk-neutral calibration, not part of
PR-015..021's local-validation sequence above) adds the first evidence for
PRI-05, a previously-unevidenced ID. PR-023 (portfolio optimization) adds
the first evidence anywhere in this repository for OPT-01, OPT-02, OPT-03,
OPT-04 and OPT-09 -- the entire OPT-* category had zero evidenced IDs
before it. PR-024 (covariance shrinkage) adds the first evidence for
RISK-05 and strengthens OPT-05, connecting directly to PR-023's portfolio
optimizer. PR-025 (multi-period rebalancing simulator) adds the first
evidence for OPT-07 and strengthens OPT-10, closing the loop across time
between PR-023's optimizer and PR-024's shrinkage estimator. PR-026 (central-
bank ledger-backed balance sheet) extends ECO-05 and ECO-09 with a genuine
reserve-issuance/OMO/interbank-settlement agent, previously explicitly
listed as not done. PR-027 (factor exposure model) adds the first evidence
anywhere in this repository for RISK-07. PR-028 wires PR-026's
`CentralBankLedger` into the real `StepHooks` event order for the first
time and adds `Economy.add_central_bank_ledger`, closing PR-026's own
"not wired into Economy/StepHooks" admission. PR-029 wraps PR-028's
scenario in a CLI/evidence-export runner registered with
`orchestration.replay`, closing PR-028's own remaining admission. PR-030
(stress testing) adds the first evidence anywhere in this repository for
RISK-10 and OPT-11, and partial evidence for OPT-12. PR-031 (interbank
network contagion) adds the first evidence anywhere in this repository
for RISK-11, and strengthens the partial RISK-12 evidence. PR-032 connects
PR-031's contagion analysis to live `econosim` ledger state for the first
time, closing PR-031's own "no connection to the ledger" admission. PR-033
adds a genuine direct bank-to-bank lending instrument, closing PR-032's
own "no direct bank-to-bank lending" admission. PR-034 wires that
instrument plus a periodic live systemic-risk check into PR-028's
`StepHooks` scenario, extending RISK-11 to continuous monitoring inside a
running simulation rather than an offline-only analysis. PR-035 adds the
first position book anywhere in this repository, with the first evidence
for RISK-01 and RISK-13. PR-036 makes PR-034's contagion check ACT on a
detected default via a one-way circuit breaker, rather than only
recording it, closing PR-034's own remaining admission. PR-037 adds
forward contracts as a second instrument type, generalizing PR-035's
position book beyond options. PR-038 adds American options, priced by a
binomial tree -- the first non-closed-form pricing method in this
repository -- cross-checked against Black-Scholes convergence and two
classical early-exercise theorems. PR-039 wires American options into
the position book (PR-035/037) as a third instrument type, closing
PR-038's own remaining admission. PR-040 adds Greeks for American
options, catching and fixing a genuine numerical pitfall (naive
spot-bumped gamma on a binomial tree) before evidencing the feature as
done. PR-041 optionally unifies `CentralBankLedger` with the standalone
rate wrapper into one object, without retiring or breaking either
existing class. PR-042 migrates `econosim.monetary_operations` to that
unified constructor, closing PR-041's own deferred remaining admission.
PR-043 adds interest accrual (LED-05) and single-creditor loan write-off
(LED-06) to `Bank`, additive to the already-committed `originate_loan`/
`receive_repayment` pair.

## Evidenced today (PR-001 + PR-002)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| GOV-01 (partial) | mission, personas, non-goals published | README.md |
| ECO-01 | typed economic state, immutable transitions | `core.ledger.EconomicState` is a frozen dataclass; `tests/unit/test_ledger.py::test_journal_is_append_only_and_postings_immutable` |
| ECO-02 | household budget feasibility | `tests/unit/test_agents.py::test_consume_more_than_cash_balance_raises_and_does_not_mutate` |
| ECO-03 | firm deposits, output revenue recognition | `tests/unit/test_agents.py::test_firm_pays_wages`, `test_household_receive_income_and_consume` |
| ECO-04 | bank loans/deposits/equity, double-entry | `tests/unit/test_agents.py::test_bank_capitalize_then_originate_loan` |
| ECO-09 | loan underwriting / bank capital limit | `tests/unit/test_agents.py::test_loan_origination_blocked_beyond_leverage_cap` |
| ECO-12 (partial) | deterministic config -> equivalent state/journal hash | `tests/unit/test_ledger.py::test_state_hash_is_deterministic_for_identical_histories`; only covered for the ledger primitive, not a full agent-config -> simulation replay |
| ECO-16 | fail-closed halt on broken accounting identity | `tests/unit/test_ledger.py::test_check_identities_detects_bypassed_mutation`; enforced structurally by `Ledger.post()`'s precondition check, not just detected after the fact |
| LED-01 | every transaction is balanced journal entries | `core.ledger.Ledger.post()`; `tests/unit/test_ledger.py::test_globally_imbalanced_transaction_rejected`, `test_cross_sector_transaction_with_missing_counterpart_rejected` |
| LED-02 | deterministic integer minor units, no float drift | `core.money.Money` rejects non-int/bool input; `tests/unit/test_money.py::test_float_rejected_no_cent_drift` |
| LED-06 (partial) | loan repayment reduces receivable/payable/deposits | `tests/unit/test_agents.py::test_loan_repayment_reduces_debt_and_bank_assets`; no write-off/recovery path |
| LED-12 | global conservation under randomized transaction sequences | `tests/property/test_ledger_invariants.py::test_random_action_sequences_preserve_identities_and_total_equity` (Hypothesis, 100 random examples per run) |
| VAL-07 | economic conservation under randomized transitions | same property test as LED-12 |
| VAL-09 (partial) | deterministic CPU test mode, reference hashes | `EconomicState.state_hash()`; not yet wired to a pinned CI reference-hash fixture |

## Evidenced today (PR-003)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| LED-11 (partial) | time-zone/holiday/business-day calendars | `core.calendar.BusinessDayCalendar`; `tests/unit/test_calendar.py`. Time-zone handling itself (not just business-day stepping) is explicitly out of scope. |
| EXP-03 | random seed hierarchy across agent/market/training, order-independent replay | `core.seeds.SeedHierarchy`; `tests/unit/test_seeds.py::test_stream_identity_is_independent_of_request_order` |
| ECO-13 | no hidden future variables in policy feature vector | `econosim.pit.PointInTimeStore.as_of` / `all_eligible_as_of` only ever expose `published_at <= t`; `tests/unit/test_pit.py`, `tests/unit/test_time_engine.py::test_point_in_time_data_is_not_visible_before_its_publication_step` |
| ECO-14 | shocks to productivity/prices/policy, impulse-response reproducibility | `econosim.shocks.ShockGenerator`; `tests/unit/test_shocks.py::test_same_seed_reproduces_identical_shocks` |
| DAT-07 (partial) | observation/publication timestamp tracking, point-in-time inclusion predicate | `econosim.pit.MacroObservation`/`PointInTimeStore`; full DAT ingestion (FRED-MD/QD, ALFRED, hashing) is not implemented |
| R-03 mitigation (risk register) | release-time data view prevents lookahead leakage | same point-in-time tests as above, exercised across a multi-step replay in `test_time_engine.py` |

## Evidenced today (PR-004)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| SDE-01 | GBM path generator, empirical mean/variance match theory within CI | `stochastica.gbm.simulate_gbm_paths`; `tests/unit/test_gbm.py::test_terminal_distribution_matches_theory_within_confidence_interval` (standard-error-based interval, not a magic tolerance) |
| SDE-02 | correlated multivariate asset simulator, PSD checks pass | `stochastica.gbm.simulate_correlated_gbm_paths` + `stochastica.correlated`; `tests/unit/test_gbm.py::test_correlated_gbm_recovers_approximate_asset_correlation` |
| SDE-03 | Heston price/variance dynamics, nonnegative variance | `stochastica.heston.simulate_heston_paths`; `tests/unit/test_heston.py::test_variance_path_never_negative`, `test_terminal_variance_mean_matches_exact_cir_moment` (checked against the exact continuous-time CIR first moment) |
| SDE-04 | variance discretization policy documented, convergence/positivity tests | full-truncation Euler, documented in `heston.py`'s module docstring; `tests/unit/test_heston.py::test_low_feller_ratio_hits_the_zero_floor_far_more_often` (bias/clamping diagnostic tied to the Feller ratio) |
| VAL-04 | covariance symmetry/PSD validation, adversarial matrices rejected or repaired with warning | `stochastica.correlated.validate_and_repair_covariance`; `tests/unit/test_correlated.py` (asymmetric and materially non-PSD matrices rejected; a tiny-negative-eigenvalue matrix is repaired with a warning) |
| VAL-06 (partial) | Heston variance scheme across parameter extremes, no hidden negative values | `tests/unit/test_heston.py::test_variance_path_never_negative` at a low-Feller, high-vol-of-vol parameter set; "silent clamps" are not hidden -- they are the documented, tested mechanism (full truncation), not a bug being masked |

Not covered by PR-004: SDE-05 formal time-step convergence-rate estimation (only an informal Feller-ratio bias diagnostic exists), SDE-06..SDE-12 (regime switching, jumps, historical calibration, identifiability diagnostics, extreme-input fuzzing), Tier 2-4 of the model ladder (neural SDEs, macro-conditioned models, stress-robust policies).

## Evidenced today (PR-005)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| PRI-01 | versioned instrument/payoff specifications | `volterra.instruments.EuropeanOption`; boundary tests in `tests/unit/test_black_scholes.py::test_option_rejects_invalid_fields` |
| PRI-02 | Black-Scholes European call/put, analytical reference fixtures | `volterra.black_scholes.black_scholes_price`; `tests/unit/test_black_scholes.py::test_matches_known_textbook_reference_value` |
| PRI-03 | put-call parity and bounds verification | `volterra.black_scholes.put_call_parity_residual`; `test_put_call_parity_holds_to_floating_point_precision`, `test_call_price_respects_lower_arbitrage_bound`, monotonicity-in-spot/strike tests |
| PRI-06 | Monte Carlo pricer with standard errors | `volterra.monte_carlo.monte_carlo_price_vanilla`; `tests/unit/test_monte_carlo.py` |
| PRI-07 | Delta/Gamma/Vega with method tagging, analytical vs. independent-method comparison | `volterra.black_scholes.black_scholes_greeks` vs `volterra.greeks_fd.finite_difference_greeks`; `tests/unit/test_greeks_fd.py` (parametrized across ITM/ATM/OTM, call and put) -- see caveat below |
| PRI-12 | fail closed on invalid parameters | `MarketSnapshot`/`EuropeanOption` `__post_init__` validation (non-positive spot/vol/strike/maturity rejected) |
| PRI-13 | numerical uncertainty required with every non-closed-form price | `MonteCarloResult` always carries `standard_error` and `n_paths`; there is no code path that returns a Monte Carlo price without them |
| SDE-09 | explicit P/Q measure tagging on every pricing call | `volterra.market.MarketSnapshot` raises in `__post_init__` unless `measure == "Q"`; the Monte Carlo pricer always simulates with drift `r - q`, never a physical-measure `mu` |
| VAL-05 (caveat) | AD vs. finite-difference Greek checks | Implemented as *analytical-formula* vs. *finite-difference*, not automatic differentiation vs. finite-difference as the ID's literal text says; both differentiate the same `black_scholes_price` function, so this does not independently verify the price formula itself, only the Greeks formulas derived from it |

Not covered by PR-005: risk-neutral calibration (PRI-05, closed later by PR-022), barrier/Asian options (PRI-08/09), portfolio-level Greeks aggregation (PRI-10), volatility-surface arbitrage checks (PRI-11), and all of PDE-01..PDE-12 (PINN/deep-BSDE solvers). Heston/Fourier pricing (PRI-04) remained open until PR-051, barrier options (PRI-08) until PR-053, and Asian options (PRI-09) until PR-054, below. Portfolio-level Greeks aggregation (PRI-10) remains open.

## Evidenced today (PR-006)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| RISK-02 | historical VaR with definitional metadata | `titan.risk_metrics.historical_var`; declares its `alpha`/`interpolation` convention explicitly, no hidden default assumption |
| RISK-03 | parametric VaR under explicit distribution | `titan.risk_metrics.parametric_var` (Gaussian); `tests/unit/test_risk_metrics.py::test_parametric_var_known_value` against a literature reference value |
| RISK-04 | Expected Shortfall, tie/atom-safe estimator, discrete and continuous reference examples | `titan.risk_metrics.historical_expected_shortfall`; hand-worked discrete examples with and without ties (`test_expected_shortfall_discrete_worked_example_with_ties` is the one that would break under naive distinct-value tie handling), plus a continuous Gaussian reference check within 1% |
| RISK-06 | historical drawdown | `titan.risk_metrics.max_drawdown`; hand-worked example |
| RISK-08 | VaR exception and coverage tests, expected frequency and CI | `titan.risk_metrics.var_exception_coverage_test` (exact two-sided binomial test); tests confirm a correctly-calibrated model is not flagged and a badly miscalibrated one is |

Not covered by PR-006: RISK-09 (ES backtesting/proper scoring rules beyond the coverage test above). RISK-01 (position/snapshot linkage), RISK-05 (covariance/shrinkage estimators), RISK-07 (factor exposure), RISK-10 (stress scenarios), RISK-11 (network contagion), RISK-12 (concentration, partial), RISK-13 (stale-snapshot rejection) and OPT-01..12 (portfolio optimization) were not covered at the time of PR-006; see PR-023/PR-024/PR-027/PR-030/PR-031/PR-035 below for the evidence added later.

## Evidenced today (PR-007)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| HDG-01 | portfolio wealth/terminal loss with cash financing, self-financing assumption documented | `hedging.simulate.simulate_self_financing_hedge`; `tests/unit/test_hedging_simulate.py::test_self_financing_identity_matches_manual_recomputation` and the exact closed-form `test_zero_hedge_ratios_reduce_to_a_naked_short_option_position` |
| HDG-02 | Black-Scholes model-consistent delta hedge, convergence under zero frictions | `hedging.baseline.black_scholes_delta_hedge_ratios`; `tests/unit/test_hedging_simulate.py::test_finer_discretization_reduces_hedging_error_under_zero_cost` (std of terminal loss strictly decreases at 10/50/250 steps) |
| HDG-03 | cost-aware no-trade/threshold hedge vs. delta hedge | `hedging.baseline.apply_no_trade_band`; `test_no_trade_band_reduces_turnover`; empirically cuts turnover/cost by roughly 30% at a 0.1 band width in development |
| HDG-04 | MLP hedging policy, bounded actions | `hedging.deep_hedge.HedgePolicyMLP` (tanh-bounded to [-1, 1]); `tests/unit/test_deep_hedge.py::test_generated_ratios_are_bounded_by_tanh_squashing` |
| HDG-05 | causal observations, no future path information | hedge ratios at step t are built only from price_paths[:, t] and prior holdings; `tests/unit/test_hedging_baseline.py::test_delta_hedge_ratios_are_causal` (mutating only the terminal price leaves every earlier ratio unchanged) |
| HDG-06 | transaction costs, cost ledger reconciles to holdings/cash changes | same self-financing simulator as HDG-01; the manual-recomputation test above is exactly this reconciliation |
| HDG-08 | CVaR objective with correct loss definition | `hedging.deep_hedge._differentiable_cvar`, the same quantile-integral estimator as `titan.risk_metrics.historical_expected_shortfall`, reimplemented differentiably |
| HDG-09 | detached test evaluation | all `test_deep_hedge.py` evaluation happens on a freshly simulated test-seed path set, never the training paths |
| HDG-13 (partial) | reward-hacking / unfair-baseline checks | baseline and learned policies are evaluated through the identical `simulate_self_financing_hedge` function with identical cost rate and price paths -- structurally, not just by convention |
| EXP-06 | untrained/random-policy negative control | `tests/unit/test_deep_hedge.py::test_trained_policy_vastly_outperforms_untrained_negative_control` (~10x CVaR gap observed in development; test asserts a conservative 2x) |
| EXP-03 (partial) | deterministic training given a fixed seed | `tests/unit/test_deep_hedge.py::test_training_is_deterministic_given_a_fixed_seed` (identical objective history across two independent calls) |

Deliberately not claimed: that the trained policy beats the delta baseline. It did, slightly, on one configuration explored during development -- but the blueprint's own central hypothesis (section 01) is explicit that such a result "can be positive, negative, or inconclusive; no improvement is assumed," so no test asserts it, and none should until a pre-registered comparison (EXP-01, not yet implemented) is run.

Not covered by PR-007: HDG-07 (leverage/concentration/position constraints beyond the tanh bound), HDG-10 (policy risk diagnostics like gradient norms/action saturation), HDG-11 (out-of-family stress evaluation), HDG-12 (formal paired-significance P&L/CVaR/cost/turnover reporting), HDG-14 (RL agents), and GRU/LSTM or actor-critic/robust policy families from section 07's table.

## Evidenced today (PR-008)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| EXP-01 | pre-register primary endpoint and baseline comparison | `experiments.hedge_benchmark.PRIMARY_ENDPOINT` is a module-level constant fixed before any result is examined, not chosen post hoc |
| EXP-02 (partial) | factorial economy/market/hedge matrix | only the hedge axis is varied (delta vs. MLP); explicitly documented as a partial slice, not the full 2x2x2, in both the module docstring and every report's `limitations` tuple |
| EXP-03 (partial) | seed hierarchy, replay reconstructs results | each test seed independently reseeds path simulation and bootstrap resampling; `tests/unit/test_hedge_benchmark.py::test_result_hash_is_reproducible_across_independent_runs` |
| EXP-06 | untrained/random-policy negative control | reused from PR-007 (`test_deep_hedge.py`) |
| EXP-07 | paired confidence intervals respecting dependence | `experiments.bootstrap.paired_bootstrap_difference`; `tests/unit/test_bootstrap.py::test_paired_constant_shift_gives_a_degenerate_ci_at_the_exact_shift` demonstrates the pairing is load-bearing (a planted constant per-path difference collapses to an exact-point CI, which an unpaired bootstrap would not do) |
| EXP-10 (partial) | effect size and economic significance jointly | each `SeedResult` carries both the raw CVaR values and the bootstrap point estimate/CI, not just a p-value-style verdict |
| EXP-13 | no results excluded without transparent reason | `run_hedge_benchmark` always returns one `SeedResult` per requested seed; there is no filtering/selection step |
| AUD-01/02 (partial) | immutable run ID, reproducible result hash | `experiments.manifest.RunManifest`; result_hash is a canonical sorted-key JSON hash of the full per-seed payload, reproducible given the same seeds/config, while `run_id`/`created_at` are explicitly documented as *not* part of that reproducibility claim |

The benchmark's actual finding in development (not asserted by any test, since it is a result, not an infrastructure property): at the one configuration explored, the trained policy's and delta baseline's CVaR were statistically indistinguishable (every seed's bootstrap CI included zero) -- an inconclusive result, which is itself one of the three outcomes the blueprint's central hypothesis explicitly allows for.

Not covered by PR-008: EXP-04 (immutable split IDs/holdout manifest as a first-class artifact), EXP-05 (leakage negative control), EXP-08/09 (multiple-testing correction, block bootstrap for serial dependence -- paths here are i.i.d. terminal outcomes, not an overlapping-horizon series), EXP-11 (formal compute-cost benchmarking), EXP-12 (OOD/distribution-shift evaluation), EXP-14 (independent reviewer rerun).

## Evidenced today (PR-009)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| ECO-05 | central bank policy-rate rule baseline, known reaction-function scenarios reproduce coefficients | `econosim.policy_rate.PolicyRateRule`; `tests/unit/test_policy_rate.py::test_matches_exact_discrete_ou_closed_form_with_zero_shocks` (exact match to the closed-form discrete OU recursion, not just "close") |
| ECO-14 (extended) | shocks to monetary policy, impulse-response fixture reproduces expected sign/range | `test_policy_rate_shock_adds_exactly_its_magnitude_before_next_reversion` -- exact, not just sign/range |
| SDE-03 Tier 3 (partial, non-neural) | macro-conditioned market dynamics, no leakage from future releases | `econosim.macro_market_link.simulate_policy_rate_conditioned_market` + `stochastica.gbm.simulate_piecewise_drift_gbm_paths`; `tests/unit/test_piecewise_gbm.py::test_later_drift_cannot_affect_earlier_simulated_prices` and `test_macro_market_link.py::test_no_lookahead_from_future_policy_shocks` (bit-identical path prefixes despite a wildly different/later tail) |
| SDE-01-style reference check (extended to piecewise drift) | empirical mean/variance match theory within CI | `stochastica.gbm.piecewise_gbm_terminal_moments` (exact closed form for a piecewise-constant-drift GBM, reduces exactly to the constant-drift formula when the path is flat); `tests/unit/test_piecewise_gbm.py::test_terminal_distribution_matches_piecewise_theory_within_ci` |
| Full-chain integration | seeded shocks -> policy rate -> macro-conditioned market, end to end | `tests/unit/test_macro_market_link.py::test_integrates_with_the_seeded_shock_generator_from_pr003` and `test_terminal_distribution_matches_theory_for_a_policy_tightening_scenario` |

Explicitly labeled, not overclaimed: this is a deterministic, rule-based (non-neural) v0 of STOCHASTICA's Tier 3. "Macro conditioned... Neural SDE with macroeconomic state" literally calls for a *neural* drift/diffusion network; what exists here is a hand-specified piecewise-constant mapping from policy rate to drift. The no-lookahead property Tier 3 requires is implemented and tested; the "improvement against Tier 1" comparison Tier 3 also calls for is not attempted (that would need a pre-registered benchmark in the style of PR-008, which has not been run for this).

Not covered by PR-009: inflation/output-gap state or a full Taylor rule (the policy rate here only reacts to injected shocks plus mean reversion, not to any other macro variable), publication-lag-aware macro conditioning (the policy rate here is used immediately, not filtered through PointInTimeStore's as_of predicate), and wiring this into the Economy/MacroTimeEngine's own step loop (it is called as a standalone function, like every other subsystem so far).

## Evidenced today (PR-010)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| MLO-09 | model cards for intended use and limitations, CIs/failure modes/risk owner | `evidence.model_card.ModelCard`, structurally validated (cannot construct with a missing required section); `evidence.repository_status.build_deep_hedge_model_card` cards the actual PR-007 MLP policy with real, specific failure modes, not placeholder text |
| DOC-06 | model card template and validation documentation | same `ModelCard` class, enforced at construction rather than documented as a convention to remember |
| AUD-08 | simulation-vs-empirical disclaimer in exports, machine-readable source tag | `evidence.export.SIMULATION_DISCLAIMER` / `SOURCE_TAG`; `build_evidence_bundle` has no code path that omits either |
| AUD-11 | one-command gate evidence bundle with manifest and reviewers | `evidence.export.build_evidence_bundle` / `export_evidence_bundle`; `evidence/gate_report_r0.json` in this repository is a real, generated (not hand-written) instance |
| LCH-12 / section 19's gate decision form | signed GO/NO-GO record referencing every required gate and waiver | `evidence.gate_report.GateDecisionForm`: constructing one with `decision="GO"` or `"CONDITIONAL"` *without* naming `scientific_approval`, `security_ops_approval`, and a `sunset_date` raises -- there is no code path that produces an unsigned GO record |
| Section 19's actual verdict, reproduced in code | `evidence.repository_status.current_repository_gate_report()` returns `decision="NO-GO"`, matching the blueprint's own section 19 verdict, generated from this repository's real state rather than copied from the PDF |

`evidence/gate_report_r0.json` is committed to this repository as a real artifact, not a test fixture -- regenerate it with `python -c "from prometheus.evidence.repository_status import current_repository_gate_report; from prometheus.evidence.export import build_evidence_bundle, export_evidence_bundle; from pathlib import Path; export_evidence_bundle(build_evidence_bundle(None, [], current_repository_gate_report()), Path('evidence/gate_report_r0.json'))"` whenever the repository's scope or open findings change.

Not covered by PR-010: AUD-01..07/09/10/12 (per-run immutable IDs wired into every subsystem's output, access-control logging, versioned figures/tables), MGR-01..14 (none of this has had independent review, by construction -- that's the point, not a gap to silently close), CMP-01..12 (no regulatory/standards mapping attempted).

## Evidenced today (PR-011: orchestrated end-to-end demonstration run)

Beyond Appendix C's ten starter PRs: section 16's "Minimum v0.1
demonstration script" is implemented and tested, closing the "nothing is
wired to anything else" gap every prior PR's status table called out.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| Section 16's demonstration script, literally | economy -> shock -> GBM/Heston -> pricing -> hedge comparison -> P&L/CVaR -> evidence export, one command | `orchestration.demo_run.run_demo`; `tests/unit/test_demo_run.py::test_all_report_fields_are_populated_on_a_valid_run` |
| "...the run must be marked invalid rather than silently published" | invariant / valuation-tolerance / data-timing checks | all three implemented as named categories in `invalid_reasons`; `test_corrupted_ledger_is_caught_via_injected_economy` and `test_valuation_tolerance_check_can_actually_fail` both force a genuine failure (not just confirm the happy path), and the report is still fully populated up to the point of failure rather than crashing |
| AUD-01/02 (extended) | immutable run ID, reproducible result hash, for an integration run rather than a single subsystem | `test_result_hash_reproducible_given_identical_config` |
| Appendix B SC-01 | "Unanticipated +200bp policy-rate shock" scenario, named outputs | `DemoRunConfig.policy_shock_bps` defaults to exactly this scenario; `test_policy_rate_path_length_and_known_shock` confirms the jump in the realized rate path matches the configured magnitude to `1e-9` |
| AUD-08 (reused) | disclaimer and source tag on export | `test_evidence_bundle_carries_disclaimer_and_is_tagged_no_go` |

This closes the single most-repeated limitation across PR-003 through PR-010's status entries ("each subsystem is still called standalone"). It does not mean the subsystems are wired together *generally* -- `run_demo` is one specific, hard-coded pipeline for one scenario and one option, not a general orchestration engine or scheduler. (Update, PR-014: `MacroTimeEngine.advance_step()` itself now has real, working extension points for section 02's steps 3-7 via `econosim.step_hooks.StepHooks` -- see that section below. `run_demo` was not refactored to use them; the two remain separate, non-overlapping pieces of evidence.)

10 new tests (238 total), ruff/mypy --strict clean, 97%/98% coverage, stable across repeated runs (~15s total suite, ~1s per demo run).

## Evidenced today (PR-012: government and central-bank agents)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| ECO-06 | government taxes, transfers and expenditures; sectoral flows reconcile to counterpart accounts | `econosim.agents.Government.collect_tax` / `pay_transfer`; `tests/unit/test_government.py`; extended into the PR-002 Hypothesis property test (`tests/property/test_ledger_invariants.py`) so random tax/transfer/bond sequences are now part of the same conservation proof, not a separately-asserted claim |
| ECO-05 (extended) | central bank policy-rate rule baseline, as a stateful agent | `econosim.policy_rate.CentralBank`; `tests/unit/test_central_bank.py::test_step_matches_the_same_closed_form_as_the_free_function` -- the agent wrapper is proven to be behaviorally identical to the pure function it wraps, not a parallel reimplementation that could drift |
| ECO-09 (extended) | bank capital/leverage limits apply uniformly across borrower types | `econosim.agents.Borrower` protocol; `Bank.originate_loan`/`receive_repayment` now take any `Borrower`, not `Household` specifically; `tests/unit/test_government.py::test_government_and_household_borrowing_share_the_same_leverage_cap` and the full `tests/unit/test_borrower_protocol.py` (parametrized over household and government, same assertions, same code path) |

This is a genuine generalization, not a copy-paste: `Government.issue_bonds`/`repay_bond` call `Bank.originate_loan`/`receive_repayment` directly, and `Household.repay_loan` was refactored to delegate to the same `Bank.receive_repayment` it always should have (previously it duplicated that logic inline) -- there is exactly one implementation of loan/bond accounting in this repository, exercised by both agent types.

## Evidenced today (PR-013: labor and goods-market clearing)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| ECO-07 | goods-market price and quantity clearing, residuals tracked with documented tolerance | `econosim.market_clearing.clear_quantity_market` / `apply_goods_clearing_to_ledger`; `ClearingResult.clearing_residual` is always reported (signed excess demand), never silently discarded; `tests/unit/test_market_clearing.py::test_goods_clearing_charges_realized_not_desired_quantity` |
| ECO-08 | labor supply, demand and rationing, no double counting of hours or paid wages | `apply_labor_clearing_to_ledger`; `test_labor_clearing_pays_realized_not_desired_hours`; the no-double-counting property is proven structurally for arbitrary buyer/seller mixes in `test_no_double_counting_sums_match_realized_total` (3 parametrized cases, oversupply and overdemand), not just asserted for one example |

A deliberate bug was caught before any test ran: the first draft of `apply_labor_clearing_to_ledger` / `apply_goods_clearing_to_ledger` had buyer/sell semantics exactly swapped (households are *sellers* of labor but *buyers* of goods), caught by an exploratory scratch run, not by a test -- a reminder that "wrote a test that passed" and "the code is correct" are not the same claim until the test actually exercises the path that was wrong.

## Evidenced today (PR-014: generalized step-hooks orchestration)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| Section 02's full event order, steps 1-8 | release -> shocks -> actions -> clear/settle -> financial step -> value/hedge -> portfolio risk -> commit, as reusable engine behavior, not a one-off script | `econosim.step_hooks.StepHooks` + `MacroTimeEngine.advance_step()`; `tests/unit/test_time_engine_hooks.py::test_full_hook_wiring_against_real_subsystems` wires all five slots to the real `market_clearing`, `stochastica.gbm`, `volterra.black_scholes` and `titan.risk_metrics` modules -- not mocks -- across 3 real steps |
| Causal ordering of hook inputs | each hook only ever sees a `StepContext` built from already-known data | `test_hooks_receive_the_same_context_fields_advance_step_reports`; `test_hook_results_thread_into_the_next_hook` proves the threading order (actions -> settlement -> financial_step -> valuation -> risk) matches section 02's numbering exactly |
| AUD-02 (extended) | state hash reflects everything that happened in a step | `test_state_hash_reflects_ledger_mutations_made_by_hooks`: a hook that posts a ledger transaction is proven to change `state_hash`, confirming the snapshot is taken after steps 3-7 run, not before |

This directly closes the "called standalone" caveat repeated in every status update since PR-003: `MacroTimeEngine.advance_step()` now has real, working extension points for every step section 02 describes, exercised end to end against four different subsystems in one test. It does **not** ship an opinion about what those steps should compute for any given scenario -- `demo_run.py` (PR-011) remains the one concrete example of wiring choices for one scenario; `StepHooks` is the mechanism other scenarios would use, not a second copy of PR-011's pipeline.

Without `hooks`, `MacroTimeEngine` behaves exactly as it did in PR-003 -- `test_no_hooks_leaves_all_new_fields_none` plus every original PR-003 test still passes unmodified, confirming this was a strictly additive change.

## Evidenced locally (PR-015: monthly reference scenario and financing correction)

The packaged `orchestration.multi_step_run.run_multi_step_simulation`
scenario now exercises all five `StepHooks` every month, not only in a
test. `python -m prometheus.orchestration.multi_step_run --output
evidence/my_monthly_run.json` runs and exports it. Configuration validation
rejects non-finite parameters, invalid counts and maturity/month mismatches
before training. This slice is local work pending commit and review.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| HDG-01 (corrected/extended) | self-financing cash reflects the interval after each trade | `test_hedging_simulate.py::test_one_period_trade_is_financed_until_maturity` uses an independent borrowed-cash closed form; `test_deep_hedge.py::test_differentiable_accounting_matches_numpy_on_identical_actions`; `test_online_hedge.py::test_matches_batch_simulator_exactly_path_by_path`; `test_multi_step_run.py::test_trajectory_reconciles_to_independent_cash_flow_calculation` reconciles each policy through changing rates |
| HDG-05 (extended) | scenario decisions cannot see future shocks; risk sampling cannot affect trading | `test_multi_step_run.py::test_future_policy_shock_cannot_change_earlier_results`, `test_risk_sample_count_cannot_change_market_or_hedge_decisions` |
| RISK-04 (extended, conditional diagnostic) | CVaR of portfolio losses, with horizon and continuation assumptions declared | `test_multi_step_run.py::test_conditional_risk_uses_physical_portfolio_losses`; exact terminal loss/expiry checks in `test_all_months_are_completed_and_expiry_is_exact` |
| AUD-02 (extended) | replay and exported result hash cover full config, seeds, policy hash and step trace | `test_multi_step_run.py::test_replay_is_identical_but_run_id_is_unique`, `test_export_round_trip_preserves_full_result_hash_and_metric_meaning`, `test_cli_exports_a_replayable_bundle_and_prints_summary`; real generated `evidence/multi_step_reference.json` |
| ECO-16 (extended) | hook mutations are checked before emitting a completed step; failed runs retain invalid evidence | `test_time_engine_hooks.py::test_hook_corruption_is_rejected_before_a_step_result_is_emitted`; `test_multi_step_run.py::test_corrupted_ledger_cannot_produce_a_valid_run`, `test_firm_funding_failure_preserves_completed_steps_and_invalid_evidence` |

The financing correction is material: previously NumPy and PyTorch accrued
interest on cash *before* trading at each observed price. They now trade
at t, then accrue the resulting cash until t+dt, including the final
interval. Earlier benchmark numbers and fitted weights are not evidence
for this corrected convention without rerunning. All three simulators use
the same correction; the monthly runner opens the initial hedge at t=0
and does not trade again at expiry.

Conditional risk freezes current holdings and rates and draws physical
GBM continuation. It is not a forecast of a dynamically rehedging policy.
The model card reports only the single path's `realized_terminal_loss`,
not a fictitious sample CVaR. Monthly dt is 1/12 year with business-day
date labels. Economic and hedging accounts remain separate; failed steps
halt without rollback or resumption. No approval state has changed.

Local validation: 336 tests passed, 98% line coverage, ruff and strict mypy
clean. Commands, environment and reference-artifact hash are recorded in
[`evidence/validation_pr015.md`](./evidence/validation_pr015.md).

## Evidenced locally (PR-016: benchmark recipes and actual artifact replay)

`orchestration.benchmark_run` trains and evaluates a complete recorded
recipe under corrected financing. `orchestration.replay` reconstructs a
monthly or benchmark run from its exported JSON, retrains the model and
compares the actual recomputed result hash. Hash consistency alone is not
called a successful replay. This slice is local work pending commit and
independent review.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| AUD-02 (extended) | actual full-recipe replay, including typed dates/currency and training | `test_replay.py::test_replay_retrains_and_reproduces_the_exported_result`, `test_recorded_failed_scenario_replays_as_failed_not_successful`, `test_rehashing_fabricated_results_does_not_make_replay_match`; generated reference/replay artifacts in `evidence/` |
| EXP-03 (extended) | independent named path/bootstrap streams; test scenarios cannot affect training | `test_benchmark_run.py::test_seed_order_does_not_change_each_seeds_draws_or_bootstrap`, `test_different_test_seeds_cannot_change_training` |
| EXP-10 (extended, not full acceptance) | CVaR differences/CIs plus per-seed mean loss, cost and turnover | `test_benchmark_run.py::test_report_preserves_all_seed_results_and_financial_metrics`; `hedge_benchmark.SeedResult` and the generated corrected benchmark include each metric without selecting successful seeds |
| AUD-01 (partial, extended provenance) | bind recipe, training-data hash, policy hash, source digest and observed versions | `test_benchmark_run.py::test_recipe_and_policy_hash_are_bound_to_exported_payload`; `test_manifest.py::test_runtime_provenance_observes_source_and_dependency_versions`; no dependency lock, signed source identity or immutable external storage is claimed |
| AUD-11 (extended) | strict, atomic JSON export with explicit replay failure status | `test_evidence_export.py::test_invalid_export_preserves_existing_destination_and_leaves_no_tempfile`, `test_failed_atomic_replace_cleans_tempfile_and_preserves_destination`; `test_replay.py::test_cli_mismatch_has_nonzero_exit_status` |

Replay rejects corrupt hashes, mismatched manifest configuration/seed,
unsupported schemas/conventions, duplicate JSON keys and incomplete
recipes before expensive work. It preserves the source file and reports
runtime/source-version changes separately from result mismatches. Tests
exercise both monthly and benchmark artifacts.

The benchmark decision rule and primary endpoint are fixed before results
are examined. Intervals condition on one trained policy. They are not a
pooled/multiple-testing-adjusted estimate or uncertainty across training
seeds; the full factorial and independent-review requirements remain open.
Earlier PR-008 development findings remain historical; use the new
`evidence/hedge_benchmark_reference.json` for the corrected implementation.

Local validation: 409 tests passed, 97% line coverage, ruff and strict mypy
clean. Full CLI replays of the benchmark and monthly reference both
matched their expected hashes. The corrected three-seed benchmark was
inconclusive (all paired intervals included zero). See
[`evidence/validation_pr016.md`](./evidence/validation_pr016.md) for the
commands, result table, source digest and remaining limitations.

## Evidenced locally (PR-017: retraining/test-bank/stress study)

`orchestration.study_run` trains independently seeded models once each and
crosses every model with every test bank and declared scenario. The
default recipe retains 27 cells from three training replicates, three test
banks and three stress conditions. Actual held-out path hashes confirm
that models share the same test data, while training/data hashes identify
each independent retraining. This is local work pending commit and review.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| EXP-07 (extended) | uncertainty retains dependence from shared policies and shared test banks | `test_crossed_bootstrap.py::test_more_test_banks_do_not_erase_training_variability`, `test_more_models_do_not_erase_shared_test_bank_variability`, `test_crossing_resampled_rows_and_columns_includes_their_interaction`; crossed row/column percentile bootstrap, not flattened cell resampling |
| EXP-08 (nominal treatment, partial) | predeclare a secondary scenario family and adjustment strategy | `bonferroni_confidence`; `test_crossed_bootstrap.py::test_nominal_bonferroni_tail_allocation_and_validation`; family/confidence/margin/decision rule are hashed in the study recipe; approximate marginal coverage remains uncalibrated |
| EXP-12 (partial, synthetic parameter stress) | predefined OOD/perturbed regimes receive separate scores | baseline, high realized volatility and higher execution cost; `test_study_run.py::test_stress_paths_change_without_giving_delta_oracle_volatility`, `test_stress_configuration_cannot_affect_training` |
| HDG-11 (partial) | retain stress and worse-than-baseline outcomes | `test_study_run.py::test_every_training_test_scenario_cell_is_retained`; no seed/scenario is filtered by performance; no Heston/jump/historical or market-liquidity model is claimed |
| HDG-12 (partial) | mean loss/P&L sign convention, CVaR, costs and turnover across repeated comparisons | every study cell retains all financial metrics and a paired path-conditional CVaR interval; the crossed mean-CVaR-difference endpoint also checks a predeclared economic margin; paired cost/turnover inference and full acceptance remain open |
| AUD-02 (extended) | replay reconstructs all retraining seeds, complete stress grid and inference | study variants of `test_replay.py::test_replay_retrains_and_reproduces_the_exported_result`, `test_rehashing_fabricated_results_does_not_make_replay_match`; `test_study_run.py::test_order_of_declared_seeds_and_scenarios_cannot_change_inference` |

The bootstrap construction separately resamples crossed row and column
levels; see [Owen (2007)](https://arxiv.org/abs/0712.1111). The study endpoint
is the average of cell CVaR differences, not a pooled/ensemble portfolio
CVaR. Training-only and evaluation-only intervals are conditional
diagnostics; they are not independent variance components. Bonferroni
allocates nominal tail error across the declared grid but cannot repair
uncalibrated percentile-bootstrap marginal coverage with few seed levels.

Premium and delta's assumed volatility stay at training values under all
stress conditions; realized volatility and execution costs can change.
This is parameter stress within classical GBM, not broad model-family,
historical or macro-factorial validation. Policy initialization and
training data vary jointly across replicates rather than being separately
identified. Independent review and the remaining model ladder stay open.

Local validation: 473 tests passed, 97% line coverage, ruff and strict mypy
clean. The default 27-cell study and its full replay matched exactly;
the prior single-policy reference also replayed without computational
drift. The overall study verdict was inconclusive. See
[`evidence/validation_pr017.md`](./evidence/validation_pr017.md) for the
design, scenario results, exact hashes and inference limitations.

## Evidenced locally (PR-018: exact price discovery and atomic settlement)

`orchestration.economy_run` discovers wages/goods prices from cash-feasible
budget demand and monotone linear supply on integer currency ticks. It
settles exact pro-rata allocations, produces physical inventory from labor,
and applies a causal productivity shock. This local implementation is
pending commit and independent review.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| ECO-07 (extended, rule-based price discovery) | goods prices/quantities with explicit residual tolerance and rationing | `test_price_discovery.py::test_budget_linear_market_finds_an_independent_exact_root`, `test_adjacent_integer_ticks_report_residual_instead_of_false_equilibrium`; `test_exact_markets.py::test_integer_bisection_matches_an_exhaustive_price_grid` |
| ECO-08 (extended) | labor supply/demand, feasible wages and no duplicated hours | `test_market_settlement.py::test_entire_labor_market_is_one_balanced_batch`; exact rational pro-rata allocations are structurally checked on both market sides |
| LED-01 / LED-02 (extended) | one balanced market batch, integer cash and deterministic rounding | `test_market_settlement.py::test_largest_remainder_rounding_is_deterministic_and_does_not_exceed_total`, `test_aggregate_rounding_remainder_is_exact_and_reported`; largest-remainder payments sum to floor(total nominal value) |
| ECO-02 (extended) | buyer/payroll budgets are enforced before settlement | `test_market_settlement.py::test_later_insolvent_buyer_cannot_leave_a_partial_market`, `test_unfunded_payroll_is_rejected_without_any_posting`; legacy helper regression tests cover later-party funding failures |
| ECO-16 (extended) | pre-mutation currency/identity checks and explicit halt on failed price search | `test_ledger.py::test_later_currency_mismatch_cannot_partially_apply_earlier_postings`, `test_posting_on_a_corrupted_ledger_fails_before_further_mutation`; `test_economy_run.py::test_unresolved_price_search_halts_with_invalid_evidence` |
| ECO-01 (extended) | economic snapshots cannot be changed through aliased input mappings | `test_ledger.py::test_state_balances_are_immutable_and_detached_from_input_mapping`; balance maps are copied into read-only views |
| LED-12 / VAL-07 (extended) | randomized exact settlement conserves money and quantity | `tests/property/test_exact_markets.py` covers buyer feasibility, firm payroll limits, cash/equity conservation and an exhaustive integer-price oracle; `test_economy_run.py::test_every_step_conserves_cash_equity_and_physical_inventory` checks cumulative production/sales/inventory |
| AUD-02 (extended) | exact-rational recipe/trace round-trip and actual economy replay | `test_economy_run.py::test_full_json_round_trip_and_replay_preserve_exact_quantities`; economy variants of the generic replay tests verify corruption/mismatch handling |

Tick-limited or price-bound quotes explicitly retain excess demand; these
are not silently described as exact equilibrium. Opening capital and
household endowments are recorded exogenous injections. Subsequent wage
and goods transactions conserve money exactly. Divisible physical goods
and inventory have rational quantities but no monetary asset valuation.
Behavioral schedules and payroll targets are specified rules rather than
estimated preferences or profit-maximizing agent policies.

Exact settlement is atomic per market, not per entire macro step. Original
fixed-quote helpers preserve their posting/rounding convention and now
validate all expected funds/participant failures before the first payment.
Ledger rejects duplicate transaction IDs, and failed transactions do not
consume automatic IDs. Whole-step failure still halts without rollback.

Local validation: 558 tests passed, 97% line coverage, ruff and strict mypy
clean. The twelve-step price-economy replay matched exactly, with 24 market
batches reconciled from exported JSON. The previous full financial monthly
reference also reproduced its original result hash. See
[`evidence/validation_pr018.md`](./evidence/validation_pr018.md) for the
scenario table, exact hashes, commands and accounting/model limitations.

## Evidenced locally (PR-019: published-data monetary feedback)

`orchestration.monetary_run` couples the reusable exact price economy to
publication-lagged inflation/output feedback, financial drift/financing,
closing-rate marks and opening-rate payroll demand. This extends the scalar
PR-009/012 policy rules with actual published economic inputs. It remains a
local synthetic implementation pending commit and independent review.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| ECO-05 (extended, synthetic rule) | policy reaction coefficients, smoothing and bounds reproduce independently calculated cases | `test_monetary_feedback.py::test_policy_reaction_matches_independent_coefficients_and_smoothing`, `test_policy_bounds_are_applied_after_smoothing_and_reported` |
| ECO-13 (extended) | policy observes only available macro data | `test_monetary_feedback.py::test_future_publication_is_rejected_if_a_caller_bypasses_point_in_time_store`; `test_monetary_run.py::test_productivity_shock_affects_policy_only_after_release_and_market_one_interval_later` tests one- and two-month lags |
| ECO-14 (extended, specified channels) | productivity shocks propagate causally to prices, rates and subsequent financial periods | `test_monetary_run.py::test_last_step_productivity_shock_cannot_change_financial_history`, `test_higher_opening_rates_reduce_desired_payroll_and_real_activity`; no empirically identified impulse-response claim |
| DAT-07 (partial, synthetic) | observation/publication dates and inclusion predicates | `test_monetary_feedback.py::test_macro_data_is_unavailable_until_publication_and_warms_up_on_two_prices`, `test_model_month_metadata_prevents_business_day_rolls_from_changing_annualization`, `test_no_trade_quote_never_manufactures_a_macro_observation`; external ingestion/vintage archives remain absent |
| HDG-01 / HDG-06 (extended) | financing and transaction costs reconcile with actual interval rates | `test_hedge_comparison.py::test_opening_rate_finances_each_interval_and_expiry_has_no_new_trade`; `test_monetary_run.py::test_hedge_cash_reconciles_with_opening_rates_and_actual_executions` checks call and put accounts independently |
| LED-12 / VAL-07 (extended) | coupled feedback preserves exact economic accounting | `test_monetary_run.py::test_coupled_steps_preserve_economic_conservation_and_opening_rate_timing`, `test_delayed_publication_prevents_any_policy_or_real_activity_feedback`; standalone price-economy results remain identical without active feedback |
| AUD-02 (extended) | full nested recipe, training/model fingerprints and actual replay | `test_monetary_run.py::test_full_nested_recipe_json_and_actual_replay`; monetary variants of `test_replay.py` reject missing configuration and fabricated results even after rehashing |

The complete trace includes released inputs, new future publications,
policy targets/bounds, payroll multipliers, exact economic states, opening
market/financing rates, closing valuations and hedge executions. Reusing an
economic process's actions, settlement or snapshot out of sequence is
rejected; tests prevent a repeated action from applying the productivity
shock twice. Conditional-risk RNG draws cannot alter the realized path.

This rule is uncalibrated, with configured physical potential output and
annualized model-good price inflation rather than GDP/CPI. Economic and
hedge balance sheets remain separate. Black-Scholes marks freeze the closing
rate until expiry; a stochastic-rate risk-neutral model is not implemented.
Conditional risk freezes current holdings/rates and omits future feedback.
MLP training uses a constant-rate environment. Warmup holds the rate; after
warmup, missing trades can leave the latest published signal stale.

Local validation and generated reference/replay results are recorded in
[`evidence/validation_pr019.md`](./evidence/validation_pr019.md).

## Evidenced locally (PR-020: crossed macro-feedback hedge study)

`orchestration.monetary_study` crosses independent retrainings with shared
stochastic macro/market banks and explicit feedback scenarios. The default
design has 36 cells: three training replicates, three banks and four
scenarios. Each bank has one economy path and 512 conditional market paths.
The common `MonetaryProcess` supplies the original online scenario's exact
economic actions, publication filtering and policy decisions. Local work
remains pending commit and independent review.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| EXP-01 / EXP-10 (extended) | declared endpoint, margin, cell metrics and decision rule | `monetary_study.ENDPOINT`; payload records CVaR differences, mean loss/cost/turnover, uncertainty and all-scenario direction rule; `test_monetary_study.py::test_complete_crossing_shares_banks_and_keeps_every_retraining` |
| EXP-02 (partial, specified macro scenarios) | vary macro conditions and compare hedge policies | default publication-delay, payroll-channel and supply-shock scenarios crossed with delta/MLP; no learned economy/market arms or full blueprint factorial |
| EXP-07 / EXP-08 (extended, approximate inference) | shared-bank dependence and declared scenario-family adjustment | crossed row/column bootstrap, nominal Bonferroni confidence; `test_reversing_declared_axes_cannot_change_inference_or_result_hash`; inherited exact crossed-bootstrap fixtures remain applicable |
| EXP-12 (partial, synthetic feedback stress) | held-out publication/real-activity/supply regimes with shared shocks | `test_stress_changes_realized_volatility_costs_without_changing_training_or_macro`; identical per-bank normal hashes and identical training hashes across scenario stress |
| HDG-01 / HDG-06 / HDG-13 (extended) | identical changing-rate financing and costs for both hedges | shared batch simulator with explicit interval/path funding schedules; `test_rate_paths.py::test_changing_funding_rates_match_independent_cash_and_online_accounts`; `test_zero_policy_cell_matches_closed_form_financing_and_fractional_tail` checks a cell against an independent naked-option calculation |
| ECO-13 (extended) | future policy rates never enter current hedge targets or completed market periods | `test_rate_paths.py::test_gbm_uses_opening_rate_and_delta_only_current_rate`; scalar Black-Scholes cross-checks and expiry-only rate perturbation |
| ECO-16 (extended) | failed bank cannot yield a selectively successful experiment | `test_no_training_or_inference_when_any_macro_bank_fails`, `test_one_failed_bank_suppresses_successful_subset_inference`; all bank records retained, no training/cards/inference on any macro failure |
| AUD-02 (extended) | actual replay reconstructs macro traces, all retrainings and common banks | `test_actual_replay_retrains_and_recomputes_macro_banks`, `test_bank_hash_reconstructs_from_released_rates_and_named_market_normals`; generic replay tests now cover this sixth payload type |

Each cell CVaR conditions on its bank's realized macro path. Averaging
those cell differences estimates the declared conditional-risk endpoint;
it does not estimate CVaR after pooling the unconditional macro/market
distribution. Three training/bank levels provide limited bootstrap
coverage evidence. Nominal tail allocation does not fix marginal coverage.
Training and scenario evaluation retain identical premium/strike/horizon;
delta observes current rates with fixed pricing volatility, while the MLP
keeps its original three features and constant-rate training distribution.

This adds macro sensitivity evidence to the earlier purely financial stress
study. It does not establish optimal monetary policy, empirical macro
calibration, a learned-economy/learned-market factorial, unconditional tail
risk, or a full online dynamic-policy conditional-risk forecast. Numerical
financial failures raise rather than silently omit cells. No scientific
acceptance is claimed. See
[`evidence/validation_pr020.md`](./evidence/validation_pr020.md).

## Evidenced locally (PR-021: matched current-rate feature experiment)

`orchestration.rate_study` fits matched rate-aware and rate-blind MLPs on
separate, independently generated macro training banks, then compares both
with delta on shared held-out macro/market banks. Both learned arms have
four inputs and identical architecture, initialization, minibatches,
changing-rate accounting, cost and optimizer settings. Only the current-rate
feature is active or zeroed. This remains local work pending commit/review.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| HDG-04 / HDG-05 (extended) | bounded causal policy with current-rate information | `rate_hedge.RateHedgePolicyMLP`; `test_rate_hedge.py::test_only_current_rate_changes_aware_targets_and_blind_arm_ignores_rates` uses an independently constructed rate-only network and future/expiry perturbations |
| HDG-01 / HDG-06 (extended) | changing-rate differentiable financing matches evaluation cash/cost recursion | `test_differentiable_changing_rate_accounting_matches_shared_numpy_simulator` covers call/put losses, turnover, costs, actions and nonzero finite gradients |
| HDG-10 (partial, training-batch diagnostics) | gradient norms, action saturation and tail-loss diagnostics | `RateTrainingDiagnostic` logs CVaR/objective, mean loss/turnover, pre-clipping norm, clipping flag and abs(action)>=.99 fraction per epoch; `test_training_is_deterministic_paired_and_preserves_global_rng`; no calibrated probabilistic policy-risk guarantee |
| HDG-13 / EXP-06 (extended, matched-feature control) | apparent feature gains cannot come from larger architecture or different training data | `test_training_arms_are_parameter_and_data_matched_with_full_crossing`; `test_identical_rate_history_makes_blind_and_aware_training_exactly_equal`; zero feature acts as an information ablation, not an untrained random hedge |
| EXP-03 / ECO-13 (extended) | independent training/evaluation draws; no test-scenario-dependent fitting | `test_test_seeds_and_scenarios_cannot_change_training_data_or_fitted_models`; `test_training_pool_records_balanced_allocations_rates_and_independent_macro_seeds` |
| EXP-07 / EXP-08 (extended, approximate inference) | two declared contrasts retain row/bank dependence and family allocation | rate-blind-minus-aware primary, delta-minus-aware secondary; nominal Bonferroni allocation over all scenario/contrast pairs; `test_all_declared_axes_can_be_reversed_without_changing_results` |
| ECO-16 (extended) | failed training/evaluation bank cannot produce selectively valid evidence | `test_any_training_macro_failure_suppresses_all_fitting_and_inference`, `test_failed_evaluation_and_training_banks_replay_as_invalid` |
| AUD-02 (extended) | reproducible data, feature semantics, matched minibatches and full artifact replay | `test_policy_hash_binds_feature_semantics_and_scaling`; `test_actual_replay_retrains_both_arms_and_rejects_fabricated_results`; generic replay tests cover this seventh payload type |

Training and test macros use separate named RNG domains, with independent
training economies for each row. Each training pool allocates the declared
path count across sorted macro labels, retaining all rates and trace/hash
provenance. Policy hashes include rate masking, centering and scaling, so
the same weights with different feature semantics are not presented as the
same policy. Every epoch's paired minibatch sequence is fingerprinted.

The default has three retraining rows, three training economies per row,
three test banks and four test scenarios. Each cell includes delta plus
both learned arms. All eight scenario/contrast intervals share declared
nominal tail allocation. The primary result is an average of conditional
cell CVaR differences, not unconditional pooled tail risk or evidence that
additional features must help. Training uses a finite macro mixture and
the only extra feature is the current scalar rate; empirical validation,
macro-history encoders and full dynamic-policy conditional-risk forecasting
remain absent. See
[`evidence/validation_pr021.md`](./evidence/validation_pr021.md).

## Evidenced today (PR-022: risk-neutral calibration)

`volterra.calibration.calibrate_implied_volatility` recovers a single
Black-Scholes implied volatility from one observed option price via
bracketed root-finding (`scipy.optimize.brentq`); `calibrate_volatility_smile`
applies it independently across a list of (strike, price) quotes at a
shared spot/rate/maturity. This is new work on top of PR-021, not part of
its local-validation count above.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| PRI-05 | risk-neutral calibration procedure; implied-vol loss, parameter constraints and errors retained | `volterra.calibration.calibrate_implied_volatility`; `tests/unit/test_calibration.py::test_round_trip_recovers_the_exact_volatility` (27-case parametrized round trip: 3 strikes x 2 option types x 3 volatility regimes, each recovered to within 1e-8 of the true value, not one convenient case) |
| PRI-12 (extended) | fail closed on invalid/unrationalizable parameters | `CalibrationError` is raised, with the specific no-arbitrage bounds reported, whenever a quoted price cannot be rationalized by *any* volatility -- checked analytically before root-finding is attempted, not discovered by a failed search; a separate test also covers a bracket that excludes the true root even though the quote itself is valid |
| PRI-11 (adjacent, explicitly not claimed) | volatility surface arbitrage checks | `calibrate_volatility_smile` fits strikes independently and imposes no cross-strike smoothness or arbitrage-free-surface constraint; a genuine (non-flat) smile shape is recovered exactly in `test_genuine_smile_shape_is_recovered_strike_by_strike`, demonstrating the fit captures real cross-strike variation, but nothing here checks that the *resulting* fitted surface itself is calendar/butterfly arbitrage-free |

Not covered: rate calibration (only volatility is fit; `risk_free_rate` remains supplied), a smoothed or parametric (e.g. SVI) surface representation, and any connection from a calibrated surface back into `MarketSnapshot`-consuming code elsewhere in this repository (hedging, benchmarks and the monetary/rate studies above all still take volatility as a direct input, not a calibration output).

28 new tests, ruff/mypy --strict clean, 100% line coverage on the new module, 794 tests passing project-wide.

## Evidenced today (PR-023: portfolio optimization)

`titan.portfolio` adds mean-variance (global minimum-variance and
Markowitz target-return) and scenario-CVaR (Rockafellar-Uryasev, via
linear programming) portfolio optimization, the first evidence for
TITAN's OPT-* checklist category (section 08), which had none before this.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| OPT-01 | budget-constrained mean-variance optimization, checked against a reference solver | `titan.portfolio.minimum_variance_portfolio` / `target_return_portfolio`; `tests/unit/test_portfolio.py::test_minimum_variance_matches_closed_form_global_min_var_portfolio` and `test_target_return_matches_closed_form_two_fund_formula` -- both match their exact closed-form analytical solutions to within `1e-7`, not an approximate/qualitative check |
| OPT-02 | max/min weight, leverage and short-sale controls; solver refuses infeasible requests with diagnostic | `PortfolioConstraints`; `test_minimum_variance_reports_failure_for_an_infeasible_box` -- a box constraint that makes the budget unreachable (`max_weight * n_assets < budget`) is confirmed to return `success=False` with a non-empty diagnostic message, not a silently-wrong allocation |
| OPT-03 | CVaR portfolio optimization via scenario formulation, toy exact solutions validated | `titan.portfolio.cvar_optimal_portfolio`; `test_cvar_optimal_portfolio_matches_brute_force_grid_search` cross-checks the LP solution against an independent brute-force grid search over a 2-asset weight using `titan.risk_metrics.historical_expected_shortfall` directly -- a different code path from the LP, not the same implementation checked against itself |
| OPT-04 | turnover and proportional cost penalties, cost tradeoff vs. naive solution | `turnover_penalty`/`prior_weights` on `target_return_portfolio`; `test_turnover_penalty_pulls_the_solution_toward_the_prior_portfolio` confirms realized turnover is strictly lower with the penalty active, holding everything else fixed |
| OPT-09 | solver name, tolerance, duality/termination state tracked; no infeasible solution silently labeled optimal | every `OptimizationResult`/`CVaROptimizationResult` carries `solver`, `success` and `status_message` unconditionally; both the SLSQP and HiGHS (linprog) infeasibility paths are exercised by name in tests, including an explicitly unachievable CVaR target-return constraint |

Not covered by PR-023: OPT-05 (robust covariance/scenario-uncertainty), OPT-06 (liquidity/position-capacity constraints beyond simple box bounds), OPT-07 (multi-period rebalancing simulator -- see PR-025 below), OPT-08 (out-of-sample optimization comparison), OPT-10..12 (turnover-adjusted backtested performance, stress-regime testing, allocation-shift attribution). Nothing in this repository calls `titan.portfolio` yet -- it is standalone, like most subsystems were before PR-014's step hooks; it is not wired into `StepHooks`, the hedging subsystem, or any of PR-015..021's benchmark/study runners.

17 new tests, ruff/mypy --strict clean, 100% line coverage on the new module, 811 tests passing project-wide.

## Evidenced today (PR-024: covariance shrinkage)

`titan.covariance` adds Ledoit-Wolf (2004) analytic shrinkage of the
sample covariance toward a scaled-identity target, connecting directly to
PR-023's portfolio optimizer. The formula was derived by reading
scikit-learn's `ledoit_wolf_shrinkage` source directly, not reimplemented
from memory of the paper, and scikit-learn is used as a dev-only test
oracle (added to `[project.optional-dependencies].dev`, not a runtime
dependency of this package).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| RISK-05 | volatility/covariance estimators, PSD and shrinkage safeguards unit-tested | `titan.covariance.shrink_covariance_ledoit_wolf`; `tests/unit/test_covariance.py::test_shrinkage_recovers_positive_definiteness_from_a_singular_sample` constructs an n < p sample (confirmed singular via its own eigenvalues first), then confirms the shrunk result is strictly positive definite |
| OPT-05 | robust covariance/scenario-uncertainty extension, sensitivity to perturbation reported | `ledoit_wolf_shrinkage_intensity` is cross-checked against scikit-learn's reference implementation to within `1e-9` across 6 (n_observations, n_assets) regimes including n > p, n < p, n == p and the n == 2 boundary; `test_shrinkage_is_higher_for_a_small_sample_than_a_large_one` confirms the intensity responds correctly to sample-size "perturbation" with a fixed non-trivial true covariance |

The practical payoff is demonstrated end to end, not just claimed: `test_reduces_true_out_of_sample_portfolio_variance_vs_raw_sample_covariance` repeatedly draws small samples (n=15, p=10) from a fixed true covariance, builds a `minimum_variance_portfolio` from both the raw sample covariance and the shrunk one, and confirms the shrunk-covariance portfolio's TRUE (population, not sample) out-of-sample variance is lower on average and in the majority of individual trials -- the classic empirical case for shrinkage, reproduced here rather than cited.

Not covered: shrinkage toward a constant-correlation or factor-model target (only scaled-identity), any scenario-based (as opposed to historical-sample) robust covariance method, and no connection from this module into the hedging/monetary/rate studies above, which still estimate or supply covariance/volatility directly.

17 new tests, ruff/mypy --strict clean, 100% line coverage on the new module, 828 tests passing project-wide.

## Evidenced today (PR-025: multi-period portfolio rebalancing simulator)

`titan.rebalancing` is the first module to connect PR-023's portfolio
optimizer and PR-024's covariance shrinkage estimator across *simulated
time* rather than as single standalone calls: `simulate_rebalancing` walks
a plain `(n_total_periods, n_assets)` returns array period by period,
periodically re-estimating a (optionally Ledoit-Wolf shrunk) covariance
from a trailing window, re-optimizing against the realized prior holdings
(minimum-variance or Markowitz target-return, with an optional turnover
penalty), and executing the resulting trade under a proportional
transaction cost. `minimum_variance_portfolio` (PR-023) was extended with
the same `prior_weights`/`turnover_penalty` parameters `target_return_portfolio`
already had, reusing the existing `_turnover_penalty_term` helper (4 new
tests in `test_portfolio.py`, 21 total there now).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| OPT-07 | multi-period rebalancing simulation with periodic re-estimation and transaction costs | `titan.rebalancing.simulate_rebalancing`; `test_runs_end_to_end_with_realistic_correlated_returns` drives it on `stochastica`-generated correlated GBM paths; `test_wealth_evolves_consistently_period_by_period` independently recomputes the entire wealth path from each period's reported return and cost outside the module and confirms it matches to `1e-10`, not just that the final number looks plausible |
| OPT-10 (extended) | turnover-adjusted performance and drawdown reporting over a rebalancing path | `RebalancingResult.total_cost`/`total_turnover`/`max_drawdown`/`historical_var_95` (reusing `titan.risk_metrics`, PR-006); `test_higher_transaction_costs_reduce_final_wealth` and `test_less_frequent_rebalancing_reduces_total_turnover` both demonstrate the expected monotone sensitivity, holding the return path fixed and varying only the cost/frequency parameter |

The no-lookahead property claimed in the module's own docstring is tested
directly, not just documented: `test_a_future_return_cannot_change_any_earlier_period_decision`
perturbs `returns[90:]` by `+5.0` and confirms every one of the first 30
periods' weights, realized returns and wealth are bit-identical to an
unperturbed run -- a later period's return cannot leak into an earlier
decision. `RebalancingFailure` (a dedicated exception, not a silently
stale-weight fallback) is confirmed raised when a scheduled rebalance's
optimization is infeasible, and plain `ValueError` is confirmed for a
`returns` array too short for the requested `estimation_window` +
`n_periods`.

Not covered: no position/account-level ledger integration (this is a pure
array-in, array-out simulation, not wired into `core.ledger` or any
`StepHooks` scenario); no out-of-sample train/test split comparison
(OPT-08) -- the same trailing window is both the estimation source and the
only data available, by construction, there is no held-out comparison
period; no stress-regime testing within the rebalancing loop itself or
full allocation-shift attribution (OPT-11/OPT-12 get their first,
separate evidence from PR-030's `titan.stress_testing`, not integrated
here); transaction costs are a single proportional rate applied to
total turnover, not a market-impact or bid/ask-spread model; expected
returns for the target-return mode are the trailing sample mean, with no
shrinkage or factor-model alternative.

13 new tests in `test_rebalancing.py` plus 4 in `test_portfolio.py` (17
new total), ruff/mypy --strict clean, 100% line coverage on both the new
module and the extended `minimum_variance_portfolio`, 844 tests passing
project-wide.

## Evidenced today (PR-026: central-bank ledger-backed balance sheet)

`econosim.central_bank_ledger.CentralBankLedger` is a genuine ledger-backed
agent built the same way every other agent in `econosim.agents` is --
`econosim.policy_rate.CentralBank` (the rate-process wrapper used
everywhere else in this repository) is unchanged and still has no balance
sheet at all; this is a separate, additional agent, not a replacement.
Three reserve-issuance/settlement channels, each one balanced Transaction:

- `purchase_government_bonds` / `sell_government_bonds` -- open market
  operations (OMO): the central bank buys/sells a bank's loans-receivable
  balance (the same account `Bank.originate_loan` posts to for every
  `Borrower`, PR-002/PR-012) in exchange for reserves.
- `lend_to_bank` / `repay_central_bank_loan` -- discount-window lending, a
  second reserve-issuance channel matched by a central-bank receivable
  rather than by securities.
- `settle_interbank_transfer` -- moves reserves between two *different*
  `Bank` instances' accounts at this central bank: the first transaction
  anywhere in this repository posting against two distinct agent
  instances sharing one `Sector` (`Sector.BANK`) in a single Transaction.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| ECO-05 (extended) | central bank with a real balance sheet (reserve issuance, OMO) | `CentralBankLedger.purchase_government_bonds`/`sell_government_bonds`/`lend_to_bank`/`repay_central_bank_loan`; `test_purchase_government_bonds_moves_bonds_for_reserves` and `test_lend_to_bank_and_repay_round_trip_exactly` confirm exact round trips back to the starting balances, not just a plausible-looking end state |
| ECO-09 (extended) | interbank settlement / reserve transfer between banks | `CentralBankLedger.settle_interbank_transfer`; `test_settle_interbank_transfer_reallocates_without_changing_total_liability` confirms the central bank's total reserve liability across both banks is unchanged by a transfer -- it is a pure reallocation, not new issuance |
| LED-01 (extended) | multi-agent-same-sector transaction correctness | `test_multi_channel_sequence_keeps_ledger_and_per_bank_identities_balanced` exercises all three channels against two different `Bank` instances sharing `Sector.BANK`, re-checking `Ledger.check_identities` after every step, and separately proves by hand-summing each bank's own accounts that OMO/discount-window operations keep each bank individually balanced, while `settle_interbank_transfer` (by design, see its own docstring) shifts each bank's individual residual by exactly the transferred amount in opposite directions -- caught by writing this test, not assumed |

A genuine limitation was caught by this module's own tests, not just
documented after the fact: `settle_interbank_transfer` moves only the
reserve-asset leg, so by itself it is balanced at the whole-`Sector.BANK`
level (which is all `Ledger.check_identities` actually checks) but NOT on
either individual bank's own book -- a real interbank settlement is paired
with a matching customer-deposit movement on both banks' books that this
repository cannot post, because no cross-bank customer deposit/transfer
mechanism exists (every `Household`/`Firm` deposit sits at exactly the one
`Bank` that created it). The method's own docstring states this rather
than silently assuming the pairing leg's existence.

Not covered: no seigniorage/profit remittance to government (the central
bank's own equity account is opened for structural symmetry but is never
posted to -- every channel here is exactly asset-for-liability); no
reserve-requirement enforcement tying `Bank.max_leverage`-style constraints
to a bank's central-bank settlement balance; `CentralBankLedger` was, at
the time of this PR, constructed and exercised standalone in its own test
file only -- PR-028 below wires it into `Economy` and the real `StepHooks`
event order, though still not into any orchestration CLI/evidence-export
runner; bond holdings are not tracked as a distinct instrument from
ordinary loans within `Bank.loans_account` (the same simplification
`Government.issue_bonds` already relies on via the shared `Borrower`
protocol), so OMO validation checks only the bank's *aggregate*
loans-receivable balance.

21 new tests, ruff/mypy --strict clean, 100% line coverage on the new
module, 865 tests passing project-wide.

## Evidenced today (PR-027: factor exposure model and risk decomposition)

`titan.factor_model` adds `estimate_factor_exposures` (per-asset OLS
alpha/beta/residual-variance/R^2 against a set of common factor returns,
solved once for every asset via one shared design matrix) and
`decompose_portfolio_variance` (splits a portfolio's total variance into
factor-driven and idiosyncratic components, plus a per-factor Euler
marginal-contribution breakdown that sums exactly to the factor total).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| RISK-07 | factor exposure estimation and portfolio risk decomposition into systematic/idiosyncratic components | `titan.factor_model.estimate_factor_exposures`/`decompose_portfolio_variance`; `test_estimate_factor_exposures_matches_lstsq_to_machine_precision` cross-checks the OLS normal-equations solve against `numpy.linalg.lstsq` -- a different algorithm (SVD-based, not matrix inversion) -- to `1e-9`; `test_decompose_portfolio_variance_matches_full_implied_covariance_matrix` independently cross-checks the factor-space decomposition against a direct `w' Sigma w` quadratic form over the full (n_assets, n_assets) implied covariance matrix |

The practical payoff is demonstrated, not just asserted:
`test_estimated_decomposition_converges_to_true_decomposition` simulates
5,000 observations from a KNOWN 2-factor, 4-asset model (known betas,
factor covariance and idiosyncratic variances), estimates exposures from
the simulated sample alone, and confirms the resulting decomposition
converges to within 5% of the one computed from the ground-truth
parameters -- a genuine statistical recovery check, not internal
self-consistency. `test_connects_to_titan_portfolio_and_covariance_modules`
composes this module with PR-023's `minimum_variance_portfolio` and
PR-024's `shrink_covariance_ledoit_wolf` in one test, confirming the
factor-route risk of a portfolio built from a shrunk covariance matches
the direct quadratic-form risk under the same exact factor-implied
covariance.

Not covered: the factor covariance matrix itself is always supplied by
the caller, never estimated from the factor returns by this module (tests
estimate it ad hoc with `numpy.cov` where needed); no shrinkage is applied
to either the factor covariance or the per-asset residual variances; the
idiosyncratic-uncorrelated-across-assets assumption is structural, not
tested against real cross-sectional residual correlation; and like every
other `titan.*` module, this one is standalone -- not wired into
`StepHooks`, `titan.rebalancing`, or any orchestration runner.

17 new tests, ruff/mypy --strict clean, 100% line coverage on the new
module, 882 tests passing project-wide.

## Evidenced today (PR-028: central bank wired into StepHooks)

`econosim.monetary_operations.MonetaryOperationsProcess` is the first
scenario anywhere in this repository to drive PR-026's `CentralBankLedger`
through the real `MacroTimeEngine`/`StepHooks` event order, not standalone
calls in one test. `Economy` gained `add_central_bank_ledger` (alongside
the pre-existing rate-only `add_central_bank`) so a simulation can hold a
ledger-backed central bank in the same `add_*`-tracked-by-id pattern as
every other agent -- directly closing the "not wired into `Economy`"
limitation PR-026 explicitly admitted. Each step: the existing
rate-only `policy_rate.CentralBank` decides the policy rate (same rule,
same `.step(shocks)` call multi_step_run.py already uses); the rate's
*change* that step sizes an open-market operation (buy when easing, sell
when tightening) executed through `CentralBankLedger`; a fixed
discount-window loan is drawn once and amortized on a schedule; and a
periodic interbank reserve transfer moves reserves between the two banks
-- exercising all three `CentralBankLedger` channels together, across
simulated time, for the first time.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| ECO-05 (extended) | central-bank balance sheet operations driven by the real step-event order, not standalone | `MonetaryOperationsProcess.compute_actions`/`clear_and_settle`, wired as `StepHooks` callbacks exactly like `price_economy.PriceEconomy`'s two hooks already are; `test_full_engine_driven_run_keeps_ledger_identities_balanced_every_step` runs 24 real `MacroTimeEngine.advance_step()` calls with a seeded policy-rate shock stream and reconfirms `Ledger.check_identities` after every single one |
| ECO-16 (extended) | a failed/infeasible monetary operation is skipped and recorded, not allowed to silently halt or corrupt the run | every channel's execution is wrapped in its own try/except recording a `*_skipped_reason` string rather than propagating; `test_discount_window_repayment_remaining_is_unchanged_after_a_skipped_repay` confirms a failed repay attempt leaves the internal amortization schedule exactly unchanged, not partially applied |

An exact reconciliation test, not an approximate one:
`test_bank_b_settlement_balance_reconciles_exactly_with_successful_transfers`
runs a full seeded scenario, counts how many scheduled interbank transfers
actually executed (some are skipped when the payer lacks balance), and
confirms the payee bank's final settlement balance equals EXACTLY that
count times the configured transfer amount, after the discount-window
loan (whose lend/repay legs net to exactly zero once fully amortized) is
fully repaid -- `test_discount_window_fully_amortizes_to_zero_in_default_configuration`
separately confirms the default principal/installment configuration
amortizes to exactly zero with no lingering fractional remainder.
Determinism is also tested directly: the same seed reproduces identical
per-step ledger state hashes end to end, and a different seed diverges.

Not covered: this is a two-bank, single-central-bank, rule-based scenario
with no profit-maximizing or learned monetary policy -- the OMO/lending/
transfer sizes are specified schedules, exactly like `policy_rate.PolicyRateRule`
itself; at the time of this PR it was not wrapped in an orchestration
CLI/evidence-export runner or registered with `orchestration.replay`,
unlike the other `StepHooks` scenarios (PR-015, PR-018, PR-019) -- PR-029
below adds exactly that; and it does not connect to `titan.portfolio`/
`titan.covariance`/`titan.factor_model` (PR-023/024/027), which remain
standalone.

27 new tests (plus 2 more in `test_central_bank.py` for
`add_central_bank_ledger`), ruff/mypy --strict clean, 100% line coverage
on the new module, 911 tests passing project-wide.

## Evidenced today (PR-029: monetary operations orchestration/replay)

`orchestration.monetary_operations_run` wraps PR-028's scenario in the
exact CLI/evidence-export/replay pattern every other `StepHooks` scenario
already uses (`economy_run.py`, `monetary_run.py`, ...), closing the gap
PR-028 explicitly left open. `MonetaryOperationsConfig` (PR-028) gained a
`policy_rate_shock_std` field and a `from_dict` classmethod (the same
exact-field-set, no-silent-defaults contract as `EconomyRunConfig.from_dict`),
and `orchestration.replay` gained a new `"monetary_operations"` convention
key, a `model_convention` check, and a dispatch branch -- the complete set
of integration points every other replay-registered scenario already has.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| AUD-08/AUD-11 (extended) | reproducible evidence export with disclaimer/source-tag, independently replayable | `run_monetary_operations`; `test_full_json_round_trip_and_replay_preserve_the_exact_result` exports a real evidence bundle to disk, re-reads it, independently recomputes the full recipe via `orchestration.replay.replay_evidence_bundle`, and confirms the observed hash matches the recorded one -- the same full-fidelity check `economy_run.py`'s own replay test performs |
| EXP-03 (extended) | seed hierarchy reconstructs nested RNG state on replay | the policy-rate shock stream is drawn from `SeedHierarchy(config.seed).stream("policy-rate-shocks")`, a named, order-independent stream (core.seeds, PR-003); `test_same_config_is_fully_deterministic` confirms two runs from the same seed produce bit-identical per-step ledger state hashes, not just the same final result |

A tampered-input rejection is tested directly, not just implied by the
`CONVENTIONS` dict's existence: `test_replay_rejects_a_tampered_model_convention`
corrupts a real exported bundle's `model_convention` field and confirms
`verified_payload` raises before any simulation work is attempted --
mirroring (and newly covering, where the four pre-existing sibling
conventions' equivalent checks were not) the same fail-fast contract.

Not covered: the orchestration layer adds no new economic behavior over
PR-028 -- it is packaging (CLI, evidence export, replay) only; CLI flags
cover only a subset of `MonetaryOperationsConfig`'s fields (seed, steps,
start date, shock std, interbank cadence), not every field, matching
`economy_run.py`'s own CLI's partial-coverage precedent.

16 new tests, ruff/mypy --strict clean, 100%/98% line coverage on the two
new/modified orchestration-layer files, 932 tests passing project-wide.

## Evidenced today (PR-030: stress testing)

`titan.stress_testing` adds deterministic stress-scenario evaluation: a
named shock, applied either to a set of common factors (composed with
PR-027's `factor_model` betas) or directly to asset returns, scored
against portfolio weights and ranked against an externally supplied VaR
threshold. Sign convention matches `titan.risk_metrics` exactly (loss
positive when money is lost), so results compose directly with
`historical_var`/`historical_expected_shortfall` without any conversion.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| RISK-10 | named stress scenarios (factor-based and historical-replay) applied to a portfolio, loss reported in a consistent sign convention | `stress_scenario_loss_from_factor_shock`/`stress_scenario_loss_from_asset_shock`/`historical_scenario_losses`; `test_factor_shock_matches_the_equivalent_implied_asset_shock` independently cross-checks the factor-shock path against composing the shock through `betas` into an implied asset-level shock and applying it through the completely separate asset-shock path |
| OPT-11 | stress-regime testing integrated with the portfolio optimizer and VaR | `run_stress_tests`'s `worst_case_exceeds_var` flag; `test_worst_case_scenario_exceeding_historical_var_is_flagged` builds a real historical loss series, computes its 95% VaR with `titan.risk_metrics.historical_var`, and confirms a scenario engineered to lose more is flagged while one engineered to lose less is not |
| OPT-12 (partial) | loss attribution across risk factors under a stress scenario | `stress_scenario_factor_attribution`; sums *exactly* (not approximately -- the underlying dot product is linear, unlike variance's Euler allocation) to the scenario's total loss, confirmed directly |

The full composition is exercised end to end, not just unit by unit:
`test_connects_to_factor_model_covariance_and_portfolio_modules` simulates
a known factor model, estimates exposures (PR-027), shrinks the
covariance (PR-024), builds a minimum-variance portfolio (PR-023), and
stress-tests the result -- confirming the estimated-beta stress loss
converges to the one computed from the ground-truth betas.

Not covered: no scenario is calibrated from real historical crisis data or
hard-coded as a named "2008"/"2020"-style event -- callers supply their
own `StressScenario` definitions; `historical_scenario_losses` replays a
supplied returns matrix generically, with no opinion about which rows
represent a crisis; no network-contagion (RISK-11) analysis -- see PR-031
below; full concentration decomposition (RISK-12) remains partial; and
like every other `titan.*` module, this one is standalone -- not wired
into `StepHooks` or any orchestration runner.

23 new tests, ruff/mypy --strict clean, 100% line coverage on the new
module, 955 tests passing project-wide.

## Evidenced today (PR-031: interbank network contagion)

`titan.contagion` adds Eisenberg & Noe's (2001) fixed-point clearing
payment vector for a network of banks linked by interbank liabilities:
each bank pays the lesser of what it owes and what it actually has
available (external assets plus whatever its own debtors pay it),
computed via the proven monotone-decreasing iteration starting from full
payment. `network_concentration` adds a second, partial RISK-12 building
block: the Herfindahl-Hirschman index of each bank's debtor/creditor
interbank exposures.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| RISK-11 | network contagion / default-cascade simulation across interbank exposures | `titan.contagion.eisenberg_noe_clearing`; `test_three_bank_cascade_fully_defaults_down_the_chain` is a fully hand-derived worked example (A owes B owes C, A and B undercapitalized) matching exact expected payments, shortfalls and creditor losses -- not just a plausible-looking result; `test_clearing_vector_is_a_genuine_fixed_point_on_random_networks` independently re-verifies, for 10 random 5-bank networks, that the reported payments truly satisfy the fixed-point equation when recomputed from scratch outside the module |
| RISK-12 (partial) | concentration decomposition of interbank exposure | `network_concentration`'s Herfindahl-Hirschman index per bank, both as debtor and as creditor; exact known values confirmed (a single counterparty gives HHI=1.0, an equal two-way split gives exactly 0.5) |

A genuine economic distinction many simpler contagion models miss is
captured and tested explicitly: a bank that owes nothing itself
(`nominal_obligations=0`) can never show a "debtor shortfall" even when a
counterparty default wipes out money it was counting on receiving --
`creditor_loss` (nominal claims minus actually received) is tracked as a
separate, independent quantity precisely to catch this, confirmed in the
three-bank cascade test where the terminal bank's `defaulted` is `False`
throughout even as it absorbs a full `creditor_loss`. A known, documented
(not hidden) degeneracy is tested directly rather than discovered by
surprise: a pure liability ring with zero external assets anywhere
converges to the trivial full-payment vector, the economically-empty
"Ponzi cycle" case Eisenberg & Noe's own paper acknowledges.

Not covered: no sequential-default / "least clearing vector" tie-breaking
for the degenerate pure-cycle case described above; no multi-period or
dynamic contagion (this is a single, static clearing round); at the time
of this PR, no connection to `econosim.central_bank_ledger`/`econosim.agents.Bank`
-- this module takes a plain liabilities matrix and external-assets
vector, not live ledger balances -- PR-032 below adds exactly that
adapter; and like every other `titan.*` module, standalone, not wired
into `StepHooks` itself.

26 new tests, ruff/mypy --strict clean, 100% line coverage on the new
module, 981 tests passing project-wide.

## Evidenced today (PR-032: econosim-to-titan contagion adapter)

`econosim.network_risk` is the first connection anywhere in this
repository between ECONOSIM-X's simulated banking system and TITAN's
systemic-risk analytics: `build_contagion_network` reads live `Bank`/
`CentralBankLedger` ledger state and produces exactly the liabilities
matrix and external-assets vector PR-031's `eisenberg_noe_clearing`
needs, with the central bank itself included as one more node in the
network rather than a bolted-on special case (its reserve liabilities TO
banks, and the discount-window loans banks owe IT, are genuine
interbank-style obligations). `run_contagion_analysis` composes the two
steps for callers that don't need the intermediate network.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| RISK-11 (extended) | contagion analysis against a real, live simulated banking system, not only synthetic matrices | `test_network_matches_hand_computed_values_for_a_well_capitalized_scenario` hand-derives every matrix entry and external-asset value from a real `Bank`/`CentralBankLedger` sequence of operations and confirms an exact match; `test_connects_to_a_full_monetary_operations_scenario` runs PR-028/029's real `StepHooks`-driven scenario for 24 steps and clears the resulting live network end to end |

The adapter's own correctness is demonstrated with a genuine systemic-risk
failure mode, not just a healthy baseline:
`test_central_bank_itself_can_default_when_undercapitalized` has the
central bank issue discount-window reserves to one bank with no
securities backing them; that bank drains the reserves to a second bank
via interbank settlement; the central bank itself then cannot cover the
resulting reserve liability and is correctly reported as `defaulted`,
with the second bank (which owed nothing itself) showing zero shortfall
but a real, nonzero `creditor_loss` -- exactly the distinction PR-031's
`ClearingResult` was designed to capture, now triggered by a real,
undercapitalized central bank rather than a synthetic matrix. A
double-counting trap was deliberately avoided, not just noticed: a bank's
`cb_settlement_balance` is excluded from its external assets, since it is
already represented as the central bank's reserve-liability edge to that
bank -- counting it twice would have inflated every well-capitalized
scenario's apparent resilience.

Not covered: at the time of this PR, there was still no direct
bank-to-bank lending instrument in `econosim.agents`, so every
off-diagonal bank<->bank liability entry was exactly zero regardless of
ledger state -- PR-033 below adds exactly that instrument;
`build_contagion_network` is a point-in-time snapshot, not wired into
`StepHooks` as its own step or run automatically alongside a
`MonetaryOperationsProcess`'s loop.

7 new tests, ruff/mypy --strict clean, 100% line coverage on the new
module, 988 tests passing project-wide.

## Evidenced today (PR-033: direct bilateral interbank lending)

`econosim.interbank_market.InterbankMarket` is the direct bank-to-bank
lending instrument PR-032's own docstring flagged as the one remaining
gap: unlike `CentralBankLedger` (every bank relates to ONE shared central
bank), `InterbankMarket` lends directly BETWEEN arbitrary pairs of `Bank`
agents, with per-(lender, borrower)-pair linked accounts opened lazily --
not one aggregate payable/receivable balance per bank, which could not
tell a contagion analysis WHO a bank owes if it borrowed from several
different counterparties. `econosim.network_risk.build_contagion_network`
gained an optional `interbank_market` parameter that reads these genuine
bilateral exposures directly into the liabilities matrix.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| ECO-09 (extended) | direct bank-to-bank credit extension, subject to the lender's own capital/leverage cap | `InterbankMarket.lend`/`repay`; `test_lend_rejects_amount_exceeding_lender_leverage_cap` confirms a bank that borrowed heavily from a third party (boosting its reserves but not its capital) is still capped by its OWN capital when relending, not by how much cash happens to be sitting in its account |
| RISK-11 (extended) | contagion analysis incorporating genuine, non-zero bank-to-bank exposures | `test_interbank_market_populates_genuine_bilateral_bank_edges` confirms the liabilities matrix now carries real directional bank<->bank entries; `test_distinct_pairs_get_distinct_linked_accounts_not_an_aggregate` confirms borrowing from two different lenders is tracked independently, not netted |

A genuine, real-world-relevant limitation of ANY partial-sample stress
test is demonstrated end to end from real ledger mechanics, not just
asserted: `test_restricted_sample_network_can_miss_a_bank_s_true_resources`
has bank_a borrow $1000 from bank_b, then relend all of it to bank_d -- a
bank deliberately excluded from the analyzed network. Because the
adapter only sees banks in the supplied list, bank_a's legitimate
receivable from bank_d is invisible to it, so bank_a is correctly shown
defaulting on its debt to bank_b within this restricted view, even though
a fuller analysis including bank_d would show it holds a covering asset.
This mirrors a well-known real-world issue with partial-coverage stress
tests, reproduced here from first principles rather than cited.

A deeper finding from building this module, documented rather than
hidden: a pure interbank loan is, by construction, a symmetric
asset/liability pair, so a simple lending chain can never by itself
create a shortfall within one static clearing snapshot unless the
borrowed funds are spent on something invisible to the analyzed network
(as in the restricted-sample case above) or a pre-existing obligation
already consumed them before the snapshot -- genuine default risk in this
model always traces back to an asymmetric event, not symmetric lending
alone.

17 new tests (14 in `test_interbank_market.py`, 3 added to
`test_network_risk.py`), ruff/mypy --strict clean, 100% line coverage on
both the new module and the extended `network_risk.py`, 1005 tests
passing project-wide.

## Evidenced today (PR-034: continuous systemic-risk monitoring in StepHooks)

`econosim.monetary_operations` (PR-028/029) is extended with a genuine
direct interbank loan (`InterbankMarket`, bank_a lending to bank_b,
amortized on its own independent schedule exactly like the discount
window) and a periodic LIVE systemic-risk check: every
`contagion_check_every` steps, `network_risk.run_contagion_analysis`
clears the real two-bank-plus-central-bank network and the result is
recorded directly in that step's settlement -- continuous risk monitoring
integrated into a running simulation, not a one-off offline analysis
bolted on afterward.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| RISK-11 (extended) | systemic-risk monitoring integrated into a live, running simulation loop, not only an offline snapshot | `MonetarySettlement.contagion_check` (a JSON-safe `ContagionCheckSummary`, deliberately avoiding embedding `ClearingResult`'s numpy arrays in an exported evidence payload); `test_periodic_contagion_check_detects_a_genuine_default` directly engineers a real default inside a running `MonetaryOperationsProcess` and confirms the process's OWN wired-in check -- not `network_risk` tested in isolation again -- reports it |
| ECO-16 (extended) | a capacity-constrained operation that CAN fail is skipped and recorded, never allowed to crash the step | a genuine bug caught by writing this PR's own tests, fixed before being evidenced as done: the interbank loan's "lend" branch was initially unguarded (copied from the discount window's unconditional, uncapped central-bank lending, which structurally cannot fail) even though `InterbankMarket.lend` -- real bank capital/leverage, real reserves -- genuinely can; `test_clear_and_settle_skips_interbank_loan_gracefully_when_lender_lacks_capacity` now exercises exactly that path |

10 new tests, ruff/mypy --strict clean, 100% line coverage on the
extended module, 1015 tests passing project-wide. The full CLI/evidence-
export/replay round trip (PR-029's wrapper) was re-verified end to end
against the richer scenario, including the new nested `ContagionCheckSummary`
field, with no changes needed to the orchestration layer itself.

Not covered: the interbank loan is always bank_a lending to bank_b in one
fixed direction, not a dynamic/bidirectional interbank market; the
contagion check only ever covers the two banks already in this scenario
plus the central bank -- it cannot detect exposure to any bank outside
this fixed pair (the same restricted-sample limitation PR-033 itself
documented); and, at the time of this PR, the check result was recorded
but not ACTED on -- PR-036 below adds exactly that.

## Evidenced today (PR-035: position book with snapshot linkage)

`titan.positions` adds the first position book anywhere in this
repository: a `Position` records what was originally entered -- an
`EuropeanOption`, a signed quantity, the exact `MarketSnapshot` it was
entered against, and its per-unit entry price -- and `value_position`/
`value_book` mark it (or a whole `PositionBook`) to a CURRENT snapshot and
instrument, computing mark price, market value and unrealized P&L.
Deliberately does not invent a new day-count convention to decay
maturity from calendar dates: the caller supplies the current
instrument's own remaining maturity explicitly, the same way
`multi_step_run.py` already recomputes `remaining_years` itself each
step, rather than this module guessing at an actual/365 rule inconsistent
with the rest of the repository.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| RISK-01 | a position book linking positions to the market snapshot they were entered and valued against | `titan.positions.Position`/`PositionBook`/`value_book`; `test_value_book_aggregates_a_long_and_a_short_position_correctly` confirms a multi-position book's long and short legs are valued and summed independently, matching a direct recomputation |
| RISK-13 | stale-snapshot rejection | `StaleSnapshotError`, raised in two independent, separately tested cases: a current snapshot dated before the position's own entry snapshot (structurally nonsensical -- you cannot mark to data from before the position existed), and, when the caller supplies an `as_of`/`max_staleness_days` tolerance, a snapshot older than that tolerance relative to `as_of` |

A correctness check many simpler mark-to-market shims skip is enforced
directly, not assumed: `current_instrument`'s strike and option type must
match the position's original contract exactly (`InstrumentMismatchError`
otherwise) -- only remaining maturity may differ -- and a
`current_instrument` whose remaining maturity EXCEEDS the position's
original maturity (time running backward) is rejected with a plain
`ValueError`, confirmed in its own test.

The practical payoff is demonstrated end to end, not just asserted:
`test_connects_to_titan_risk_metrics_for_a_real_var_pipeline` marks a
position to 200 simulated daily spot moves, builds a realized daily P&L
series from the resulting market values, and feeds it directly into
PR-006's already-evidenced `titan.risk_metrics.historical_var` -- composing
a pricing-layer module (VOLTERRA) with a risk-layer module (TITAN) for
the first time via this position book, rather than each being tested in
isolation.

Not covered: at the time of this PR, only `EuropeanOption` positions were
supported -- PR-037 below adds a second instrument type; a `PositionBook`
is a plain in-memory collection, not persisted or linked to
`core.ledger`/`econosim` in any way; no realized-P&L/close-out accounting
(every P&L figure here is unrealized, mark-to-market only); and like
every other `titan.*` module, standalone -- not wired into `StepHooks` or
any orchestration runner.

19 new tests, ruff/mypy --strict clean, 100% line coverage on the new
module, 1034 tests passing project-wide.

## Evidenced today (PR-036: a risk circuit breaker that acts on detected defaults)

`econosim.monetary_operations`'s periodic contagion check (PR-034) is
extended to ACT on what it finds, not just record it: a one-way circuit
breaker (`MonetaryOperationsProcess._risk_frozen`) is set the first time
the check ever detects a default, and never automatically clears. While
frozen, no NEW discount-window or interbank loan is extended for the rest
of the run -- a deliberately limited response, not a full shutdown: OMO
and interbank reserve transfers (reallocating existing reserves, not
extending new unsecured credit) are unaffected, and existing debt still
amortizes exactly on its original schedule.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| ECO-16 (extended) | a detected risk condition changes future behavior, not just future reporting | `test_a_detected_default_freezes_future_new_lending_but_not_repayment` engineers a real default, confirms the check detects it, and then confirms a discount-window loan scheduled for a LATER step is never extended even though nothing about that specific request changed -- only the process's own risk state did |
| RISK-11 (extended) | systemic-risk detection feeding back into subsequent decisions, not a dead-end report | `test_frozen_state_does_not_block_amortization_of_existing_debt` confirms the freeze is scoped correctly: a loan taken out BEFORE the freeze continues amortizing normally afterward -- the breaker suspends new credit, not existing obligations |

The freeze decision is causal by construction, not merely by convention:
it is set at the END of `clear_and_settle` (after a check detects a
default) and only ever consulted at the START of the NEXT step's
`compute_actions` -- a step's own lending decision can never be
influenced by information only available at the end of that same step,
consistent with the no-lookahead discipline this repository already
enforces everywhere else (`PointInTimeStore`, `titan.rebalancing`'s
trailing-window estimation).

4 new tests, ruff/mypy --strict clean, 100% line coverage on the extended
module, 1038 tests passing project-wide. The full CLI/evidence-export/replay
round trip was re-verified end to end with the new `risk_frozen` field, no
orchestration-layer changes needed.

Not covered: the freeze never automatically lifts, even if the defaulting
exposure is later fully resolved (a one-way breaker, not a
resolution/recovery regime); it only suspends NEW lending by THIS
process's two fixed instruments -- it does not, for example, also halt
OMO activity, even for a central-bank-side default; and there is no
graduated response (e.g., partial lending limits) between "normal" and
"fully frozen."

## Evidenced today (PR-037: forward contracts, a second instrument type)

`volterra.instruments` gains `ForwardContract` (a fixed delivery price
and remaining maturity) and `volterra.forwards` prices it by cost of
carry: a brand-new contract's fair delivery price is `F = S * exp((r-q)T)`,
and an existing contract's value is `S*exp(-qT) - K*exp(-rT)`.
`titan.positions` (PR-035) is generalized from `EuropeanOption`-only to
`Instrument = EuropeanOption | ForwardContract`, closing that PR's own
"only EuropeanOption positions are supported" admission -- a `Position`,
a `PositionBook`, and the identifying-terms/stale-snapshot checks all
work unchanged for either instrument kind.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| PRI-01 (extended) | a second versioned instrument specification, cost-of-carry priced | `volterra.forwards.forward_price`/`forward_contract_value`; `test_contract_value_matches_the_equivalent_f_minus_k_formulation` cross-checks the direct `S*exp(-qT) - K*exp(-rT)` formula against the economically equivalent `(F_now - K) * exp(-rT)` form -- two independently-derivable expressions for the same no-arbitrage value, not the same code checked against itself; `test_a_freshly_entered_contract_is_worth_exactly_zero` confirms the defining property of a fair forward price directly |
| RISK-01 (extended) | a position book that generalizes across instrument types, not hard-coded to one | `test_position_book_can_mix_option_and_forward_instruments` builds and values a book holding BOTH an option and a forward position in one call; `test_cross_type_reprice_is_rejected_both_ways` confirms an option position cannot be repriced as a forward, and vice versa -- the instrument's TYPE itself is checked, not only its identifying terms |

12 new tests (7 in `test_forwards.py`, 5 added to `test_positions.py`),
ruff/mypy --strict clean, 100% line coverage on `forwards.py` and the
extended `positions.py`, 1050 tests passing project-wide.

Not covered: at the time of this PR, no American-style early exercise
existed anywhere -- PR-038 below adds it; no futures-specific daily
margining/mark-to-market settlement (this is a forward, settled only at
maturity, not a futures contract); forward contracts are still only
priced against a flat risk-free rate and dividend yield, with no
convenience-yield or storage-cost term for commodities; and `Instrument`
remains a closed union of exactly two types -- adding a third still
requires touching `_price`/`_identifying_terms_match` by hand, not a
plugin/registry mechanism.

## Evidenced today (PR-038: American options via a binomial tree)

`volterra.american_options` adds `AmericanOption` (a genuinely distinct
instrument from `EuropeanOption`, not an exercise-style flag on the same
one) and prices it with a Cox-Ross-Rubinstein binomial tree -- the first
non-closed-form, non-Monte-Carlo pricing method in this repository.
`european_binomial_price` runs the IDENTICAL tree with early exercise
disabled, which is what makes the cross-checks below meaningful: they
compare the same code path differing only in one comparison, not two
independently-written pricers that might happen to agree by coincidence.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| PRI-01 (extended) | a third versioned instrument specification, priced by a distinct numerical method | `instruments.AmericanOption`; `american_options.american_binomial_price`/`european_binomial_price` |
| SDE-* (lattice/tree numerical method, extending the project's Monte Carlo + closed-form pricing methods) | `test_european_binomial_price_converges_to_black_scholes` confirms the tree's error shrinks monotonically (50 -> 200 -> 800 steps) toward PR-005's already-evidenced closed-form price, to below 1 cent at 800 steps -- a genuine numerical-convergence check, not a single-tolerance pass/fail |

Two independently-known theorems from option-pricing theory are used as
correctness cross-checks, not just plausibility checks, each tested as
the EQUALITY or INEQUALITY it actually is:
`test_american_call_equals_european_call_with_no_dividends` confirms
Merton's classical result -- early exercise of a call is never optimal
without dividends -- holds to `1e-9`, an equality, not an approximate
inequality; `test_american_call_exceeds_european_call_when_dividends_make_early_exercise_valuable`
and `test_american_put_never_cheaper_than_the_european_put` confirm the
corresponding strict inequalities hold once early exercise genuinely
matters. A deep in-the-money American put's price is also confirmed
never to fall below its immediate-exercise intrinsic value -- a property
the backward induction's own `max(continuation, intrinsic)` step
guarantees by construction, checked directly rather than merely trusted.

12 new tests, ruff/mypy --strict clean, 100% line coverage on the new
module (and on `AmericanOption`'s own validation), 1062 tests passing
project-wide.

Not covered: at the time of this PR, `AmericanOption` was not yet wired
into `titan.positions` (PR-035/037) -- PR-039 below adds exactly that;
no Greeks (analytical or finite-difference) for American options; the
tree is O(n_steps^2) with no speedup (no finite-difference PDE solver,
no Richardson extrapolation); and only a flat volatility/rate term
structure is supported, matching every other pricing module in this
repository.

## Evidenced today (PR-039: American options in the position book)

`titan.positions` (PR-035/037) is generalized a second time:
`Instrument` is now `EuropeanOption | ForwardContract | AmericanOption`,
closing PR-038's own "not yet wired into titan.positions" admission.
Binomial pricing needs an `n_steps` the two closed-form instruments
don't -- `value_position`/`value_book` gained an optional `n_steps`
parameter, required (with a clear, specific error raised before any
pricing is attempted) exactly when the instrument being valued is an
`AmericanOption`, and silently unneeded otherwise, so no existing caller
of either function needed to change.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| RISK-01 (extended) | a position book generalizing across THREE instrument types sharing one API, not hard-coded to one or two | `test_position_book_can_mix_all_three_instrument_types` builds and values a book holding a European option, an American option and a forward in one call; `test_american_vs_european_with_identical_strike_and_type_is_a_mismatch` confirms that even with IDENTICAL strike and option type, an `AmericanOption` and a `EuropeanOption` are different instrument TYPES and repricing one as the other is rejected -- the same discipline PR-037's forward/option check already established, now proven to generalize to a third type rather than being special-cased for two |

`test_n_steps_is_not_required_for_european_or_forward_positions`
confirms the new parameter is purely additive: every existing call
pattern for the two closed-form instruments continues to work completely
unchanged with `n_steps` omitted or `None`.

5 new tests, ruff/mypy --strict clean, 100% line coverage on the
extended module, 1067 tests passing project-wide.

Not covered: `value_book` applies one shared `n_steps` to every American
position in a book -- a book wanting different tree resolutions for
different American positions must call `value_position` individually;
and at the time of this PR, no Greeks existed for American options at
all -- PR-040 below adds exactly that.

## Evidenced today (PR-040: Greeks for American options)

`volterra.american_greeks` adds delta/gamma/vega/theta/rho for American
options. Delta and gamma are extracted from a SINGLE binomial tree's own
early nodes (the standard CRR technique), not by bumping spot and
rebuilding the tree -- a genuine numerical pitfall was discovered and
confirmed empirically before choosing the better method, not assumed:
naive central differences on an independently-rebuilt tree are wildly
wrong even with a "reasonable-looking" small bump, because the tree
price is a piecewise-linear (kinked), not smooth, function of spot.
`american_options.py` was refactored to expose `crr_parameters` and
`binomial_tree_values(..., stop_at_step=...)` as shared public
primitives, so both pricing and Greeks extraction build on the identical
backward induction rather than two separately-written tree-walkers that
could silently drift apart.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| VAL-05 (extended) | Greeks for a non-closed-form instrument, cross-checked for correctness | `test_naive_spot_bumped_central_difference_gamma_does_not_converge` demonstrates the broken approach directly (gamma off by more than 10x using a bump on the same scale `greeks_fd.py` already uses successfully for the smooth Black-Scholes price) BEFORE the correct method's own convergence test runs, so the fix is proven necessary, not merely elegant |
| PRI-01 (extended) | American-option sensitivities validated against the closed-form reference in the degenerate (no-dividend) case | `test_full_greeks_converge_to_black_scholes_for_a_no_dividend_call` confirms ALL FIVE Greeks (not just delta) converge to PR-005's analytical Black-Scholes Greeks, since PR-038 already proved the two PRICES are identical without dividends -- the same equality theorem, extended to its derivatives |

Convergence is tested as a genuine numerical property, not a single
pass/fail tolerance: `test_delta_gamma_error_shrinks_monotonically_with_more_steps`
confirms the gamma error strictly decreases across 100 -> 500 -> 2000
tree steps.

12 new tests (10 in `test_american_greeks.py`, 2 added to
`test_american_options.py` to re-cover a validation branch the earlier
refactor made unreachable through its original call path), ruff/mypy
--strict clean, 100% line coverage on both the new module and the
refactored `american_options.py`, 1079 tests passing project-wide.

Not covered: vega/theta/rho still use ordinary bump-and-reprice (full
tree rebuild), which works here because rebuilding on volatility/time/
rate doesn't share delta/gamma's spatial-lattice pathology -- but it is
still a less rigorous construction than the tree-native delta/gamma
extraction, and no analogous "read it off one tree" trick is applied to
them; Greeks are still not exposed through `titan.positions` at all (for
any instrument type); and the tree-native delta/gamma technique reads
sensitivities at `t=2*dt`, not exactly `t=0` -- an approximation that
vanishes as `n_steps` grows, confirmed by convergence, but not algebraically
eliminated.

## Evidenced today (PR-041: unifying the central bank)

`econosim.central_bank_ledger.CentralBankLedger` can now OPTIONALLY be
constructed with a `rate_rule`/`initial_rate` (the exact same
`policy_rate.PolicyRateRule` the standalone wrapper uses), giving ONE
object that is both the policy-rate setter and the ledger-backed balance
sheet, via a new `step_rate(shocks)` method. `policy_rate.CentralBank`
itself is completely unchanged, and `CentralBankLedger` built WITHOUT the
new kwargs behaves exactly as before -- this is a pure addition, not a
breaking refactor. `Economy.add_central_bank_ledger` gained the matching
optional kwargs.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| ECO-05 (extended) | one central-bank agent combining a policy-rate process and a real balance sheet | `CentralBankLedger.step_rate`; `test_step_rate_matches_the_standalone_central_bank_wrapper_exactly` confirms bit-for-bit agreement (`abs(...) < 1e-15`) against `policy_rate.CentralBank.step` across 12 steps including a shocked one -- proving `step_rate` calls the SAME `PolicyRateRule.step`, not a reimplementation that could silently drift |

A genuine, previously-latent limitation was surfaced while building this
-- not introduced by it, but newly worth documenting now that unifying
the central bank makes it more likely to matter: `register_bank`'s
linked account names are keyed only by the bank's `agent_id`, not by
`(central_bank_id, bank_id)`, so one `Bank` can be registered with at
most one `CentralBankLedger` per `Ledger` -- a second registration
raises `core.ledger.DuplicateAccountError`, confirmed directly in
`test_a_bank_cannot_be_registered_with_two_different_central_banks`
rather than left for a future multi-central-bank scenario to discover by
surprise.

9 new tests, ruff/mypy --strict clean, 100% line coverage on the extended
`central_bank_ledger.py`, 1088 tests passing project-wide.

Not covered: at the time of this PR, `econosim.monetary_operations` still
constructed its rate-only `CentralBank` and its `CentralBankLedger`
SEPARATELY under different agent_ids -- PR-042 below migrates that
scenario to the unified constructor; the one-`Bank`-per-`CentralBankLedger`
limitation above remains documented, not fixed (no account-namespacing-
by-central-bank exists).

## Evidenced today (PR-042: monetary_operations migrated to the unified central bank)

`econosim.monetary_operations.MonetaryOperationsProcess` is migrated to
PR-041's unified `CentralBankLedger`: the scenario's original two-object
split (a bare rate-only `policy_rate.CentralBank` under agent_id
`"cb_rate"` deciding the rate, a separate `CentralBankLedger` under
`"cb"` executing every operation) is replaced by ONE `CentralBankLedger`
constructed with `rate_rule`/`initial_rate`, closing PR-041's own
deliberately-deferred remaining admission. `compute_actions` now calls
`step_rate` directly on the same object `clear_and_settle` already
operates on, rather than threading two separate agent references through
the process.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| ECO-05 (extended) | a real scenario (not just a unit test) using ONE central-bank agent for both the rate decision and the balance sheet | `test_process_uses_one_unified_central_bank_for_both_rate_and_balance_sheet` confirms `central_bank_rate` no longer exists as a separate attribute and `central_bank_ledger.tracks_policy_rate` is `True` from construction; the full CLI/evidence-export/replay round trip (PR-029) was re-verified end to end against the migrated scenario with an unchanged result structure |

This was a small, well-contained migration, not a risky rewrite: only
three call sites inside `monetary_operations.py` itself referenced the
old split (`__init__`, and two lines in `compute_actions`), and exactly
one existing test asserted the now-obsolete "two different agent_ids"
behavior -- found immediately by running the existing suite, not
discovered later. 100% line coverage and the full seeded/shocked
scenario's qualitative behavior (OMO direction, discount-window
amortization, contagion checks) were reconfirmed unchanged after the
migration, not merely assumed from the diff.

1 new test, ruff/mypy --strict clean, 100% line coverage on the migrated
module, 1089 tests passing project-wide.

Not covered: `policy_rate.CentralBank` and the rate-only construction
path remain available and still used by OTHER orchestration scenarios
(`multi_step_run.py`, `monetary_run.py`, etc.) -- only this one scenario
was migrated; the one-`Bank`-per-`CentralBankLedger` limitation PR-041
documented is unaffected by this PR either way, since this scenario only
ever had one central bank to begin with.

## Evidenced today (PR-043: interest accrual and loan write-off)

`econosim.agents.Bank` gains two new methods, additive to the already-
tested, committed `originate_loan`/`receive_repayment` pair, not a
modification of either: `accrue_interest` (LED-05) capitalizes unpaid
interest directly into the loan balance each period -- a simplified,
explicitly-documented convention (not a fixed-payment amortization
schedule) -- via the same four-posting, two-sector pattern
`originate_loan` already uses, just moving no cash; `write_off_loan`
(LED-06) extinguishes a specific borrower's debt without repayment,
recognizing a realized loss on the bank's own equity and the accounting-
correct debt-forgiveness gain on the borrower's. Both are written against
the shared `Borrower` protocol (now additionally requiring an
`equity_account`), so Government goes through the identical code path as
Household, exactly like the two pre-existing methods already do.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| LED-05 | interest accrual and amortization schedule, reference cash-flow tests match documented convention | `Bank.accrue_interest`; `test_accrue_interest_compounds_across_multiple_periods` hand-verifies exact compounding (`1000.00 * 1.01^3 = 1030.301` rounding to `1030.30`) over three periods, not a single-period smoke test |
| LED-06 | loan loss, write-off and recovery; counterparty receivable/payable and equity reconcile | `Bank.write_off_loan`; `test_write_off_loan_extinguishes_debt_and_reallocates_equity` confirms the realized loss on the bank's equity and the debt-forgiveness gain on the borrower's equity are EXACTLY equal and opposite, both to the written-off amount |

A correctness property many simpler write-off implementations miss is
caught and tested explicitly: `write_off_loan` validates against the
SPECIFIC borrower's own outstanding balance, not the bank's aggregate
`loans_account` (which pools every borrower together) --
`test_write_off_loan_rejects_amount_exceeding_borrowers_own_balance`
confirms one borrower's smaller debt cannot be written off for more just
because a DIFFERENT borrower at the same bank owes more, and that the
rejected attempt leaves both borrowers' balances completely unchanged.

10 new tests, ruff/mypy --strict clean, 100% line coverage on the two new
methods (the only pre-existing gaps in `agents.py` are unrelated
`Government` validation branches, unaffected by this PR), 1099 tests
passing project-wide. The change is purely additive: the full project
test suite was re-run before AND after, confirming zero regressions, and
`Borrower`'s protocol extension (`equity_account`) required no changes to
`Household`/`Government`, which already had that attribute.

Not covered: `write_off_loan` is a single-creditor primitive, not the
full multi-creditor insolvency/loss waterfall with creditor-priority
ranking LED-07 actually asks for (`Loss waterfall tests pass prescribed
creditor priority`) -- that arrived separately in PR-049
(`econosim.insolvency`), below; interest accrual has no
fixed-payment/level-principal amortization schedule, only capitalizing
compounding; and nothing in this repository yet calls these two new
methods from any `StepHooks` scenario or orchestration runner -- they
exist on `Bank` and are tested standalone, exactly like every other
capability was before its own first caller.

## Evidenced locally (PR-044: empirical macro/market-mixture tail risk)

`orchestration.mixture_study` adds a distinct, declared risk endpoint to
the matched rate-feature experiment. It collects terminal losses once,
pools each fitted model's macro/market outcomes before CVaR, then averages
comparator-minus-aware CVaR differences across retrainings. Models are
never pooled into a synthetic ensemble. All previous local changes through
PR-043 remain present and are included in project-wide validation.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| RISK-04 (extended, empirical macro mixture) | fractional/tied tail estimator across equal-weight macro banks | `test_mixture_bootstrap.py::test_fractional_tail_and_ties_match_an_independent_weighted_tail`, `test_macro_mixture_can_reverse_the_mean_conditional_risk_conclusion`, `test_fitted_policies_are_not_pooled_into_an_ensemble_before_cvar` |
| EXP-07 (extended, nested paired design) | preserve training, shared macro and within-bank market dependence | `test_nested_draws_match_a_separate_loop_based_reconstruction`; `test_constant_shift_is_preserved_in_every_nested_and_conditional_resample`; tests confirm macro/training uncertainty survives increasing conditional path counts |
| EXP-01 / EXP-08 / EXP-10 (extended, approximate inference) | declared estimand/contrasts, economic margin and separate family allocation | `mixture_study.ENDPOINT`; new mixture scenario/contrast family uses nominal Bonferroni allocation; source conditional intervals remain auxiliary and cannot select the new endpoint/verdict |
| EXP-03 / AUD-02 (extended) | nested resampling cannot change training, prices or original risk results | `test_nested_settings_never_change_training_data_models_or_loss_samples`, `test_axis_order_cannot_change_results`; copied loss vectors/cubes are fingerprinted against original cells |
| ECO-16 / AUD-11 (extended) | fail explicitly on malformed samples, numeric overflow and failed source experiment | `test_numeric_overflow_is_rejected_instead_of_emitting_an_infinite_risk_claim`, invalid shape/non-finite/control fixtures; `test_failed_macro_experiment_produces_no_mixture_inference_and_replays`; invalid CLI recipe preserves existing output |
| AUD-02 (extended) | full loss samples independently reconstruct risk points and actual replay | `test_exported_loss_cubes_reconstruct_mixture_and_conditional_cvar_points`, `test_actual_replay_retrains_and_recomputes_nested_risk_and_samples`; generic replay coverage now includes the mixture payload alongside existing runners |

The nested bootstrap samples training rows, macro banks and conditional
market indices within each drawn bank occurrence. Every row and hedge arm
shares the selected bank/path pairs; repeated draws of one bank receive
fresh within-bank samples. Single-axis intervals condition on other axes
and are diagnostics, not an additive variance decomposition. The design
does not implement a temporal block bootstrap -- that capability is added
later, as a separate, standalone module, see PR-076 below.

Loss cubes have explicit (training, macro bank, conditional market path)
axes, equal bank/path weights and hashes. The original conditional-study
payload/hash remains embedded for lineage. Policy model cards retain their
original metrics and add per-model empirical-mixture CVaR. No scientific
approval or full industrial/deployment readiness is inferred from tests.
The supplied PDF matches the repository blueprint byte-for-byte; its
deployment/review controls remain requirements, not automatic certification.

This is a finite empirical macro mixture, not calibrated unconditional
population risk. Small independent macro/training samples and uncalibrated
nested-percentile coverage remain material limitations. See
[`evidence/validation_pr044.md`](./evidence/validation_pr044.md).

## Evidenced locally (PR-045: artifact integrity and full-scope traceability)

New exports seal a detached JSON snapshot of the entire artifact, not only
the computational payload. The offline auditor validates integrity,
metadata structure and model-card/training fingerprint consistency without
running numerical simulation or fitting models. Legacy artifacts remain
explicitly identifiable. All work is local and pending independent review.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| GOV-04 (partial, full inventory) | retain every requirement and its acceptance evidence target | `evidence.requirements` extracts all 374 IDs in 29 categories with requirement/acceptance text, source page and unreviewed repository-note links; parser rejects duplicates, missing rows and wrong cardinality; no P0/full acceptance is asserted |
| AUD-01 / AUD-02 (extended, unsigned integrity) | detect metadata changes and bind model fingerprints to declared training | `test_evidence_integrity.py` covers every section, external content pins and seal schemas; `test_evidence_validation.py` rejects mismatched/missing/duplicate cards and malformed provenance |
| AUD-11 (extended) | refuse malformed evidence before changing the destination | stale seals and invalid metadata preserve existing files and leave no temporary output; sealed snapshots detach nested mutable input; existing atomic-replace failure tests remain in force |
| MLO-09 / DOC-06 (extended) | model-card metrics and reviewer fields have enforceable schema | finite numeric metrics, explicit conditional/approved reviewer names; malformed dates, boolean approvers and reversed gate sunset dates are rejected |
| AUD-08 (extended) | source/disclaimer and gate context survive complete export/readback | shared contract reader validates all artifact sections; computational result hashes remain unchanged; strict audit rejects seal stripping, while legacy access requires explicit opt-in |
| EXP-03 / VAL-09 (extended) | retain reproducibility while strengthening export integrity | all supported replay fixtures exercise strict sealed replay and explicit legacy rejection; runtime changes still differ from computational result mismatches |

The register is an exhaustive scope inventory, not an automatic acceptance
claim. Every blueprint requirement retains NOT VERIFIED status with no
invented owner/reviewer. Linked notes do not prove the requirement is fully
implemented or independently approved. The implementation plan preserves
all categories, including separately gated external/live requirements.

The checksum format is explicitly Python sorted-key JSON v1, not a digital
signature or cross-language canonical-JSON guarantee. A recomputed unsigned
checksum cannot prove authorship. An externally trusted content pin can
detect substituted content; trust in that pin is outside this tool. Offline
audit performs the checks named in its output; actual numerical replay and
independent model review remain separate requirements. See
[`evidence/validation_pr045.md`](./evidence/validation_pr045.md).

## Evidenced locally (PR-046: bounded durable local research jobs)

The common recipe registry now drives replay and local job execution for
all nine research runners. A transactional SQLite queue, fenced Linux
process workers and content-addressed artifact store provide actual local
execution/recovery, not just queue-shaped test doubles. This is a backend
foundation; HTTP authentication/routes and deployment acceptance remain open.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| MLO-01 (partial, local typed recipes) | complete typed/versioned execution configuration | immutable runner allowlist, canonical recipe fingerprints and all existing strict decoders; `test_recipe_registry.py` covers defaults, missing/unknown fields and resource preflight; committed release config acceptance remains pending |
| API-02 (partial, pre-HTTP validation) | reject malformed/oversized requests with precise causes | complete dataclass decoding, structure/precision and aggregate work admission; service 4xx/OpenAPI mappings are not yet implemented |
| API-03 (partial, local jobs) | persistent unique/replayable jobs with scoped lookups | `test_job_store.py::test_persistence_idempotency_conflicts_and_owner_visibility`; actual worker/artifact round trip; owner filters rely on trusted operator/OS access, not network authentication |
| API-04 (partial, execution controls) | bound workloads, cancellation and orphan recovery | queue/work/byte budgets, Linux wall/CPU/file controls, token fencing; real timeout, running cancellation, parent-death and recovery tests; hard RSS/cgroup and per-period quotas remain open |
| API-06 (partial, backend idempotency) | retries must not create duplicate jobs | sixteen concurrent identical submissions return one transactional job; conflicting request reuse is rejected; HTTP endpoint acceptance remains pending |
| API-07 (partial, job diagnostics) | distinguish validation/model/infrastructure failures | typed submission errors plus terminal structured error codes and diagnostic IDs; malformed requests preserve existing state; HTTP diagnostic response envelope remains open |
| API-11 / OPS-03 (partial, local trace correlation) | connect job request, execution and artifact lineage | job/trace/recipe/attempt context is checked before publication; event history binds input/environment and final outcome; distributed tracing/log collection remains open |
| REL-04 (partial, closed-runner process isolation) | concurrent simulations do not corrupt each other's seeds | two real workers produce identical same-seed financial results while leaving parent Torch RNG unchanged; this is not proof of hostile-tenant filesystem/network isolation |
| AUD-01 / AUD-02 / AUD-11 (extended) | durable lineage, explicit failures and no-clobber artifacts | verified content-addressed objects, scoped pagination, hash-chained event/job projection and optional external audit-head pin; tests detect stale workers, corrupt objects and mismatched job contexts |

Jobs persist observed source/dependency fingerprints. A changed worker
environment rejects execution; this is not a locked/signed build. Stale
attempt tokens and cancellation requests fence completion. A valid but
scientifically failed simulation is stored as failed evidence, without
successful model cards/status. Publication can leave an unreferenced valid
object after database failure; only a current committed job points to a
successful artifact. Retries give at-least-once computation with fenced
publication, not exactly-once computation.

Object publication has per-object and total-byte caps, a local filesystem
lock and verified deduplication. SQLite uses rollback journal/FULL sync and
single-host transactions. Event update/delete is blocked through ordinary
application SQL; a privileged owner can still rewrite/truncate the database
and its hashes. External checkpoint trust remains outside this tool.

No broker/order/payment adapter, authenticated HTTP service, distributed
worker cluster, hard RAM isolation or production gate approval was added.
The complete 374-item scope remains in the register. See
[`evidence/validation_pr046.md`](./evidence/validation_pr046.md) and
[`docs/LOCAL_JOBS.md`](./docs/LOCAL_JOBS.md).

## Evidenced locally (PR-047: authenticated research-job API and typed SDK)

These are implementation/test notes, not independent acceptance or deployment
approval. The API is single-host research infrastructure with separate workers.

| ID | Local evidence scope | Test/artifact evidence |
|----|----------------------|------------------------|
| API-01 (partial) | versioned OpenAPI contract and compatibility policy | `docs/api/openapi-v1.json`, `docs/RESEARCH_API.md`; contract snapshot and all nine default recipe schema tests |
| API-02 (extended, partial) | strict JSON, typed nested wire schemas, dates, currencies, resource admission and structured 4xx failures | `test_service_http.py`: duplicate keys, overflowing exponents, missing/extra fields, invalid dates/units/types/precision/work, media/framing/byte/deadline guards; data ingestion/inference payload families remain open |
| API-03 / API-06 (extended, partial) | authenticated owner-derived asynchronous submission/status and mandatory submission idempotency | real socket SDK/worker round trip; repeat/conflict cases; foreign-owner status/cancel/artifact denial; complete service acceptance/load validation remains open |
| API-04 (extended, partial) | HTTP admission plus existing worker deadlines, cancellation and recovery | request/global-owner rate caps, inflight fencing after caller cancellation, durable queue quotas; existing real worker failure tests; hard RSS/distributed budgets remain open |
| API-07 (extended, partial) | consistent HTTP error codes, request/diagnostic IDs and terminal job error classes | wire schema validates error envelopes; SDK distinguishes structured service failures from protocol/transport faults; no recipe/token values in service logs |
| API-08 (partial, job collection only) | stable owner-scoped cursor pagination over jobs | HTTP and real SDK page traversal; foreign-owner/invalid cursors rejected; artifact-collection filters and immutable collection snapshot pagination remain open |
| API-09 (partial) | liveness separated from credential/SQLite writer/storage-directory readiness | removal, writer contention and policy drift return not-ready while liveness stays healthy; missing database is not recreated by probe; worker heartbeats/disk-capacity readiness remain open |
| API-10 (partial) | typed v1 SDK with bounded reads, operation timeouts and verified artifact lineage | `test_service_client.py`: real socket submit/idempotency/status/cancel/pages/artifacts/revocation, protocol/redirect guards; contract fixture; broader compatibility matrix remains open |
| API-11 (extended, partial) | structured request-to-job/trace/artifact correlation | service audit log tests and sealed API execution receipt; external collectors/distributed tracing remain open |
| API-12 (partial, current route surface) | research-only HTTP surface | exact OpenAPI route inventory and rejection of order/payment/trade routes; no broker/order/payment adapter is implemented |
| SEC-04 (partial, service-token foundation) | deny anonymous/cross-owner/write-with-read-only access | private hashed token bindings and rotation/revocation tests; this is not SSO/OIDC, MFA or an independently reviewed access system |
| SEC-05 (partial, transport controls) | CLI requires TLS outside loopback; app refuses remote cleartext and ignores spoofed forwarding; SDK retains default TLS verification | binding/proxy tests; deployed certificates, key management and encrypted-at-rest controls remain unverified |
| REL-07 (partial, process-local backpressure) | predictable 429/503 overload responses with retry guidance | global/owner rate, inflight and pending-queue quota tests; no calibrated production load/SLO or cluster-wide rate limit claim |

Credential files contain hashes only, are bounded/private/owner-controlled
regular files, and are re-read for revocation. Plain tokens are generated
into a separate private file and never printed by provisioning. Local
service tokens do not satisfy the blueprint's SSO/vault requirements.
Socket-operation timeouts in the SDK are not an absolute response wall
deadline. Application admission does not replace ingress connection/TLS
controls. Artifact retrieval validates the complete seal and job association.
See `docs/RESEARCH_API.md` and `evidence/validation_pr047.md` for exact scope.

## Evidenced locally (PR-048: locked builds and encrypted local recovery)

The scope remains all 374 items. The following notes are partial local
engineering evidence, with no independent acceptance or deployment approval.

| ID | Local evidence scope | Evidence and remaining boundary |
|----|----------------------|----------------------------------|
| MLO-02 (partial) | exact dependency/artifact hashes, CPU index binding, pinned build/bootstrap inputs and independent wheel rebuild | `uv.lock`, `requirements/bootstrap.txt`, `tools/reproducible_build.py`; clean locked environment and installed-wheel checks; container/OS digest rebuild remains open |
| CIQ-01 (partial) | CI lint/type/format checks include platform modules and build tooling | prepared workflow uses locked tools; local checks pass; remote CI/branch protection is not asserted |
| CIQ-03 (partial) | reference replay under installed wheel and locked numerical dependencies | strict reference hash/replay and recovery drill; prepared reference-profile CI step; broader endpoint/workload acceptance remains open |
| CIQ-04 (partial) | contract tests run against installed wheel, rather than an editable checkout alone | OpenAPI/schema/SDK real-socket tests retained in locked test suite; wider compatibility matrix remains open |
| CIQ-06 (partial) | repeatable Python wheel and resolved-profile CycloneDX SBOM | independent source snapshots, wheel RECORD/source verification, `docs/release/dependency-sbom.cdx.json`; container rebuild, deployed inventory and vulnerability assessment remain open |
| REL-05 (partial) | copied in-flight leases cannot finalize a restored attempt; requested cancellation stays terminal | real restored worker execution and old-token rejection; existing live cancellation/parent-death tests; complete cleanup/load acceptance remains open |
| REL-06 (partial, local restore only) | rebuild verified queue/object state into a new root after corruption/outage simulation | encrypted snapshot verification, corrupt/authenticated-invalid state refusal, atomic no-clobber publication, source preservation and numerical replay; live database/object failover remains open |
| DRI-07 (partial, measurement/runbook only) | document snapshot boundary, cooperative resource/deadline budgets and local recovery timing | `docs/RECOVERY.md`, drill receipt; business-approved RPO/RTO, accountable owners and scheduling remain open |
| DRI-08 (partial, local encrypted drill) | encrypted state restore and reference report recomputation | AES-256-GCM with full authentication before metadata parsing, integrity/audit/lineage checks and restored worker replay; encrypted offsite transfer/custody and full environment rebuild remain open |
| SEC-05 (extended, partial) | local backup encryption and private binary key handling | corruption/wrong-key/pin tests, fresh nonce, bounded regular-file key guard, no secret/recipe in CLI receipts; primary-storage encryption and deployed key-management verification remain open |
| OPS-02 (partial) | recovery CLI emits bounded operational receipts without plaintext keys/recipes | sentinel tests and retained drill report; service logs remain correlated/sanitized; external durable log storage and exhaustive secret scans remain open |

All recovered leases are fenced before the new root is visible, including
unexpired leases. Interrupted work is retried only within the persisted
attempt policy; requested cancellation remains cancelled, and exhausted work
fails with `restore_interrupted`. Terminal evidence retains its original
hashes/runtime. Restoring does not stop an original host or promote a service;
operator isolation and fresh service credentials are required before use.
No container engine, offsite transfer, key vault, approved recovery objective
or production SLO/failover result is inferred from a local encrypted drill.

## Evidenced today (PR-049: multi-creditor insolvency waterfall)

`econosim.insolvency` adds the multi-creditor loss-waterfall process the
"Explicitly NOT done" list below used to flag as missing (LED-07).
`allocate_recovery` is pure allocation math (no ledger side effects):
given a borrower's creditor claims, each tagged with a `ClaimPriority`
tier, and the cash actually recovered, it applies the absolute priority
rule (every senior tier paid in full before a junior tier receives
anything) with largest-remainder (Hamilton) pro-rata apportionment
within a tier when a tier's own recovery is short. `resolve_insolvency`
then applies that allocation by calling the existing, already-evidenced
`Bank.receive_repayment` (for the paid portion) and `Bank.write_off_loan`
(for the shortfall) once each per claim -- it introduces no new posting
pattern, only a new way of sizing those two existing calls.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| LED-07 | corporate default / insolvency process across multiple creditors | `test_resolve_insolvency_end_to_end_two_creditors_same_tier_pro_rata`, `test_resolve_insolvency_end_to_end_respects_priority_across_tiers` (secured claim made whole before the unsecured claim absorbs any loss) |
| LED-06 (reused, not reimplemented) | single-creditor write-off/repayment as the waterfall's own building block | `resolve_insolvency` calls `Bank.receive_repayment`/`Bank.write_off_loan` directly; no duplicate posting logic was written |
| ECO-16 (extended, fail-closed) | reject an insolvency resolution before posting anything if claims or recovery are inconsistent with the ledger | `test_resolve_insolvency_rejects_claims_not_matching_borrowers_recorded_debt`, `test_resolve_insolvency_rejects_recovery_exceeding_borrowers_cash` -- both assert zero mutation on rejection |
| LED-02 (extended, exact integer apportionment) | a short tier's recovery splits pro rata without minor-unit rounding drift | `test_allocate_recovery_apportionment_is_exact_and_within_one_unit_of_ideal_share`: 500 random claim sets, largest-remainder shares always sum to exactly the target and never deviate from each claim's ideal real-valued share by a full minor unit |
| ECO-09 (reused) | household/government borrowers go through the identical Borrower-protocol code path | `test_government_borrower_can_be_resolved_through_insolvency_too` |

Hand-worked and randomized verification (scratch, before the formal
suite): a two-creditor pro-rata split (600.00/400.00 claims, 250.00
recovered) was checked against a direct manual calculation (exact
150.00/100.00, no remainder) before any test was written; 2,000 random
largest-remainder trials and the absolute-priority tier ordering were
independently verified the same way. All five validations above are
additionally covered as formal pytest assertions, not just the scratch
check.

A claim list must sum to *exactly* the borrower's current pooled
`loan_account` balance, or `resolve_insolvency` raises before posting --
this module does not (and, given `agents.py`'s single pooled
loan-liability-account convention, cannot) discover each creditor's
individual exposure on its own; the caller supplies it explicitly, the
same way `titan.contagion.eisenberg_noe_clearing` takes an explicit
pairwise obligations matrix rather than inferring one. See
[`src/prometheus/econosim/insolvency.py`](./src/prometheus/econosim/insolvency.py).

## Evidenced today (PR-050: factor-model covariance shrinkage target)

PR-024's Ledoit-Wolf shrinkage only ever shrinks the sample covariance
toward a scaled-identity target (mu*I) -- an admission the "Explicitly
NOT done" list below used to carry verbatim ("no constant-correlation or
factor-model target"). `titan.covariance.shrinkage_intensity_to_target`/
`shrink_covariance_to_target` generalize this to shrink toward ANY fixed
target matrix, and `titan.factor_model.factor_model_implied_covariance`
promotes the (previously test-only, inline) Sigma = B Sigma_f B' +
diag(resid_var) formula into a reusable function so a factor-model
structure can actually be used as that target.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| OPT-05 / RISK-05 (extended, general shrinkage target) | shrinkage toward a structure beyond scaled identity | `test_target_shrinkage_matches_the_identity_special_case_exactly` (6 (n, p) regimes), `test_shrink_covariance_to_target_matches_ledoit_wolf_for_identity_target` -- an independently-written general implementation, not a refactor of PR-024's, reproducing it exactly at its own special case |
| RISK-07 (extended, reusable implied covariance) | the factor model's full covariance matrix, not only its Euler decomposition | `test_factor_model_implied_covariance_matches_decompose_portfolio_variance` (20 random weight vectors, two different computational paths over the identical quadratic form); `test_factor_model_implied_covariance_is_positive_semidefinite` |
| RISK-05 (extended, practical value of the new target) | a factor-model target must actually help, not merely exist | `test_factor_target_reduces_average_estimation_error_vs_identity_target`: 200 repeated modest-sample (n=60, p=10) draws from a TRUE factor-structured covariance, factor-shrunk estimate has lower mean Frobenius-norm error than identity-shrunk |
| OPT-05 / OPT-10 (extended, composes with the portfolio optimizer) | the lower-error target must translate into a better out-of-sample portfolio, not just a smaller matrix-norm number | `test_factor_target_portfolio_has_lower_true_variance_than_identity_target_portfolio`: `minimum_variance_portfolio` fed the factor-shrunk covariance has lower TRUE out-of-sample variance than the same optimizer fed the identity-shrunk covariance, averaged over 80 trials -- mirrors PR-024's own existing identity-vs-raw portfolio test, one level up |

Derivation (Ledoit & Wolf 2003, "Honey, I Shrunk the Sample Covariance
Matrix": for a FIXED target -- not itself re-estimated from the same
sample -- the asymptotic covariance between target and sample estimator
is zero, so the optimal intensity reduces to pi_hat / gamma_hat, where
pi_hat is the sample covariance's own target-independent estimation-error
variance and gamma_hat is the squared Frobenius distance from target to
the (sample-estimated) population covariance) was checked empirically,
before any production code was written, against an independent scratch
reimplementation: 200 random (n, p) panels confirmed the general formula
reduces exactly to PR-024's own scaled-identity-specific implementation,
and a separate simulation confirmed the practical error/portfolio-variance
reduction claims above, before the same two properties were written as
formal pytest assertions.

Not covered: no generalized cross-validation or empirical-Bayes choice
between candidate targets (identity vs. factor vs. others) -- the caller
picks the target; no multi-target blend; `factor_model_implied_covariance`
does not itself validate that `factor_covariance` is PSD (symmetric
non-PSD input silently produces a non-PSD result, exactly like
`decompose_portfolio_variance`'s existing, equally unvalidated,
assumption). See
[`src/prometheus/titan/covariance.py`](./src/prometheus/titan/covariance.py) and
[`src/prometheus/titan/factor_model.py`](./src/prometheus/titan/factor_model.py).

## Evidenced today (PR-051: Heston characteristic-function option pricer)

`volterra.heston_pricer` adds the first stochastic-volatility PRICER to
VOLTERRA's ladder (Black-Scholes, forwards, American binomial -- all
GBM/deterministic-volatility so far), using the "little trap" branch-
stable characteristic function (Albrecher, Mayer, Schoutens & Tistaert,
2007) rather than the original 1993 formulation, which has a documented
branch-cut correctness bug for certain parameter/strike combinations.
`stochastica.heston` (PR-012-era) already simulated Heston paths; this
PR adds the matching semi-closed-form PRICE, previously missing.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| PRI-04 | Heston Fourier/characteristic-function pricer, checked against reference values | `test_characteristic_function_at_zero_is_one`, `test_characteristic_function_at_negative_i_equals_forward_price` (exact algebraic identities any correct characteristic function must satisfy); `test_converges_to_black_scholes_in_the_zero_vol_of_vol_limit` (+ the symmetric put test, + a from-scratch second Black-Scholes computation not calling `volterra.black_scholes` at all) |
| VAL-14 (partial, two-method pricing cross-check) | cross-check pricing with an independent implementation | `test_matches_monte_carlo_simulation`: the Fourier price falls within 4 Monte Carlo standard errors of simulating `stochastica.heston.simulate_heston_paths` (an independently-written module) over 200,000 paths |
| PRI-03 (extended, model-independent parity) | put-call parity holds for the new model too | `test_put_call_parity_against_an_independently_mirrored_put_formula`: the put price is checked against a SEPARATELY, independently-coded P1'/P2' integral in the test itself, not against the production shortcut's own definition of a put (which derives the put from the call via parity by design, so testing parity against that shortcut alone would be circular) |
| RISK-04 (reused convention, risk-neutral probability) | P2 must be a genuine probability | `test_risk_neutral_probabilities_are_in_unit_interval`, parametrized over 5 strikes |

The "little trap" derivation was checked empirically before any
production code was written: a scratch reimplementation independently
confirmed all five properties above (the two algebraic identities, the
probability-interval property, put-call parity, and Monte Carlo
agreement) in one pass, with no implementation fix needed afterward --
unlike PR-034/PR-040's earlier real bugs, this derivation was correct on
first attempt, confirmed rather than assumed.

Design choice: `heston_option_price` prices a put by applying put-call
parity to the call price, not by re-deriving a second P1'/P2' formula --
parity is an exact, model-independent identity, so this is strictly safer
than hand-deriving the mirror-image integral a second time in production
code (the test file DOES do that second derivation, specifically so the
parity shortcut has something independent to be checked against).

Not covered: no Heston model CALIBRATION (fitting kappa/theta/xi/rho/v0
to observed market prices) -- this prices a European option under
ALREADY-SPECIFIED parameters, the reverse direction of
`volterra.calibration`'s implied-volatility solve; no FFT/COS multi-
strike acceleration (each call prices one strike via two adaptive
numerical integrals); not wired into `titan.positions`' instrument union
yet (standalone, like every VOLTERRA pricing method before its own first
caller -- forwards and American options were each standalone for one PR
too). See
[`src/prometheus/volterra/heston_pricer.py`](./src/prometheus/volterra/heston_pricer.py).

## Evidenced today (PR-052: Merton jump-diffusion model and closed-form pricer)

`stochastica.jump_diffusion` adds a second non-GBM model (SDE-08: "jump
or fat-tail stress scenario model"), and `volterra.merton_pricer` adds
its matching closed-form European option price -- the second time this
repository has added both a stochastic model AND its pricer together
(the first was Heston/PR-051, which only had the model already, from the
PR-012 era). The simulator's per-step jump allocation is EXACT, not an
Euler approximation: a Poisson-distributed jump count convolved with the
matching sum-of-normals jump-size distribution reproduces the true
per-step law with no discretization bias at all.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| SDE-08 | jump/fat-tail model, parameterization and jump timing fully disclosed | `stochastica/jump_diffusion.py`'s module docstring states the exact per-step allocation; `test_simulator_with_zero_jump_intensity_matches_pure_gbm_moments` confirms the zero-jump degenerate case reduces to plain GBM moments |
| PRI-01 / PRI-04 (extended, a second non-GBM pricer) | a second stochastic model with a working closed-form price | `test_matches_monte_carlo_simulation_of_the_independent_simulator`: the closed form agrees with simulating the INDEPENDENTLY-written `jump_diffusion` module, within 5 Monte Carlo standard errors |
| VAL-14 (extended, a second two-method cross-check) | cross-check pricing with an independent implementation | same test as above, plus `test_matches_a_from_scratch_second_computation_of_the_closed_form` (a from-scratch re-derivation, not calling the production formula) and the Black-Scholes zero-intensity limit (call and put, with and without dividends) |
| PRI-03 (reused convention) | put-call parity holds for the new model too | `test_put_call_parity_holds`, exact to `1e-9` |

A real, easy-to-make derivation error was caught and documented, not
just avoided by luck: the Poisson-weighted Black-Scholes sum's weight
sequence must use the RISK-NEUTRAL-ADJUSTED jump intensity
`jump_intensity * (1 + k)` (k = the jump compensator), not the physical
`jump_intensity` the simulator itself draws jump counts from -- both
formulas look equally plausible written down, and the physical-intensity
version gives a price off by far more than Monte Carlo noise could
explain (confirmed directly in
`test_using_the_physical_jump_intensity_as_the_poisson_weight_would_be_wrong`,
which pins the size of that discrepancy so a future refactor
reintroducing the bug fails loudly). This was resolved empirically,
before writing any production code, by deriving the closed form
independently from first-principles conditional expectations (which
weight sequence makes the derivation's two halves agree is unambiguous)
and cross-checking both candidates against Monte Carlo at high enough
path counts (40 million) to separate a ~0.3% price difference from
simulation noise -- an earlier, lower-path-count attempt could not
actually distinguish the two candidates, which would have let the wrong
one through silently.

Not covered: no jump-diffusion model CALIBRATION; no FFT/COS
acceleration (same scope boundary as the Heston pricer above); not wired
into `titan.positions`; dividend yield (`market.dividend_yield`) is
supported in the closed-form pricer (confirmed against Monte Carlo with
q != 0 before being written into production code) but the simulator
itself has no separate q term (`params.mu` already plays the role of the
risk-neutral drift directly, matching `stochastica.heston`'s own
convention). See
[`src/prometheus/stochastica/jump_diffusion.py`](./src/prometheus/stochastica/jump_diffusion.py) and
[`src/prometheus/volterra/merton_pricer.py`](./src/prometheus/volterra/merton_pricer.py).

## Evidenced today (PR-053: single-barrier options with discretization correction)

`volterra.barrier_options` adds single-barrier European option pricing
(PRI-08: "barrier option with discretization correction"), derived
directly from the reflection principle for drifted Brownian motion rather
than transcribed from a reference formula table (the classical Reiner-
Rubinstein closed form has roughly eight case-dependent sub-formulas that
are easy to mis-transcribe from memory without catching the error). The
continuous-monitoring price is a numerical integral (quadrature) of the
option payoff against the derived survival density, in the same spirit as
`heston_pricer`'s own semi-closed-form integral.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| PRI-08 | barrier option with discretization correction | `broadie_glasserman_kou_adjusted_barrier`/`discretely_monitored_barrier_option_price` implement the Broadie-Glasserman-Kou (1997) continuity correction; `test_discretization_correction_reduces_error_vs_naive_discrete_monitoring` pins that the correction reduces pricing error by more than 5x versus the uncorrected continuous formula, against a direct simulation of the actual discretely-monitored process |
| VAL-14 (extended, a third two-method cross-check) | cross-check pricing with an independent implementation | `test_matches_independent_bridge_corrected_monte_carlo`: a from-scratch, separately-written Brownian-bridge continuity-corrected Monte Carlo (not the production quadrature re-run), parametrized over down/up barriers, calls/puts, knock-in/out, and strikes on both sides of the barrier |
| PRI-03 (reused convention) | put-call / in-out parity holds for the new model too | `test_in_out_parity_holds`: knock-in + knock-out price equals the Black-Scholes vanilla price, exactly to `1e-8` |

The reflection-principle density was itself verified before being used to
price anything: first in isolation, against a vectorized Monte Carlo of
plain drifted Brownian motion hitting a barrier (no options involved at
all, isolating just the probability identity), then against full barrier
option prices. The FIRST Monte Carlo attempt used a naive "check only at
discrete simulation grid points" barrier test and showed small but
consistent mismatches against the closed form across every parameter
combination tried -- which was not a bug in the formula, but a known bias
in that Monte Carlo itself (discrete-grid monitoring systematically misses
excursions between sampled points, so it under-detects crossings relative
to true continuous monitoring). Switching the check to weight each
simulated path by its Brownian-bridge continuity-corrected survival
PROBABILITY each step, instead of a hard discrete-grid check, removed the
bias and confirmed the closed form was correct all along -- the same
discretization-bias phenomenon the Broadie-Glasserman-Kou correction
above exists to compensate for, caught here on the test side before it
could be mistaken for a production bug.

Not covered: no rebates (payment on knockout or on failing to knock in);
no double barriers; no American exercise combined with a barrier; not
wired into `titan.positions`. `market.volatility` IS used by this pricer
(unlike `heston_pricer`/`merton_pricer`, which take their own diffusion
parameter objects) since there is no separate stochastic-volatility or
jump parameter object here. See
[`src/prometheus/volterra/barrier_options.py`](./src/prometheus/volterra/barrier_options.py).

## Evidenced today (PR-054: Asian options with a Kemna-Vorst control variate)

`volterra.asian_options` adds path-dependent Asian option pricing
(PRI-09: "path-dependent Asian option with controls"), fixed at
`n_fixings` equally-spaced dates. The geometric-average variant has an
exact closed form (a geometric average of jointly Gaussian log-prices is
itself Gaussian); the arithmetic-average variant has none (a sum of
lognormals is not lognormal), so it is priced by Monte Carlo using the
geometric average's exact price as a Kemna & Vorst (1990) control
variate -- the literal "with controls" the requirement text calls for.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| PRI-09 | path-dependent Asian option with controls | `monte_carlo_price_asian`'s Kemna-Vorst control variate; `test_monte_carlo_arithmetic_control_variate_reduces_variance` pins more than a 5x standard-error reduction versus plain Monte Carlo (a conservative margin below the roughly 20-30x actually observed in pre-implementation scratch verification at similar settings) |
| VAL-14 (extended, a fourth two-method cross-check) | cross-check pricing with an independent implementation | `test_geometric_closed_form_matches_independent_monte_carlo`: the closed form against simulation of the independently-written `stochastica.gbm` path simulator's own fixing values, across three (strike, maturity, n_fixings) combinations |
| PRI-03 (reused convention, generalized to any lognormal terminal variable) | put-call parity holds for the new model too | `test_geometric_put_call_parity_against_the_geometric_forward`: Call - Put = e^{-rT}*(E[G_T] - K), exact to `1e-9` |
| PRI-06 (reused convention, control variates) | Monte Carlo pricer with standard errors | `MonteCarloResult` (the same dataclass `monte_carlo.py`'s vanilla pricer already returns) carries `control_variate_used` and a standard error on every Asian Monte Carlo price |

The closed form's own underlying identity -- that averaging n
equally-spaced Brownian motion samples gives variance
`dt*(n+1)*(2n+1)/(6n)` -- was independently re-derived by brute-force
double summation of `min(t_i, t_j)` over every pair of fixing times (not
assumed from the `n(n+1)(2n+1)/6` shortcut the production formula uses)
and confirmed to match to `1e-10`
(`test_geometric_closed_form_matches_brute_force_covariance_sum`). A
verification-script discrepancy was caught and resolved before trusting
the formula: an initial zero-volatility limit check compared the priced
geometric average against the ARITHMETIC mean of the per-date forward
prices and found a small but consistent mismatch -- not a bug in the
formula, but in that check's own expectation, since by AM-GM the
geometric mean of several different forward levels is strictly below
their arithmetic mean whenever r != q. Comparing against the geometric
mean of the same forwards instead matched to 6 decimal places.

AM-GM also gives a model-free, non-statistical sanity floor that holds on
every single path and was tested directly: the arithmetic average's call
price can never be below the otherwise-identical geometric average's
call price (`test_arithmetic_price_is_at_least_geometric_price`).

Not covered: continuous-time (infinite-fixing) averaging; floating-strike
Asian options (the strike here is fixed at inception, not reset to the
average at maturity); American-style early exercise; not wired into
`titan.positions`. See
[`src/prometheus/volterra/asian_options.py`](./src/prometheus/volterra/asian_options.py).

## Evidenced today (PR-055: point-in-time schema and no-future-data fixture extension)

The first PR under the new ECONOSIM-X/PROMETHEUS-X final-project
addendum (see the dedicated section near the top of this file). Extends
`econosim.pit` (originally from PR-003) rather than building a parallel
module, after confirming via research that no macro-forecasting or
FRED-style ingestion code existed anywhere in this repository to collide
with, and that the existing `PointInTimeStore`/`MacroObservation` already
implemented the core "strict data inclusion predicate" the addendum's
FP-03 calls for -- so this PR's job was to extend that predicate's
schema and add the missing *active-rejection* fixture, not to invent a
new mechanism from scratch.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| FP-02 (addendum, partial) | dataset licenses, raw hashes, published_at and vintage_at recorded | `MacroObservation` gained `vintage_at`, `asof_eligible_at`, `ingested_at`, `source_url`, `source_license`, `raw_hash` (format-validated as 64-char hex), `unit`, `frequency`, `transformation_id`, `timezone`, `quality_flags`, all additive with defaults so every pre-existing caller/test (`monetary_feedback.py`, `test_time_engine.py`, `test_monetary_feedback.py`) was unaffected -- confirmed by rerunning them unchanged after the schema change, not by inspection alone |
| FP-03 (addendum) | a no-future-data fixture rejects unavailable features | new `FutureDataError`, `require_eligible`, `build_feature_vector`; `test_build_feature_vector_rejects_unavailable_features_instead_of_partial_data` confirms the fixture fails closed on the WHOLE request rather than silently returning a feature vector missing just the one series that is not yet eligible |
| DAT-07 (original blueprint, strengthened) | point-in-time inclusion predicate | the predicate itself now has one more leakage gate than before: `asof_eligible_at` (this system's own ingestion lag) in addition to `published_at` (the source's publication date) -- `test_as_of_also_gates_on_internal_ingestion_lag_not_just_publication` exercises a case where publication has happened but internal ingestion has not, confirming the stricter (later) gate wins |

A genuine new leakage vector was identified and closed, not just
re-tested: the pre-existing predicate only ever checked `published_at`,
implicitly assuming this system's own ingestion pipeline makes data
available instantaneously at the moment of external publication. That
assumption is false in any real pipeline (ingestion, parsing,
transformation and quality checks take time), so `effective_eligible_at`
= `max(published_at, asof_eligible_at)` is now the actual gate used by
both `as_of` and `all_eligible_as_of`; when `asof_eligible_at` is left at
its default of `None`, this is mathematically identical to the old
predicate, which is why the five pre-existing tests needed zero changes.

Not covered: real FRED-MD/FRED-QD/ALFRED/Treasury/French-factor ingestion
(DAT-02..DAT-05 remain unimplemented; this PR only extends the SCHEMA
and PREDICATE those future ingestion adapters would populate and be
gated by); no dataset has actually been licensed (PRV-01/DAT-01 remain
open); no forecasting model exists yet to consume `build_feature_vector`
(MACROCORE/RECESSIONNET/INFLATIONCAST are all still FP-05/06/07 NOT
VERIFIED, tracked above). See
[`src/prometheus/econosim/pit.py`](./src/prometheus/econosim/pit.py).

## Evidenced today (PR-056: classical forecasting baselines and rolling-origin backtest)

`macrocore.baselines` + `macrocore.synthetic_data` + `macrocore.evaluation`
close FP-04: "Classical forecasting baselines run reproducibly" --
Persistence, AR(p) and VAR(p), all OLS-fit with closed-form Gaussian
multi-step forecast intervals, backtested against a clearly-labeled
synthetic macro panel entirely through `econosim.pit`'s point-in-time
store (PR-055's module), not a bare ground-truth array. These are the
addendum's own required comparison point for MACROCORE's eventual shared
Transformer encoder (section 09/E01: "Persistence / ARIMA / VAR / TCN vs
shared Transformer") -- building them now, before any neural model
exists, means a future MACROCORE can be judged against a real baseline
from day one rather than against nothing.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| FP-04 (addendum) | classical forecasting baselines run reproducibly | `fit_autoregression`/`fit_vector_autoregression` are deterministic OLS (`np.linalg.lstsq`, no randomness); `backtest_persistence`/`backtest_autoregressive`/`backtest_vector_autoregressive` run a full rolling-origin backtest over a fixed-seed synthetic panel, confirmed reproducible by construction (same seed, same OLS, no stochastic fitting step) |

No original-blueprint 374-item ID is claimed for this PR beyond the row
above, even though the verification method below reuses the project's
usual "verify against Monte Carlo, then re-verify via a second from-
scratch computation in the test suite" discipline. VAL-01 is specifically
a GBM/Black-Scholes golden test suite, VAL-03 is specifically stochastic-
INTEGRATOR convergence, and VAL-14 is specifically pricing/ES cross-
checks -- AR(p)/VAR(p) forecast intervals and CRPS scoring are none of
these, so tagging any of them here would be a real misattribution, not
merely an imprecise one. An earlier draft of this section tagged VAL-01/
VAL-03/VAL-14 anyway (the blueprint register's `with_repository_notes`
count briefly, incorrectly, rose from 124 to 126 as a result); caught by
noticing the jump looked too large for what this PR actually did, and
corrected here before being committed to anywhere permanent.

The forecast-interval math was still verified exactly as rigorously as
every prior PR's pricing formula, just without an original-blueprint ID
to hang that rigor on: the AR(p)/VAR(p) h-step forecast-interval formulas
(MA(infinity) psi-weight expansion) were checked against Monte Carlo
re-simulation of the TRUE process from a fixed origin (millions of paths,
max relative error under 0.5% at every tested horizon) before being
trusted in production code, then re-verified via a second,
independently-coded psi-weight recursion written directly into the test
suite (`test_ar_forecast_matches_from_scratch_second_computation_of_psi_weights`,
`test_var_forecast_matches_from_scratch_second_computation`). The
closed-form Gaussian CRPS formula (Gneiting & Raftery, 2007) was checked
against a direct Monte Carlo CRPS estimator (`E|X-y| - 0.5*E|X-X'|` for
independent draws X, X' from the forecast distribution) to within 0.002
at three test points, also before being written into production code.

A model-free sanity check was used alongside the statistical ones: a
stationary AR(1)'s h-step forecast variance must converge to its exact
unconditional variance `sigma^2/(1-phi^2)` as h grows (the forecast has
no informational value about the arbitrarily-far future), confirmed
analytically to 1e-6 relative error at h=200
(`test_ar_forecast_variance_converges_to_stationary_variance_at_long_horizon`)
-- a cheap, exact check independent of the Monte Carlo verification above.
A genuinely comparative (not tautological) integration test confirms AR(1)
forecasting measurably beats persistence specifically on strongly
mean-reverting synthetic data constructed to make that true by design
(`test_autoregressive_beats_persistence_on_strongly_mean_reverting_data`),
and a calibration self-consistency test confirms a model whose assumed
distribution exactly matches the data-generating process achieves a
realized interval-coverage rate within the correctly-calibrated model's
own binomial confidence interval.

"ARIMA" here means AR(p) (ARIMA(p,0,0)): a deliberate scope cut against
differencing and moving-average terms, documented in
`macrocore.baselines`'s own module docstring, not a hidden gap. Regime-
conditioned error breakdown ("error by regime" in E01's minimum evidence)
is not implemented -- there is no regime-labeling mechanism anywhere in
this repository. No real macroeconomic data is used anywhere in this PR;
`macrocore.synthetic_data` labels every observation it produces
`source_license="synthetic-generated-for-testing-only"` and
`quality_flags=("synthetic",)`. See
[`src/prometheus/macrocore/`](./src/prometheus/macrocore/).

## Evidenced today (PR-057: addendum-checklist accuracy audit, Heston weak-convergence study, and three small gap closures)

This PR started as a skeptical, literal re-read of the six "PARTIAL
(pre-existing)" rows PR-055/056 had added to the ECONSIM-X addendum
section, after the VAL-01/VAL-03/VAL-14 misattribution two PRs ago made
clear that "this evidence is nearby and the right general shape" is not
the same as "this evidence actually says what the ID requires." Two of
the six turned out to be over-credited; one new convergence-study module
and two small test additions close or narrow the rest honestly.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| FP-09 (addendum, upgraded) | ECONOSIM-X transaction and stock-flow identities pass | re-confirmed `tests/property/test_ledger_invariants.py::test_random_action_sequences_preserve_identities_and_total_equity` already does exactly this under Hypothesis-generated randomized sequences; upgraded from PARTIAL to VERIFIED-BY-TEST (text-only change, evidence already existed) |
| FP-12 (addendum, corrected) | VOLTERRA reference price and Greeks match benchmark tolerances | corrected an inaccurate prior claim that Greeks exist for all 5 pricers -- they exist only for Black-Scholes and American options; Heston/Merton/barrier/Asian have price benchmarks but no Greeks at all |
| FP-14 (addendum, upgraded) | DEEP HEDGING uses a cost-aware matched baseline | re-confirmed `hedging.baseline.apply_no_trade_band` is directly compared against the delta baseline on the same paths (HDG-03's own existing evidence); upgraded from PARTIAL to VERIFIED-BY-TEST |
| FP-16 (addendum, corrected) | TITAN risk/optimization reports include horizon, units, costs | corrected an inaccurate prior PARTIAL claim -- every TITAN risk/report output was checked and NONE carries horizon+units+cost together (`historical_var`/`parametric_var`/etc. return a bare `float`; `VarCoverageResult`/`StressTestReport` carry neither units nor cost); downgraded to NOT VERIFIED rather than left overstated |
| FP-11 (addendum, narrowed+closed) | STOCHASTICA paths pass numerical and positivity diagnostics | jump-diffusion had no explicit positivity/finiteness test before this PR (only moment-matching); `test_jump_diffusion_paths_are_always_positive_and_finite` closes that specific gap under a deliberately severe stress case (jump_intensity=5, jump_mean=-0.6) |
| FP-20 (addendum, narrowed+extended) | Run manifest includes code hash, data hash, seed and model ID | `RunManifest` gained optional `code_hash`/`data_hash`/`model_id` fields (format-validated as 64-char hex SHA256 where applicable), additive with defaults so all 11 pre-existing call sites are unaffected; `model_id` remains unpopulated by any real model, since none exists yet |
| SDE-05 (original blueprint) | numerical time-step refinement experiments, path distribution stability reported | `stochastica.convergence.heston_weak_convergence_study`: a batched (memory-safe), fixed-seed Monte Carlo bias study of `simulate_heston_paths`'s log-Euler/full-truncation scheme against the closed-form reference price at 3 step counts, confirming bias shrinks monotonically as dt decreases |
| VAL-03 (original blueprint) | strong/weak convergence checks for stochastic integrators | same module: `estimate_weak_convergence_order` (log-log OLS slope of bias vs dt) is independently verified against two synthetic cases with an EXACTLY known order (pure dt^1 and dt^2 decay, recovered to 1e-9) before being applied to the real Heston result, which lands at order ~0.78 (theory predicts ~1); this is a correct, literal match to "convergence checks for stochastic integrators" -- unlike the VAL-01/03/14 misattribution earlier, this module genuinely IS a stochastic-integrator convergence check |

A near-miss worth recording precisely because it was caught, not because
it happened: an early draft of this module's own verification script
allocated the full `(n_paths, n_steps+1)` Heston path array directly at
`n_paths=4,000,000`, driving system memory from 4GB to 26GB/31GB used
with swap nearly exhausted, before being killed and rewritten to batch
paths (accumulating only running sum/sum-of-squares) -- the production
`heston_weak_convergence_study` function was written batched from the
start as a direct consequence, not as an afterthought.

GBM and jump-diffusion are explicitly out of scope for the convergence
study itself (both draw from exact transition laws with zero
discretization bias to characterize -- see the module's own docstring);
only Heston's log-Euler/full-truncation scheme has genuine bias to
study. SDE-11/SDE-12 (parameter-identifiability diagnostics, extreme-
input solver fuzzing) remain separately open and NOT addressed by this
PR. See
[`src/prometheus/stochastica/convergence.py`](./src/prometheus/stochastica/convergence.py).

## Evidenced today (PR-058: Greeks for Heston, Merton, barrier and geometric Asian)

Closes the real gap PR-057's audit found in FP-12: finite-difference
Greeks (`heston_greeks.py`, `merton_greeks.py`, `barrier_greeks.py`,
`asian_greeks.py`), reusing the shared `black_scholes.Greeks` dataclass
and the same central-difference bump-and-reprice pattern `greeks_fd.py`
already uses, cross-checked against Black-Scholes' own independently-
computed analytical Greeks in each pricer's degenerate (or, for Asian at
n_fixings=1, EXACT) limit.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| PRI-07 (extended) | Delta/Gamma/Vega with method tagging | 4 new modules extend Greeks coverage from 2 pricers (Black-Scholes, American) to 6 (+ Heston, Merton, barrier, geometric Asian); arithmetic Asian is the one explicitly disclosed remaining gap (see below) |
| VAL-05 (extended, same caveat as the original row) | Greeks cross-checked for correctness | each new module's Greeks converge to Black-Scholes' analytical Greeks in a limit where the two models coincide, confirmed in testing, not merely plausible by inspection |
| FP-12 (addendum, closed) | VOLTERRA reference price and Greeks match benchmark tolerances | the specific gap PR-057's audit found (Greeks existed for only 2 of 5 pricers) is closed for 4 of the remaining 5 variants; see "Not covered" below for the one still open |

Two genuinely new findings came out of verifying these before writing
production code, not just confirming what was expected:

1. **Heston's vega is not simply Black-Scholes vega in different units,
   even after the chain-rule unit conversion.** Heston has no single
   "volatility" input; its natural vega is `d(price)/d(v0)` (v0 a
   variance). Converting units via the chain rule
   (`d(price)/d(sigma) = d(price)/d(v0) * 2*sigma`) was NOT enough to
   match Black-Scholes vega at a realistic mean-reversion speed
   (kappa=1.5) -- the converted value came out roughly half of Black-
   Scholes' vega. This is a real economic effect, not a bug: with
   kappa > 0, variance reverts from v0 toward theta over the option's
   life, so a bump to v0 alone has a smaller effect on the option price
   than an equivalent bump to a CONSTANT Black-Scholes sigma held fixed
   for the whole horizon would. Only after separately testing with
   kappa -> 0 (removing mean reversion) did the chain-rule-converted
   vega match Black-Scholes closely, confirming both the formula and
   the economic explanation.
   `test_vega_requires_removing_mean_reversion_to_match_black_scholes`
   pins both halves of this finding as a permanent regression guard.
2. **Barrier gamma needed a much larger finite-difference bump than
   Black-Scholes' usual default, for a concrete, measured reason.**
   `barrier_option_price` is a numerical quadrature with its own
   integration-noise floor; gamma's central-difference formula divides
   by `spot_bump^2`, amplifying that floor by roughly 1e6 at a
   Black-Scholes-sized bump of 1e-3 -- confirmed directly: the same
   gamma computation went from a 7.8% error at `spot_bump=1e-3` to
   matching Black-Scholes' gamma to 4 significant figures at
   `spot_bump=0.05`, which is now `barrier_greeks.py`'s default.
   `test_gamma_at_the_small_black_scholes_style_bump_would_be_wrong`
   pins this as a regression guard too.

Not covered: arithmetic-average Asian Greeks. `monte_carlo_price_asian`
has no common-random-numbers machinery, so a naive bump-and-reprice on
it would have unknown, likely-unreliable precision (the same failure
mode barrier's gamma ran into, but without even a fixed, characterizable
noise floor to calibrate a bump size against) -- `asian_greeks.py` raises
`ValueError` rather than silently returning a number of unknown quality,
consistent with this project's existing "fail closed rather than report
false precision" convention. None of the four new Greeks modules are
wired into `titan.positions`' instrument union yet. See
[`src/prometheus/volterra/heston_greeks.py`](./src/prometheus/volterra/heston_greeks.py),
[`src/prometheus/volterra/merton_greeks.py`](./src/prometheus/volterra/merton_greeks.py),
[`src/prometheus/volterra/barrier_greeks.py`](./src/prometheus/volterra/barrier_greeks.py) and
[`src/prometheus/volterra/asian_greeks.py`](./src/prometheus/volterra/asian_greeks.py).

## Evidenced today (PR-059: portfolio-level Greeks aggregation)

`titan.portfolio_greeks` adds the first evidence anywhere in this
repository for PRI-10: "portfolio-level repricing and Greeks
aggregation... sum of line-level Greeks reconciles to portfolio
totals." Repricing aggregation already existed (`titan.positions`'
`value_book`/`total_market_value`, RISK-01) but only for 3 instrument
types, and nothing aggregated Greeks at all. Rather than redesign
`Position`/`Instrument` to carry every pricer's own extra parameters
(Heston needs `HestonParams`, Merton needs `MertonJumpParams`, neither
of which `Position` has anywhere to put) and risk the existing, already-
tested repricing path, this is a deliberately decoupled module: it
aggregates whatever PER-UNIT `Greeks` the caller supplies, computed via
whichever of the now 6 pricer-specific Greeks functions actually
applies -- so it works across every current pricer (and any future one)
without needing `titan.positions` itself to know about Heston, Merton,
barrier or Asian contracts.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| PRI-10 | portfolio-level repricing and Greeks aggregation; sum of line-level Greeks reconciles to portfolio totals | `aggregate_portfolio_greeks` sums quantity-scaled per-unit Greeks across lines; `verify_reconciliation` independently re-derives the total from the lines and confirms it matches, rather than trusting the total is correct merely because it was computed by the same function -- and a dedicated test (`test_verify_reconciliation_detects_a_tampered_total`) confirms this check actually discriminates a wrong total from a correct one, not just that it returns `True` on the happy path |

A real cross-model integration test, not just a structural one:
`test_aggregation_genuinely_works_across_different_pricing_models`
builds a 3-line portfolio with one line's Greeks from Black-Scholes, one
from Heston, and one from Merton, and confirms the aggregate total is
the correct quantity-weighted sum across models the module never
inspects or special-cases. `greeks_from_position_book` connects this to
the existing `PositionBook` (reads quantities from it directly, no
duplicated bookkeeping) without modifying `titan.positions` itself.

Not covered: no automatic selection of which pricer/Greeks function
applies to a given position (the caller must supply per-unit Greeks
already computed via the right one); no cross-model unit reconciliation
(aggregating a Heston line's vega, which is `d(price)/d(v0)`, against a
Black-Scholes line's vega, which is `d(price)/d(sigma)`, is
mathematically well-defined as a sum but economically meaningless unless
the caller accounts for the different units -- this module sums
whatever `Greeks` it is given and does not attempt to detect or warn
about that mismatch); no scenario/stress Greeks (only point-in-time
sensitivities). See
[`src/prometheus/titan/portfolio_greeks.py`](./src/prometheus/titan/portfolio_greeks.py).

## Evidenced today (PR-060: first real, live-verified external data connector)

`data_ingestion.worldbank` (plus a shared `data_ingestion.transport`
pluggable-HTTP abstraction) is the first external macroeconomic data
source in this repository that has actually been exercised against a
real, live API -- World Bank Open Data, which needs no API key, unlike
FRED/ALFRED (no `FRED_API_KEY` is configured in this environment; see
"Not covered" below). Every prior mention of macro data in this
repository was either fully synthetic (`macrocore.synthetic_data`,
PR-056) or a schema/predicate with no real source behind it
(`econosim.pit`, PR-003/PR-055).

Before any production code was written, a full round trip was run by
hand against the live API: real HTTP fetch -> JSON parse ->
`MacroObservation` construction -> `econosim.pit.PointInTimeStore`
eligibility query, confirming the response shape (a two-element
`[metadata, rows]` JSON array), pagination (`page`/`pages` in the
metadata), and the missing-value convention (JSON `null`, not a magic
string) all behave as documented. The 4 real response pages from that
verification are embedded verbatim in the test suite (not hand-typed
fake JSON), so the committed tests exercise the parser against data it
did not invent, while staying hermetic (a `ScriptedTransport` test
double serves the captured pages; no test makes a live network call).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| DAT-07 (strengthened) | observation/publication timestamp tracking, point-in-time inclusion predicate | the SAME predicate now gates a real external HTTP-sourced observation, not just synthetic/econosim data -- `test_observations_feed_the_point_in_time_store_correctly` confirms a fetched observation is ineligible before the API's own `lastupdated` date and eligible on/after it |
| DAT-08 (first evidence, narrow) | no forward-fill across release windows without justification | `test_rows_with_a_null_value_are_skipped_not_fabricated`: a JSON `null` value is excluded from the result, never forward-filled or fabricated -- this is the specific clause claimed; no cross-source REVISION policy exists (World Bank's bulk API has no revision concept to test against) |
| FP-02 (addendum, closed) | dataset licenses, raw hashes, published_at and vintage_at recorded | PR-055 built the schema; this PR is the first REAL dataset flowing through it end to end, with a real license (CC-BY-4.0), a real `raw_hash` (SHA256 of the actual fetched bytes, confirmed in `test_parses_all_pages_of_a_real_captured_response` against an independently-computed hash of the same bytes), and a real `published_at` |

Deliberately NOT claimed despite being adjacent, directly applying the
lesson from the VAL-01/03/14 misattempt two PRs ago (proximity to a
requirement's subject matter is not the same as satisfying its literal
text): DAT-01 (one connector's docstring is not an approved,
organization-wide source catalog covering all 15 sources the project's
own dataset plan lists); DAT-02 (that ID is specifically FRED-MD/QD, a
different source from World Bank); DAT-06 (no raw/normalized/features/
artifacts storage layers exist -- this fetches into memory only);
DAT-12 (the hash covers RAW bytes, not "normalized data and feature
transformations," which is DAT-12's literal text); DAT-13/DAT-14 (no
release-gating or dataset-card mechanism exists).

A defensive pagination safety cap (`_MAX_PAGES`) was added and tested
(`test_pagination_safety_cap_prevents_an_infinite_loop`) after
recognizing, while writing the fetch loop, that a malformed or
adversarial API response reporting an ever-larger `pages` value could
otherwise spin forever -- caught by review before it could become a
real incident, not found by a failure.

Not covered: FRED, ALFRED, Treasury, Kenneth French, IMF, BIS and UN
Comtrade connectors (the dataset plan's other 7 "P0/P1" sources) do not
exist. FRED/ALFRED specifically need an API key
(`FRED_API_KEY`) this environment does not have configured --
`UrllibTransport` (the real HTTP implementation) is itself untested
against any live endpoint by the committed suite (only mocked), by
design, to keep tests hermetic; its correctness rests on the same class
being exercised live, successfully, by `worldbank.py` during this PR's
own pre-implementation verification. No raw/normalized/feature storage
layer, no freshness/completeness monitoring (DAT-11), no schema-
contract/currency-mapping layer (DAT-10) and no dataset card (DAT-14)
exist. See
[`src/prometheus/data_ingestion/transport.py`](./src/prometheus/data_ingestion/transport.py) and
[`src/prometheus/data_ingestion/worldbank.py`](./src/prometheus/data_ingestion/worldbank.py).

## Evidenced today (PR-061: extreme-input solver robustness -- SDE-12 and VAL-13)

Closes two original-blueprint items left explicitly open since PR-057
("SDE-11/SDE-12 ... remain separately open and NOT addressed by this
PR"): SDE-12 ("test solver behavior on extreme but admissible inputs
... no silent NaN, Inf or unbounded accepted paths") and VAL-13
("perform NaN/Inf injection and solver fail-closed tests ... no invalid
output promoted or silently cached"). Both were tackled with the same
discipline already used throughout this project: an empirical scratch
probe across every VOLTERRA pricer and STOCHASTICA simulator first, to
find REAL bugs rather than assume none exist, production fixes second,
then a broad Hypothesis property-test file
(`tests/property/test_extreme_input_robustness.py`) asserting the core
invariant going forward: every pricer either returns a finite price or
raises a clear, named `ValueError` -- never an uncaught exception of any
other type, never a silent NaN or Inf.

The initial probe, and the property-test file's own repeated runs
against fresh random examples (Hypothesis is not seeded; re-running it
found MORE bugs each time until none were left), surfaced **seven**
distinct, real, previously-undiscovered defects, not one or two:

1. **Barrier options, wrong-answer bug**: `barrier_option_price` silently
   returned `0.0` instead of matching the vanilla price at tiny
   volatility, because the reflection-principle integration bounds were
   centered on log-return `0` instead of the TRUE drift `nu*maturity`.
2. **Barrier options, dormant quadrature-kink bug**: fixing (1) exposed a
   SECOND, previously-dormant bug that had silently existed all along --
   `scipy.integrate.quad` is not automatically aware of the payoff's
   non-smooth kink at `ln(strike/s0)`, and its own reported error
   estimate was unreliable near it (confirmed against an independent
   Simpson's-rule ground truth on a 4-million-point grid). Fixed by
   passing `points=[kink]` to force exact subdivision there.
3. **Barrier options, overflow/no-overlap handling**: three further
   overflow paths (payoff `exp()`, a representable-range check, and the
   `_survival_density` reflected-weight term) needed either a clear
   upfront rejection or, for one specific case (very negative rate, small
   volatility), recognizing that the integration bounds had become
   inverted because the TRUE answer is exactly `0.0` (near-certain
   breach) -- not an error.
4. **Merton jump-diffusion, two domain/overflow crashes plus a THIRD,
   independent one**: a very negative `jump_mean` drives the jump
   compensator to underflow to exactly `-1.0`, making `log(1+k)` a domain
   error; a large `jump_std` drives the adjusted Poisson mean past
   computability. Both are caught upfront now. Broader property testing
   then found a FOURTH path surviving both guards: `r_0 = r -
   jump_intensity*k` alone can already overflow `exp(-r_n*maturity)` at
   `n=0`, even when `k` is finite and the Poisson mean is nowhere near
   its cap (confirmed directly: jump_intensity=1, jump_mean=0,
   jump_std=4 overflows here). Fixed by checking both endpoints of the
   affine-in-`n` range of `r_n` upfront.
5. **Heston, a genuine removable 0/0 singularity**: whenever `kappa ==
   rho*xi` exactly, `heston_characteristic_function(-1j, ...)` -- used
   directly as a normalizing constant, and by this module's own identity
   test -- hits `b == d == 0` simultaneously, a real `ZeroDivisionError`
   in the `g = (b-d)/(b+d)` "little trap" formulation. Fixed by
   special-casing `u == -1j` to the already-known, exact martingale
   identity `phi(-i) = S0*exp((r-q)*T)`, rather than a fragile
   near-zero epsilon patch.
6. **Heston, long-maturity numerical instability**: separately, at a
   long enough maturity the adaptive quadrature probes large real `u`
   where the little-trap formula's own `c`/`cap_d` terms suffer
   catastrophic cancellation, overflowing `cmath.exp` or dividing by an
   exactly-zero term -- even though the TRUE characteristic function
   always satisfies `|phi(u)| <= 1` for real `u` (it is a genuine
   characteristic function), so this is a pure numerical artifact, not
   an unrepresentable answer. No closed-form bound on exactly which
   inputs trigger it was derived (unlike findings 1-5); instead the
   escaping `OverflowError`/`ZeroDivisionError` is caught and converted
   to a clear, named rejection rather than a cryptic crash. Three further
   plain discount-factor overflows (Black-Scholes itself, the
   geometric-Asian pricer's forward, and Heston's own put-parity branch)
   were fixed the same way `volterra.barrier_options` already was, plus
   one `inf * 0.0 == nan` case in Black-Scholes resolved by checking the
   risk-neutral weight BEFORE ever evaluating the discount factor.
7. **GBM simulator, a silent Inf -- found only AFTER this PR's own
   module docstring had already (wrongly) claimed finiteness as an
   unconditional guarantee.** A large enough positive drift sustained
   over a long enough maturity (confirmed directly: mu=5, maturity=142)
   overflows `np.exp` of the cumulative log-return to exactly `inf` for
   the upper tail of simulated paths -- discovered by re-running the
   property-test file again during this PR's own final verification
   pass, after the first round of fixes above had already been written
   up. This is the OPPOSITE direction from the pre-existing, genuinely
   unfixable underflow-to-`0.0` boundary `stochastica.gbm`'s docstring
   already documented (0.0 is a representable, legitimate value; `inf`
   silently returned is exactly what SDE-12's own text prohibits).
   Fixed by checking every GBM-family simulator's own output for
   non-finite values after simulating (`simulate_gbm_paths`,
   `simulate_piecewise_drift_gbm_paths`, `simulate_correlated_gbm_paths`
   all share the `s0*exp(cumsum(...))` pattern) and raising a clear
   `ValueError` rather than returning an array containing a silent
   `inf` -- a POST-HOC check, not a pre-check on the deterministic
   drift alone, since whether a given random path actually overflows
   depends on the realized draws, not just the input parameters.

VAL-13 specifically requires NaN/Inf INJECTION, not merely extreme-but-
finite inputs (the Hypothesis strategies above all use
`allow_nan=False, allow_infinity=False`) -- a genuinely different test,
not assumed to be covered by (1)-(6) above by proximity. Checking
revealed a real, separate gap: every instrument/market/parameter
dataclass validates with ordinary comparisons like `if spot <= 0:
raise`, and EVERY comparison involving NaN (`<=`, `<`, `>`, `>=`, `==`)
is False under IEEE754 -- so `MarketSnapshot(spot=float("nan"), ...)`
raised nothing at all before this PR, and the NaN propagated silently
into every downstream pricing formula. `prometheus.numerics.require_finite`
closes this as the first check in `__post_init__`, applied to all eight
pricing-input dataclasses: `MarketSnapshot`, `EuropeanOption`,
`AmericanOption`, `ForwardContract`, `AsianOption`, `BarrierOption`,
`HestonParams`, `MertonJumpParams`.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| SDE-12 (first evidence) | test solver behavior on extreme but admissible inputs; no silent NaN, Inf or unbounded accepted paths | 10 Hypothesis property tests across Black-Scholes, Heston, Merton, barrier and geometric-Asian pricers plus GBM/Heston/Merton simulators (`tests/property/test_extreme_input_robustness.py`), asserting finite-or-clean-ValueError; findings 1-6 above were each found by this testing and are separately pinned by named regression tests in their own pricer's unit-test file |
| VAL-13 (first evidence) | perform NaN/Inf injection and solver fail-closed tests; no invalid output promoted or silently cached | `prometheus.numerics.require_finite`, wired into 8 dataclasses' `__post_init__`; `test_numerics.py` plus a NaN/Inf regression test in each of `test_black_scholes.py`, `test_american_options.py`, `test_forwards.py`, `test_asian_options.py`, `test_barrier_options.py`, `test_heston.py` and `test_merton_pricer.py` confirm each one now fails closed with a clear `ValueError` instead of silently admitting the NaN/Inf |

Not covered: the raw, non-dataclass-gated simulator entry points
(`simulate_gbm_paths`, `simulate_heston_paths`,
`simulate_jump_diffusion_paths`, `simulate_correlated_gbm_paths`,
`simulate_piecewise_drift_gbm_paths`) still validate with the same
NaN-blind comparison pattern and were NOT hardened by this PR -- VAL-13
is claimed specifically for the pricing-input dataclasses listed above,
not the whole codebase. No closed-form bound was derived for exactly
which Heston (kappa, xi, rho, v0, maturity) combinations trigger finding
6's numerical instability (an FFT/COS-based evaluation, already out of
`heston_pricer`'s stated scope, would likely be more robust there). SDE-11
(parameter-identifiability diagnostics) remains separately open and NOT
addressed by this PR. See
[`src/prometheus/numerics.py`](./src/prometheus/numerics.py),
[`tests/property/test_extreme_input_robustness.py`](./tests/property/test_extreme_input_robustness.py),
[`src/prometheus/volterra/black_scholes.py`](./src/prometheus/volterra/black_scholes.py),
[`src/prometheus/volterra/barrier_options.py`](./src/prometheus/volterra/barrier_options.py),
[`src/prometheus/volterra/merton_pricer.py`](./src/prometheus/volterra/merton_pricer.py),
[`src/prometheus/volterra/heston_pricer.py`](./src/prometheus/volterra/heston_pricer.py),
[`src/prometheus/volterra/asian_options.py`](./src/prometheus/volterra/asian_options.py) and
[`src/prometheus/stochastica/gbm.py`](./src/prometheus/stochastica/gbm.py).

Correction to PR-058's own record: that PR's
`test_gamma_at_the_small_black_scholes_style_bump_would_be_wrong` (barrier
Greeks) asserted that a Black-Scholes-sized finite-difference bump gave
a notably wrong gamma, attributing this to quadrature-noise
amplification by `1/bump^2`. Finding 2 above (the quadrature-kink fix)
incidentally ALSO fixed that inaccuracy -- the small bump is now
accurate too. The test was rewritten
(`test_gamma_is_accurate_at_both_the_default_and_a_smaller_bump`) to
assert the corrected understanding rather than leave a now-false claim
in the suite; the larger default bump is kept as a conservative choice,
no longer a load-bearing fix.

## Evidenced today (PR-062: parameter sensitivity/identifiability diagnostics -- SDE-11)

Closes the last item from PR-057's "SDE-11/SDE-12 ... remain separately
open" note (SDE-12 was closed by PR-061 above; this PR closes SDE-11).
SDE-11's acceptance criterion has two halves, joined by a semicolon:
"impossible values rejected" and "profile or sensitivity reported."

The first half was already true before this PR, not newly built: every
Heston/Merton parameter dataclass's own `__post_init__` already rejects
impossible values (`kappa <= 0`, `rho` outside `[-1, 1]`,
`jump_intensity < 0`, etc.), hardened this session against NaN/Inf
injection too (PR-061's `prometheus.numerics.require_finite`). This PR
does not re-claim or re-test that half; it adds the second half, which
had no evidence anywhere in this repository: a SENSITIVITY report (the
blueprint's "or" means either half satisfies this clause).

`prometheus.volterra.identifiability` reports d(ln price)/d(ln param)
-- an elasticity, dimensionless and comparable across parameters of
very different units/scales, unlike a raw partial derivative -- for
Heston's 5 parameters and Merton's 4, via the same central-difference
bump-and-reprice pattern already used throughout `volterra.*_greeks`.
Cross-checked, not a new untested formula: Heston's v0 elasticity,
un-normalized back to a raw derivative, matches
`heston_greeks.heston_finite_difference_greeks(...).vega` to 9+
significant figures (both differentiate the same pricer the same way).

Two genuine, data-driven findings came out of actually running this at
several maturities, not assumed from outside literature:

1. **Heston's kappa and rho are consistently the two least
   price-identifiable parameters.** At a representative at-the-money
   parameter set, swept across T=0.1, 1.0 and 10.0, kappa and rho both
   have the two smallest-magnitude elasticities among Heston's five
   parameters at EVERY maturity tested (|elasticity| <= 0.02, versus
   0.01-0.44 for theta/xi/v0) -- the price of a single vanilla call is
   relatively insensitive to the variance mean-reversion speed and the
   spot-variance correlation, regardless of maturity. This matches
   well-known Heston calibration folklore (both are notoriously hard to
   pin down from vanilla prices alone without a full surface or
   time-series data) but is confirmed here directly, by computation.
2. **Merton's jump_mean shows an analogous pattern.** Unlike an initial,
   less careful probe suggested (comparing a semi-elasticity for
   jump_mean against proper elasticities for the other three
   parameters -- an inconsistent comparison, corrected before trusting
   it), the properly-normalized elasticity shows jump_mean IS
   consistently the smallest-magnitude of Merton's four parameters, by
   9x-34x depending on maturity -- the mean log-jump-size is the
   hardest of the four to pin down from a single vanilla price.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| SDE-11 (first evidence) | implement parameter constraints and identifiability diagnostics; impossible values rejected, profile or sensitivity reported | constraints: pre-existing `HestonParams`/`MertonJumpParams` validation, hardened by PR-061's `require_finite`; sensitivity: `heston_parameter_elasticities`/`merton_parameter_elasticities`, cross-checked against existing Heston vega and pinned by `test_kappa_and_rho_are_the_least_identifiable_heston_parameters`/`test_jump_mean_is_the_least_identifiable_merton_parameter` |

Not covered: no profile-likelihood sweep (the OTHER half of "profile OR
sensitivity" this ID's acceptance criterion offers as an alternative) --
`volterra.calibration` only solves implied Black-Scholes volatility (a
single parameter), so there is no multi-parameter calibration objective
to profile against; sensitivity is the half actually implemented. No
joint (multi-parameter) collinearity/condition-number diagnostic, only
per-parameter marginal sensitivity. Elasticity is undefined at a
parameter value of exactly `0.0` (raises `ValueError` rather than NaN),
so a caller who wants rho or jump_mean fixed at exactly 0 cannot get an
elasticity for it this way. See
[`src/prometheus/volterra/identifiability.py`](./src/prometheus/volterra/identifiability.py).

## Evidenced today (PR-063: golden reference-value suite and MC confidence-interval coverage -- VAL-01 and VAL-02)

Correctly closes the two items from the VAL-01/03/14 misattempt
(mentioned several times above) that were never actually claimed for
anything -- only wrongly claimed for PR-056's unrelated forecasting
work, then retracted. VAL-03 was later, correctly, closed by PR-057
(a genuine stochastic-integrator convergence check). VAL-01 and VAL-02
remained open until now.

**VAL-01** ("define golden analytical test suite for GBM and
Black-Scholes... CI matches known reference values") was never
properly built as a DELIBERATE, labeled suite, even though scattered
tests already touched on it (`test_matches_known_textbook_reference_value`
in `test_black_scholes.py`; `test_zero_volatility_is_deterministic_growth`
in `test_gbm.py`). `tests/unit/test_golden_reference_values.py`
consolidates and extends this into an explicit suite: the classic
S=100/K=100/r=5%/sigma=20%/T=1 Black-Scholes textbook call AND put
values (each independently re-derived via a direct N(d1)/N(d2)
computation in the test itself, not by calling this project's own
`_d1_d2` helper), put-call parity as an exact algebraic identity, GBM's
driftless martingale property (E[S_T] = S0 exactly at mu=0, for any
sigma/T -- a zero-free-parameter identity), an independently-computed
GBM terminal variance, and GBM's zero-volatility exact deterministic
limit. Runs under this repository's existing GitHub Actions CI
(`.github/workflows/ci.yml`, every push/PR, 4 Python versions),
satisfying "CI matches known reference values" literally.

**VAL-02** ("define MC sampling error test on benchmark payoffs...
expected confidence coverage across repeated simulations") was
genuinely NOT evidenced before this PR: existing Monte Carlo tests
(`test_monte_carlo.py`) checked that one run lands within a few
standard errors of the true price, that SE scales as 1/sqrt(N), and
that the control variate reduces SE -- none of them checked whether
the REPORTED standard error is correctly CALIBRATED, which a single
passing run cannot distinguish from a systematically too-wide or
too-narrow one. `test_confidence_interval_achieves_its_nominal_coverage_rate`
runs `monte_carlo_price_vanilla` independently 300 times (disjoint
fixed seeds, fully deterministic, not flaky) and checks that the true
closed-form price falls inside each run's own reported 95% interval
close to 95% of the time, sized against the analytic standard error of
a binomial proportion rather than a magic tolerance -- confirmed
empirically first (94.7% observed across 300 repeats in a pre-
production probe) before writing the production assertion's band.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| VAL-01 (first evidence) | golden analytical test suite for GBM and Black-Scholes; CI matches known reference values | `tests/unit/test_golden_reference_values.py`, 6 tests, run on every push/PR by the existing GitHub Actions CI |
| VAL-02 (first evidence) | MC sampling error test on benchmark payoffs; expected confidence coverage across repeated simulations | `test_confidence_interval_achieves_its_nominal_coverage_rate` in `test_monte_carlo.py`: 300 independent repeats, 94.7% observed vs 95% nominal coverage of the reported 95% CI |

Not covered: VAL-02's coverage check is run once, for `monte_carlo_price_vanilla`
only (a vanilla European call) -- the Asian/control-variate Monte Carlo
paths (`monte_carlo_price_asian`) share the same underlying sample-
standard-error mechanism but are not separately re-tested for coverage.
No golden suite entry exists yet for Heston/Merton/barrier/Asian
pricers (VAL-01's text names GBM and Black-Scholes specifically; the
other pricers already have their own from-scratch cross-checks under
VAL-14, a different ID, not re-claimed here). See
[`tests/unit/test_golden_reference_values.py`](./tests/unit/test_golden_reference_values.py) and
[`tests/unit/test_monte_carlo.py`](./tests/unit/test_monte_carlo.py).

## Evidenced today (PR-064: property-based metamorphic test suite -- VAL-11)

VAL-11 ("perform property-based and metamorphic test suites... scaling,
parity, relabeling and zero-shock tests documented") names four
DIFFERENT kinds of relationship, not four synonyms for "test more
cases." `tests/property/test_metamorphic_suite.py` builds one Hypothesis
test for each, genuinely distinct from this project's existing property
tests (`test_ledger_invariants.py`'s randomized-action-sequence
invariants; PR-061's `test_extreme_input_robustness.py`'s "finite or
clean reject" check): a metamorphic test does not compare a result to a
known value, it compares two RELATED computations against each other
across a wide, Hypothesis-generated range.

- **Scaling**: `titan.portfolio_greeks` aggregation is linear in
  `quantity` -- scaling every line's quantity by `k` must scale the
  portfolio total by exactly `k`.
- **Parity**: Call - Put = S - K*exp(-rT) must hold, as an exact
  algebraic identity, across a WIDE admissible parameter range for
  Black-Scholes, Heston AND Merton alike -- a genuine upgrade from each
  pricer's own existing parity tests, which check only a handful of
  hand-picked parameter sets, not a swept range.
- **Relabeling**: aggregating the same portfolio lines (or stress-test
  asset weights/shocks) in a different order must not change the total
  -- summation is commutative.
- **Zero-shock**: a stress scenario with an all-zero shock vector must
  produce EXACTLY zero loss, for both `titan.stress_testing`'s
  factor-shock and asset-shock paths.

Writing the Merton parity test found a SIXTH real, previously-untested
crash (on top of PR-061's five SDE-12 findings): `jump_intensity ==
0.0` -- a perfectly ORDINARY, non-extreme parameter `MertonJumpParams`
explicitly permits, not an edge case -- makes `poisson_mean` exactly
`0.0`, and the per-term pricing loop's `n=1` iteration then computes
`math.log(0.0)`, which Python's `math.log` raises on. No existing test
had ever called `merton_call_price`/`merton_option_price` with
`jump_intensity=0` (the pre-existing zero-intensity test exercised only
the SIMULATOR, `simulate_jump_diffusion_paths`, a different code path).
Fixed by collapsing the sum to its single `n=0` term when
`poisson_mean == 0.0` (every `n >= 1` term has exactly zero weight
there anyway), confirmed to then match this module's own Black-Scholes
degenerate limit EXACTLY, not approximately.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| VAL-11 (first evidence) | property-based and metamorphic test suites; scaling, parity, relabeling and zero-shock tests documented | `tests/property/test_metamorphic_suite.py`, 8 Hypothesis tests, one or more per named relationship; found and fixed a 6th real SDE-12-adjacent crash (Merton's `jump_intensity=0.0`) along the way |

Not covered: no metamorphic test for `titan.positions`' own
`value_book`/`total_market_value` scaling/relabeling (it follows from
the same linear-sum structure as `portfolio_greeks`, but is not
SEPARATELY exercised here); no metamorphic test for the barrier or
Asian pricers' own parity (already covered by hand-picked cases under
VAL-14, a different ID, not re-claimed here); no metamorphic test for
the Monte Carlo/simulation side (`monte_carlo_price_vanilla`,
`simulate_heston_paths`, etc.) beyond what PR-061/PR-063 already cover.
See
[`tests/property/test_metamorphic_suite.py`](./tests/property/test_metamorphic_suite.py) and
[`src/prometheus/volterra/merton_pricer.py`](./src/prometheus/volterra/merton_pricer.py).

## Evidenced today (PR-065: action-feasibility invariant audit -- VAL-08)

VAL-08 ("check budget, capital, leverage and action feasibility
always... invariant violation forces explicit fault state") was, like
VAL-01 and VAL-08's own close cousin VAL-02 before it, never formally
claimed even though `econosim.agents` already substantially satisfies
it -- an audit was done first (reading every mutating method in that
module), not assumed, before writing anything new.

Every method that debits an agent's EXISTING balance, or extends NEW
credit, already checks feasibility first and raises a named, structured
exception (not a bare `ValueError`, not a silent no-op or clamp) --
`InsufficientFundsError` (budget/capital: `Household.consume`,
`Firm.pay_wages`, `Bank.receive_repayment`, `Government.collect_tax`,
`Government.pay_transfer`) and `CreditLimitExceededError` (leverage:
`Bank.originate_loan`, and `Government.issue_bonds` through the exact
same code path). Both exceptions carry the relevant amounts as named
attributes (`agent_id`/`requested`/`available`, or
`bank_id`/`capital`/`max_leverage`), confirmed by a NEW Hypothesis
property sweep (`tests/property/test_action_feasibility_invariants.py`)
over randomly generated capital/leverage/spend amounts -- stronger
evidence than the pre-existing hand-picked cases in `test_agents.py`
alone, and the literal "always" in VAL-08's text.

One deliberate exception, stated here rather than silently glossed
over: `Bank.accrue_interest` capitalizes unpaid interest directly into
the loan balance WITHOUT re-checking the leverage cap, so
`loans_outstanding` can organically drift past `capital*max_leverage`
through compounding alone over many periods. This is NOT treated as a
VAL-08 violation -- interest accrual is a passive, mechanical
bookkeeping process, not a discretionary "action" extending new credit
(that is specifically what `originate_loan` represents and gates) --
but the distinction is recorded here precisely rather than asserted
away.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| VAL-08 (first evidence) | check budget, capital, leverage and action feasibility always; invariant violation forces explicit fault state | pre-existing `InsufficientFundsError`/`CreditLimitExceededError` across every debit/credit-extending method in `econosim.agents` (confirmed by reading the whole module); strengthened by a new property sweep over randomly generated amounts, confirming both the rejection AND its converse (an in-budget/at-the-cap action is never over-rejected) |

Not covered: `accrue_interest`'s own leverage drift (see above, a
deliberate design choice, not re-tested as a gap); `titan.portfolio`'s
OPTIMIZATION-time box constraints are a different mechanism (built into
the solver's search, not a post-hoc feasibility check on an arbitrary
proposed action) and are not re-claimed here; HDG-07 ("leverage,
concentration and position constraints... all proposed actions obey
projected feasible region") was, at the time of this PR, separately
open -- that ID's "projected feasible region" language suggested an
action-projection mechanism for the hedging policy's trade proposals
specifically, which did not exist, a different claim from VAL-08's
ledger-level checks above. That gap is closed later, see PR-078. See
[`tests/property/test_action_feasibility_invariants.py`](./tests/property/test_action_feasibility_invariants.py) and
[`src/prometheus/econosim/agents.py`](./src/prometheus/econosim/agents.py).

## Evidenced today (PR-066: regime-switching market baseline -- SDE-06)

A genuinely new STOCHASTICA model, not a test/documentation-only PR
like the last several: `stochastica.regime_switching` adds a
discrete-time Markov-chain regime-switching price process alongside
GBM, Heston and Merton -- a discrete set of regimes, each with its own
drift AND volatility (not drift-only, generalizing
`gbm.simulate_piecewise_drift_gbm_paths`'s piecewise-deterministic
drift to a STOCHASTIC, Markov-driven regime path), with the regime
itself evolving by sampling the current regime's row of a transition
matrix at every step.

SDE-06's two acceptance clauses are both met directly, not by analogy:

- **"Transition probabilities valid"**: `RegimeSwitchingParams`
  rejects any `transition_matrix` whose rows do not sum to exactly 1.0
  (within floating-point tolerance) or that contains an entry outside
  `[0, 1]` -- a genuine row-stochastic-matrix check, not merely "close
  to 1-summing by coincidence."
- **"Stationary test available"**: `stationary_distribution` computes
  the regime-occupancy distribution `pi` (`pi @ P == pi`) generally,
  for any number of regimes, via the eigenvector/null-space method, not
  just a 2-state closed form; `is_stationary_distribution` independently
  checks that fixed-point equation on ANY candidate distribution from
  any source, confirmed to actually discriminate (rejects a
  non-stationary candidate, not just returns `True` on the happy path).

Both were verified three ways before being trusted: against a 2-state
closed form `pi0 = p10/(p01+p10)` derived directly from the
stationarity equation (not recited from outside memory); against a
2,000,000-step empirical long-run simulation of the same chain; and,
for a 3-state chain, by confirming `pi @ P == pi` exactly. The
simulator's own long-horizon regime occupancy was separately checked
to converge to the SAME stationary distribution (a cross-check between
the analytical calculation and the simulator's actual Markov dynamics,
not the same code path tested against itself).

Found and fixed one real, if minor, accuracy issue before trusting the
simulator: `exp(log(s0))` is not bit-exact in float64 (confirmed
directly: `np.exp(np.log(100.0)) == 100.00000000000004`), so the
initial column of simulated paths was off by a few ULPs from `s0` --
fixed by assigning it directly, matching `stochastica.gbm`'s own
existing convention. The single-regime degenerate case (one regime,
self-transition probability 1) was confirmed to match plain GBM's
closed-form terminal moments via a large-sample Monte Carlo comparison
(NOT a bit-exact path comparison -- the regime machinery still consumes
RNG state every step even with only one regime to choose from, so the
two simulators' draw sequences diverge even at the same seed, which is
expected, not a bug).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| SDE-06 (first evidence) | implement regime-switching market baseline; transition probabilities valid and stationary test available | `stochastica.regime_switching`: `RegimeSwitchingParams` validates row-stochasticity; `stationary_distribution`/`is_stationary_distribution` provide the calculation and the independent test, cross-checked against a derived closed form, a 2M-step empirical simulation, and the module's own simulator's long-run regime occupancy |

Not covered: no pricer built on top of this model (no "regime-switching
option price" the way Heston/Merton each have one); no historical
calibration of regime parameters from real data (SDE-10, a separate,
still-open ID); no automatic regime-count selection (the number of
regimes is a caller-supplied input, not inferred). See
[`src/prometheus/stochastica/regime_switching.py`](./src/prometheus/stochastica/regime_switching.py).

## Evidenced today (PR-067: volatility clustering benchmark -- SDE-07)

Another genuinely new STOCHASTICA model: `stochastica.garch` implements
GARCH(1,1) (`r_t = mu + sqrt(h_t)*z_t`, `h_t = omega + alpha*(r_{t-1}-
mu)^2 + beta*h_{t-1}`), the classical benchmark for volatility
CLUSTERING specifically -- a phenomenon none of GBM (constant
volatility), Heston (variance driven by its own independent Brownian
motion, not by past squared returns) or Merton exhibit by construction,
which is the literal "where appropriate" qualifier in SDE-07's text.

`GarchParams` enforces Bollerslev's (1986) stationarity condition
`alpha + beta < 1` directly (not just `alpha, beta >= 0` separately),
since the unconditional variance `omega/(1-alpha-beta)` is otherwise
infinite/undefined. Calibrating these parameters to real historical
data is deliberately NOT attempted here -- that is SDE-10's own,
separate, still-open item; this module only simulates from and
diagnoses an already-specified parameter set, the same scope cut
`heston_pricer`/`merton_pricer` already use relative to
`volterra.calibration`.

**"Autocorrelation and conditional variance diagnostics recorded"**:
`volatility_clustering_diagnostics` returns a structured report (squared-
and absolute-return autocorrelation at several lags, mean conditional
variance, realized variance), not loose values a caller has to remember
to compute. The underlying `autocorrelation` helper correctly aggregates
a MULTI-PATH batch (summing numerator/denominator within each path's own
row), a real bug caught and fixed before trusting it: a naive first
draft flattened the batch into one concatenated series first, which
spuriously pairs the last observation of one path with the first of the
next at every path boundary -- confirmed to introduce a real, if small,
bias via a direct comparison against the correctly-aggregated value.

Verified three ways before being trusted, matching this project's
established discipline: the long-run sample variance of simulated
returns matches the closed-form unconditional variance (confirmed
directly: 0.00050113 sampled vs 0.00050000 theoretical over 500,000
steps); the autocorrelation of SQUARED simulated returns is strongly,
persistently positive (~0.17-0.21 at lags 1-5 across several runs) --
the literal "volatility clustering" signature; and, as a contrasting
negative control, i.i.d. Gaussian returns with the SAME unconditional
variance show essentially zero autocorrelation in their squared values
over the same sample size, confirming the clustering is a genuine model
property, not a measurement artifact any random series would show.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| SDE-07 (first evidence) | implement volatility clustering benchmark where appropriate; autocorrelation and conditional variance diagnostics recorded | `stochastica.garch`'s GARCH(1,1) simulator plus `volatility_clustering_diagnostics`; `test_garch_squared_returns_show_volatility_clustering_unlike_iid_returns` confirms the behavioral signature against a contrasting negative control, not just that the code runs |

Not covered: no GARCH-based option pricer (unlike Heston/Merton, no
"GARCH option price" exists); no calibration to real data (SDE-10,
separate and still open); no GARCH variants beyond the plain (1,1)
specification (EGARCH, GJR-GARCH asymmetric leverage effects, etc.). See
[`src/prometheus/stochastica/garch.py`](./src/prometheus/stochastica/garch.py).

## Evidenced today (PR-068: out-of-sample optimization comparison -- OPT-08)

`titan.rebalancing` (PR-025) already walks forward causally -- period
t's weights come only from a trailing window strictly before it -- but
reports a single multi-period wealth path, not an explicit split-sample
comparison. `titan.out_of_sample` does the narrower, literal thing
OPT-08 asks for: split a returns history into one TRAIN block and one
TEST block, fit minimum-variance weights using ONLY the train block
(`test` is never read before the split), then measure realized variance
on BOTH blocks with those SAME, frozen weights.

The "comparison" exists because the two numbers are NOT expected to
match, and reporting both -- not only the flattering one -- is the
point. Confirmed empirically before writing any production code, not
assumed from theory: across 300 independent (train=60, test=250)-period
trials drawn from the SAME known covariance, mean in-sample variance
(0.00281) < the TRUE optimal portfolio's variance (0.00325, computed
directly from the known covariance, not estimated) < mean out-of-sample
variance (0.00364). Minimum-variance optimization fits the ESTIMATED
covariance, not the true one, so in-sample variance is a systematically
OPTIMISTIC (biased low) measure of the portfolio's true risk, while
out-of-sample variance on fresh data is systematically PESSIMISTIC
(worse even than the true optimum, since estimation error in the
weights themselves adds extra variance no portfolio immune to it would
have). `test_in_sample_variance_is_systematically_optimistic_versus_out_of_sample`
pins this ordering as a regression guard, checked on trial AVERAGES (a
single trial is noisy enough that either side can win by chance).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| OPT-08 (first evidence) | include out-of-sample optimization comparison; train-only parameter estimates, test is untouched | `titan.out_of_sample.compare_in_sample_and_out_of_sample`: fits on `returns[:train_periods]` only, scores the frozen weights on both blocks; the systematic in-sample-optimistic/out-of-sample-pessimistic ordering is confirmed empirically (not assumed) and pinned as a regression guard |

Not covered: only the minimum-variance formulation is compared this way
(not target-return or CVaR); no rolling/walk-forward version of this
specific train/test split (that is what `titan.rebalancing` already
does, a different mechanism, not re-claimed here as OPT-08 evidence).
See
[`src/prometheus/titan/out_of_sample.py`](./src/prometheus/titan/out_of_sample.py).

## Evidenced today (PR-069: default/loss-allocation reconciliation -- ECO-10)

Like VAL-01, VAL-08 and VAL-02 before it this session, ECO-10 was never
formally claimed even though `econosim.insolvency` (PR-049, LED-07)
already substantially satisfies it -- an audit was done first, not
assumed, before writing anything new: "implement defaults and orderly
loss allocation" is literally what `resolve_insolvency`/`allocate_recovery`
already do (a borrower defaulting with insufficient cash; recovery
allocated across creditors under the absolute priority rule --
"orderly" in the specific sense of respecting seniority and splitting
same-tier claims pro rata, not arrival order).

What was genuinely missing was an EXPLICIT, deliberate "claims and
equity loss reconciliation" check, as its own stated identity rather
than inferred from the existing per-bank capital assertions scattered
across `test_insolvency.py`'s other tests (each of which happens to
show the right numbers, but never states the aggregate identity as the
point of the test). `test_claims_written_off_reconcile_exactly_with_
aggregate_equity_loss` adds exactly that: a toy case with 3 creditors
across all three priority tiers (SECURED/SENIOR_UNSECURED/SUBORDINATED)
and a partial recovery, checking that the TOTAL amount written off
across every creditor equals EXACTLY the TOTAL equity (capital) lost by
those same creditors -- no claim extinguished without a matching loss
recognized somewhere, and vice versa.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| ECO-10 (first evidence) | implement defaults and orderly loss allocation; claims and equity loss reconciliation passes toy cases | pre-existing `econosim.insolvency.resolve_insolvency`/`allocate_recovery` (confirmed by reading the module and its existing tests); strengthened with a new, explicit 3-creditor/3-tier toy-case reconciliation test stating the aggregate identity directly, rather than leaving it implicit in scattered per-bank assertions |

Not covered: this reconciliation is checked for ONE toy case (3
creditors, one default event); no property-based sweep across randomly
generated claim counts/tiers/recovery amounts (a reasonable future
extension, not attempted here). The known pooled-liability limitation
`insolvency.py`'s own docstring already discloses (callers must supply
the per-creditor claim breakdown explicitly; it is not inferred from
the borrower's single pooled `loan_account` balance) is unchanged and
not re-litigated here. See
[`src/prometheus/econosim/insolvency.py`](./src/prometheus/econosim/insolvency.py) and
[`tests/unit/test_insolvency.py`](./tests/unit/test_insolvency.py).

## Evidenced today (PR-070: bid/ask spread and liquidity cost model -- LED-09)

Genuinely new functionality, not an audit of pre-existing code like
the last several: every trade in this repository's econosim ledger
(`Household.consume`, `Firm.pay_wages`, market clearing/settlement)
executes at a single price with no bid/ask spread at all -- not
because frictionless trading was ever a deliberate baseline, but
because no spread/liquidity concept existed to apply. `econosim.liquidity`
adds that as a pure, composable quoting/cost model (no ledger side
effects, the same "caller composes it" pattern `econosim.insolvency.
allocate_recovery` already uses for loss allocation, deliberately not
modifying the existing, already-tested `agents.py`/`market_clearing.py`
posting code directly): a buyer pays the ASK (`mid*(1+spread/2)`), a
seller receives the BID (`mid*(1-spread/2)`), and `round_trip_cost`
reports the resulting friction in currency units.

"No zero-cost trades unless explicit frictionless baseline" (LED-09's
literal acceptance clause) is enforced directly in `LiquidityAssumptions.
__post_init__`, not left as a convention a caller might forget:
`spread_bps == 0` REQUIRES `frictionless=True` to be set in the same
constructor call, and `frictionless=True` REQUIRES `spread_bps == 0` --
a caller cannot get a zero-cost quote by accident, only by a flag that
states the choice explicitly.

Demonstrated against the real, unmodified ledger, not just the pure
quoting math in isolation: a household buying the same quantity of
goods at the ASK price pays strictly more, and ends up with strictly
less cash, than the identical trade executed at the frictionless mid
price -- confirmed by composing `LiquidityAssumptions` with
`Household.consume` on two otherwise-identical toy economies and
comparing the resulting ledger balances directly.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| LED-09 (first evidence) | define market bid/ask spread and liquidity assumptions; no zero-cost trades unless explicit frictionless baseline | `econosim.liquidity.LiquidityAssumptions`/`ask_price`/`bid_price`/`round_trip_cost`; the frictionless-requires-explicit-opt-in validation is tested directly, and the resulting wealth difference is demonstrated against the real ledger, not asserted in isolation |

Not covered: this module is NOT wired into `market_clearing.py`'s
existing clearing functions or `Household.consume`/`Firm.pay_wages`
themselves -- it is a standalone, caller-composed cost model a future
PR could connect to those paths, deliberately scoped this way to avoid
modifying the existing, already-tested ledger-posting code in this PR.
No market-maker/intermediary account exists to receive the spread's
proceeds (the same market-maker/clearing-account limitation already
disclosed for general multi-party clearing above); this module reports
the FRICTION COST, not where it settles. See
[`src/prometheus/econosim/liquidity.py`](./src/prometheus/econosim/liquidity.py).

## Evidenced today (PR-071: trade execution/settlement event ordering -- LED-10)

A direct companion to PR-070's liquidity model, closing the same class
of gap: every trade this repository's econosim ledger posts today is
ATOMIC (execution and settlement happen in the same instant, the same
`ledger.post()` call), so there has never been a GAP between "trade
agreed" and "trade settled" for any accounting logic to accidentally
anticipate. `econosim.trade_lifecycle.TradeLedger` adds that gap
explicitly, as a standalone, pure in-memory tracker (no `core.ledger`
side effects, the same composable pattern as PR-069's `allocate_recovery`
and PR-070's `LiquidityAssumptions` -- deliberately not modifying the
existing, already-tested atomic posting code in `agents.py`/
`market_settlement.py`): a `Trade` carries both `executed_at_step` and
`settles_at_step`, and `net_position_as_of(agent, step)` counts ONLY
trades settled by that step.

LED-10's two acceptance clauses are both checked directly, not by
analogy:

- **"Track execution ... event order"**: `TradeLedger.execute` rejects
  a trade recorded with an `executed_at_step` earlier than the last
  one already recorded -- executions must arrive in non-decreasing
  step order, not accepted in whatever order a caller happens to
  submit them.
- **"Trade accounting never anticipates later settlement states"**:
  `test_pending_trade_never_anticipates_its_own_later_settlement`
  executes a trade at step 5 settling at step 10, and checks the
  buyer's and seller's `net_position_as_of` at EVERY step from 5
  through 9 -- not just one spot-check -- confirming the trade
  contributes nothing to either position until step 10 exactly, even
  though it has already executed and is "known" to the ledger.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| LED-10 (first evidence) | track execution, settlement and position event order; trade accounting never anticipates later settlement states | `econosim.trade_lifecycle.TradeLedger`: non-decreasing execution-order enforcement, plus a direct, step-by-step confirmation that a pending (executed-but-unsettled) trade never anticipates its own settlement |

Not covered: this module is NOT wired into the real `core.ledger`/
`econosim.agents` Money-based postings -- it is a standalone event-
ordering tracker a future PR could connect to them (the same scope cut
PR-070's liquidity model makes, for the same reason: avoid modifying
delicate, already-tested posting code in this PR). No settlement-FAILURE
handling (a trade that never settles, or settles short) exists either --
only the ordering/anticipation guarantee for trades that do settle as
scheduled. See
[`src/prometheus/econosim/trade_lifecycle.py`](./src/prometheus/econosim/trade_lifecycle.py).

## Evidenced today (PR-072: inventory nonnegativity enforcement -- LED-03)

A third companion to PR-070/071's pattern: `price_economy.py`'s own
step logic already has a nonnegative-inventory GUARD (`if new_inventory
< 0: raise ValueError(...)`), but it is a bare `ValueError` carrying no
attributes, deeply nested inside a complex multi-market settlement
step, and -- because the goods market's own supply curve is capped at
available inventory by construction -- effectively unreachable by any
test that goes through normal price discovery (confirmed by checking:
no existing test references it, and triggering it legitimately would
require deliberately bypassing that capacity constraint). Rather than
force an artificial test through that narrow, hard-to-reach path,
`econosim.inventory.InventoryAccount` implements the same invariant as
a standalone, directly testable primitive, the same "pure, composable,
not wired into the real ledger" pattern PR-070 (liquidity) and PR-071
(trade lifecycle) already use.

LED-03's two clauses are both checked directly:

- **"Invalid sale or withdrawal rejects with structured error"**:
  `InsufficientInventoryError` carries `available`, `requested` and
  `floor` as named attributes (the same convention
  `econosim.agents.InsufficientFundsError` already uses for cash), not
  a bare string; a rejected withdrawal is confirmed to leave the
  balance UNCHANGED, not partially applied.
- **"Nonnegative inventory unless specified financing exists"**:
  financing is a genuine, usable escape hatch, not a clause satisfied
  by never offering one -- a withdrawal may dip into a NEGATIVE balance
  down to `-financing_limit`, but ONLY when the caller passes
  `financed=True` on that SPECIFIC withdrawal call. Configuring a
  nonzero `financing_limit` on the account does NOT, by itself,
  authorize anything: `test_financing_limit_alone_does_not_authorize_a_
  negative_withdrawal` confirms an un-financed over-withdrawal still
  rejects exactly as if no financing limit were configured at all.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| LED-03 (first evidence) | enforce nonnegative inventory unless specified financing exists; invalid sale or withdrawal rejects with structured error | `econosim.inventory.InventoryAccount`/`InsufficientInventoryError`; 12 tests cover the base nonnegativity enforcement, the structured-error attributes, non-mutation on rejection, and the explicit-opt-in financing escape hatch (including that merely configuring a limit does not implicitly authorize use of it) |

Not covered: this module is NOT wired into `price_economy.py`'s own
step logic or `titan.positions` -- it is a standalone primitive a
future PR could connect to either. `price_economy.py`'s own existing
(and, as noted, effectively unreachable) guard is left as-is, not
removed or refactored, to avoid touching that module's complex,
already-tested orchestration logic in this PR. See
[`src/prometheus/econosim/inventory.py`](./src/prometheus/econosim/inventory.py).

## Evidenced today (PR-073: equity rollforward reconciliation -- LED-04)

A fourth companion in the same series as PR-070/071/072: every agent
already carries a running equity balance (`Household.net_worth`,
`Firm.net_worth`, `Bank.capital`, `Government.net_worth`), updated by
`Account._apply` on every `Ledger.post` call -- but nothing INDEPENDENTLY
recomputes that balance from the transaction history and confirms the
two agree. `econosim.equity_rollforward.reconcile_equity_rollforward`
does exactly that: opening balance plus every CREDIT minus every DEBIT
posted to an account across a given set of transactions, compared
against the account's own reported closing balance. The two numbers
come from genuinely separate code paths -- `Account._apply`'s running
mutation during `Ledger.post`, versus a fresh scan of
`Transaction.postings` here -- so agreement is a real check, not a
tautology.

LED-04's "across all agent sectors" is checked literally, not by
analogy: `test_equity_rollforward_reconciles_across_all_four_agent_sectors`
runs ONE shared toy economy through a representative mix of
transactions (income, consumption, wages, loan origination/repayment,
tax, transfer, interest accrual) touching Household, Firm, Bank AND
Government, then independently reconciles each of the four equity
accounts against the SAME journal. A second test confirms the check
actually discriminates a deliberately tampered closing balance from a
correct one (not just `True` on the happy path); a third confirms the
reconciliation also works as a genuine "rollforward" starting from a
MID-simulation opening balance, not only from zero.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| LED-04 (first evidence) | track equity and P&L across all agent sectors; equity rollforward matches realized changes and flows | `econosim.equity_rollforward.reconcile_equity_rollforward`, independently recomputing each account's closing balance from the transaction journal rather than trusting the account's own running total; exercised across all four agent sectors (Household/Firm/Bank/Government) in one shared toy economy, with a tampered-balance discrimination test and a mid-simulation opening-balance test alongside it |

Not covered: this reconciliation is a pure, caller-invoked function,
not a standing invariant `Ledger.post`/`check_integrity` enforce
automatically on every posting (a future PR could wire it in as such).
No P&L STATEMENT decomposition (splitting the net change into named
categories like "income" vs "realized gains" vs "interest expense") --
only the aggregate increase/decrease total, which is what "equity
rollforward... matches realized changes and flows" literally asks for.
See
[`src/prometheus/econosim/equity_rollforward.py`](./src/prometheus/econosim/equity_rollforward.py).

## Evidenced today (PR-074: Expected Shortfall backtesting/calibration diagnostics -- RISK-09)

`titan.risk_metrics` already had VaR's own exception-coverage test
(RISK-08, PR-006) but nothing that specifically evaluates or backtests
an ES *forecast* -- RISK-09's own explicit gap, flagged in PR-006's
"Not covered" note above. Three additions, each verified empirically
by repeated-trial simulation (false-positive rate at a fixed nominal
size, and detection power against a deliberately miscalibrated
forecast) before being trusted as a formal test:

1. `quantile_score` -- the pinball/quantile loss (Gneiting 2011), the
   strictly consistent scoring function for a VaR quantile forecast.
   Its expectation is minimized exactly at the TRUE quantile; a grid
   search over candidate thresholds against a known Gaussian reference
   confirmed the minimizer lands on the true 95th percentile, not some
   other plausible-looking candidate. Ranks competing VaR models; not a
   pass/fail gate by itself.
2. `expected_shortfall_exceedance_residual_test` -- the McNeil & Frey
   (2000) ES backtest. Directly from ES's own definition (ES_alpha =
   E[loss | loss > VaR_alpha]), the residual loss - es_forecast,
   averaged ONLY over observations that actually exceed var_forecast,
   must be zero under correct calibration; a one-sample t-test of that
   residual is the diagnostic. A 400-trial simulation at nominal size
   0.05 produced an observed false-positive rate of exactly 0.05, and a
   forecast with ES deliberately halved (understating tail risk) was
   flagged essentially every time.
3. `es_unconditional_calibration_test` -- an Acerbi-Szekely
   (2014)-style statistic usable even with ZERO VaR exceedances in a
   sample (the exceedance-residual test above needs at least 2,
   structurally). Derived directly from E[loss * 1{loss>VaR}] =
   (1-alpha)*ES, so its expectation is zero under correct calibration;
   a nonparametric bootstrap standard error plus a normal-approximation
   p-value was confirmed, via a 1,500-trial simulation, to reproduce
   its nominal size closely (0.0953 observed vs. 0.10 nominal; 0.0473
   vs. 0.05). The zero-exceedance edge case was explicitly checked: the
   statistic is then exactly -1.0, not a crash.

All three accept either a single constant VaR/ES threshold (matching
`var_exception_coverage_test`'s existing convention) or a
per-observation forecast array, supporting genuine time-varying
(e.g. rolling GARCH-based) forecast backtesting, not only a fixed
threshold.

A real bug was caught before it reached a formal test: the first
draft of `es_unconditional_calibration_test`'s internal helper divided
the SUMMED tail mass by a single ES value, which is only correct when
the ES forecast is constant -- for a per-observation forecast array it
silently broadcast back out to the wrong shape (mypy's strict
`no-any-return` check on the surrounding public function caught the
symptom; tracing it back showed the normalization had to happen INSIDE
the sum, per-observation, not on the aggregate).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| RISK-09 (first evidence) | ES forecasting evaluation and calibration diagnostics | `titan.risk_metrics.quantile_score` (VaR pinball loss), `expected_shortfall_exceedance_residual_test` (McNeil-Frey residual t-test), `es_unconditional_calibration_test` (Acerbi-Szekely-style statistic with bootstrap p-value, handles zero exceedances); each confirmed by repeated-trial false-positive-rate and detection-power simulation against a known Gaussian reference before being pinned as a test |

Not covered: no Monte-Carlo-simulated exact null distribution for
`es_unconditional_calibration_test`'s statistic (the bootstrap +
normal-approximation p-value is a well-calibrated approximation,
confirmed empirically, not an exact test); no conditional/dynamic ES
backtest that accounts for serial dependence in exceedances (both new
tests treat exceedances as exchangeable, appropriate for i.i.d.
backtesting windows, not for detecting exceedance *clustering* itself).
See
[`src/prometheus/titan/risk_metrics.py`](./src/prometheus/titan/risk_metrics.py).

## Evidenced today (PR-075: interbank payments and reserve settlement, audit -- ECO-11)

An audit PR, same pattern as VAL-01/VAL-08/ECO-10: ECO-11's literal
wording ("interbank payments and reserve settlement") was already
substantially satisfied by two pre-existing, independently-tested
modules, neither of which had ever been tagged against this specific
ID -- `econosim.interbank_market.InterbankMarket` (direct bilateral
interbank lending/repayment, moving each bank's own vault
`reserves_account`: the "payments" half) and
`econosim.central_bank_ledger.CentralBankLedger.settle_interbank_transfer`
(central-bank-mediated reallocation of each bank's settlement
sub-account at a shared central bank: the "reserve settlement" half,
literally).

Confirmed by reading both modules in full before claiming anything,
not assumed from their names: `InterbankMarket.lend`/`repay` and
`CentralBankLedger.settle_interbank_transfer` are already exercised by
`test_interbank_market.py` and `test_central_bank_ledger.py`
respectively, each with its own rejection-path coverage (self-loan,
non-positive amount, insufficient balance, leverage-cap enforcement).
One new test file states the ECO-11 claim explicitly, in one place,
rather than leaving it inferred from those two separate suites: a
combined scenario exercises BOTH mechanisms together, and a second,
discriminating test empirically confirms a claim `central_bank_ledger
.py`'s own docstring already made but never tested directly -- that a
bank's central-bank settlement balance and its own vault
`reserves_account` are genuinely unreconciled instruments (moving money
through one channel leaves the other's balance completely unchanged).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| ECO-11 (first evidence) | interbank payments and reserve settlement | `econosim.interbank_market.InterbankMarket.lend`/`repay` (interbank payments) and `econosim.central_bank_ledger.CentralBankLedger.settle_interbank_transfer` (reserve settlement); `test_eco_11_interbank_coverage.py` states both halves explicitly in one combined scenario, plus a discriminating test confirming the two reserve instruments are genuinely unreconciled, not merely documented as such |

Not covered: the two reserve instruments remain deliberately
unreconciled (a pre-existing, honestly-documented limitation, not
introduced here) -- a transfer through one channel has no effect on
the other, so there is still no single unified "a bank's total
reserves" view spanning both. No cross-bank customer-deposit movement
accompanies `settle_interbank_transfer` (also pre-existing and
documented in `central_bank_ledger.py`'s own module docstring): it
balances only at the whole-BANK-sector level, not for each individual
bank, unless a caller posts the matching deposit leg itself.
See
[`src/prometheus/econosim/interbank_market.py`](./src/prometheus/econosim/interbank_market.py),
[`src/prometheus/econosim/central_bank_ledger.py`](./src/prometheus/econosim/central_bank_ledger.py).

## Evidenced today (PR-076: moving block bootstrap for serial dependence -- EXP-09)

EXP-09 was explicitly flagged as not implemented earlier in this document
("The design does not implement a temporal block bootstrap or claim
EXP-09 acceptance"): every existing bootstrap in this repository
(`experiments.bootstrap.paired_bootstrap_difference`, the nested/crossed
mixture bootstraps) resamples individual observations or paired rows,
correct only when those are exchangeable -- none of them resample
CONTIGUOUS blocks, so none of them are valid for a genuinely
serially-dependent series (e.g. autocorrelated returns).
`experiments.block_bootstrap.moving_block_bootstrap` (Kunsch 1989) adds
exactly that: resampling whole blocks of `block_length` consecutive
observations preserves the within-block dependence structure that
single-observation resampling destroys.

Verified on a correlated synthetic test case, matching EXP-09's own
acceptance criterion literally ("Inference verified on correlated
synthetic test cases"), not assumed from the method's textbook
justification: an AR(1) process with phi=0.7 has an exactly-computable
finite-sample variance of its own sample mean, from its known
phi^|i-j| covariance structure -- a ground truth with no simulation
error of its own. Two discriminating comparisons against that ground
truth were run before being trusted as formal tests:

1. Over 40 trials at n=300, block_length=sqrt(n): the ordinary
   single-observation ("i.i.d.") bootstrap's CI width was only ~41% of
   the width implied by the exact true standard error -- badly too
   tight, exactly as expected, since it discards the positive serial
   dependence that genuinely inflates the mean's sampling variance. The
   moving block bootstrap's CI width was ~85% of the true-implied
   width, a large and genuine improvement.
2. A 150-trial, nominal-95% CI coverage check told the same story more
   starkly: the i.i.d. bootstrap's CI covered the true mean (0, by
   construction) only 56% of the time; the moving block bootstrap's
   covered it 87% of the time. Stated honestly, not overclaimed: this
   is a large improvement, not an exact restoration of nominal
   coverage -- a known limitation of the method for short, strongly
   correlated series, documented in the module's own docstring rather
   than discovered later by a caller.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| EXP-09 (first evidence) | support block bootstrap for serial dependence | `experiments.block_bootstrap.moving_block_bootstrap`; verified against an exactly-known AR(1) ground truth (CI-width-to-true-SE ratio and direct 95%-nominal coverage-rate comparison), both confirming a large, genuine improvement over the naive i.i.d. bootstrap on a correlated synthetic test case |

Not covered: the circular variant (Politis & Romano 1992, which wraps
block starts around the end of the series to avoid under-sampling the
tail observations) is not implemented, only the simpler non-circular
moving block bootstrap; no automatic block-length selection rule (the
caller chooses `block_length`, as the existing `paired_bootstrap_
difference` leaves `n_resamples`/`confidence` to the caller too).
See
[`src/prometheus/experiments/block_bootstrap.py`](./src/prometheus/experiments/block_bootstrap.py).

## Evidenced today (PR-077: liquidity and position-capacity constraints -- OPT-06)

`titan.portfolio.PortfolioConstraints` already had a UNIFORM box bound
(`min_weight`/`max_weight`, applied identically to every asset -- OPT-02)
but nothing per-asset, so there was no way to express a genuine
liquidity/participation-limit cap (e.g. "no more than 10% of THIS
specific asset's own average daily volume," naturally different per
asset) -- OPT-06's own explicit gap. A new optional
`max_weight_per_asset: np.ndarray | None` field, and a `_per_asset_bounds`
helper threaded into all three optimizers (`minimum_variance_portfolio`,
`target_return_portfolio`, `cvar_optimal_portfolio`), closes it: each
asset's effective upper bound is min(max_weight, max_weight_per_asset[i])
-- a cap can only ever tighten the uniform bound, never loosen it.
Purely additive: the field defaults to `None`, reproducing every
existing caller's behavior exactly (confirmed by rerunning the full
pre-existing `test_portfolio.py`/`test_rebalancing.py`/
`test_out_of_sample.py` suites unchanged before adding anything new).

OPT-06's own acceptance criterion read literally -- "no portfolio
violates pre-approved participation limits" -- was tested as a
discriminating case, not a vacuous one: a covariance matrix was chosen
so the UNCONSTRAINED minimum-variance optimum genuinely wants to put
more than 76% into the one asset the cap then restricts to 10%,
confirming the cap actually binds and changes the solution, not merely
that it is "obeyed" in a case where it was never close to binding
anyway. OPT-09's existing "no infeasible solution silently labeled
optimal" guarantee was re-confirmed to still hold once a cap makes a
requested target return genuinely unreachable (capping the only
high-return asset at 10% caps the achievable portfolio return at 5.3%,
below a requested 6% target) -- `target_return_portfolio` reports
`success=False` honestly rather than returning a boundary point mislabeled
as optimal.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| OPT-06 (first evidence) | liquidity and position-capacity constraints | `titan.portfolio.PortfolioConstraints.max_weight_per_asset`, threaded through all three optimizers via `_per_asset_bounds`; a discriminating test confirms the cap actually binds against an optimum that would otherwise violate it, and that an unreachable target-return-under-a-cap still reports failure honestly (OPT-09) rather than a silently-clipped false optimum |

Not covered: no minimum-position-size / lot-size (cardinality)
constraint, only a continuous upper cap; no liquidity-COST model feeding
the cap's own derivation (that is `econosim.liquidity`'s bid/ask-spread
model, LED-09, a separate and already-evidenced piece -- the two are
not wired together here). The cap is a fixed input the caller supplies,
not estimated from any market data within this module.
See
[`src/prometheus/titan/portfolio.py`](./src/prometheus/titan/portfolio.py).

## Evidenced today (PR-078: leverage and position-size constraint projection -- HDG-07)

HDG-07 was explicitly flagged as open in this document's own PR-065
entry, which drew the exact distinction this PR closes: VAL-08's
pre-existing ledger-level feasibility checks (`InsufficientFundsError`/
`CreditLimitExceededError` in `econosim.agents`) are a different
mechanism from what HDG-07's own "projected feasible region" wording
asks for -- an action-PROJECTION step for a hedging policy's proposed
trade, applied independently of whatever policy (baseline or learned)
produced it. `HedgePolicyMLP` already tanh-squashes to [-1, 1] (HDG-04),
but that is a fixed architectural bound baked into the policy itself,
not a configurable, economically-stated limit ("no more than N shares,"
"no more than L times capital in notional exposure") checked after the
fact on any policy's output.

`hedging.position_constraints.project_onto_feasible_region` adds
exactly that: given a proposed holding and its paired spot price, it
clips to the intersection of a flat position-size cap and a
leverage-implied notional cap (capital * max_leverage, converted to
units of the underlying via the current spot price) -- the tighter of
the two always binds. A Hypothesis property sweep (matching VAL-08's
own precedent for an "always"-worded requirement, not just hand-picked
examples) confirms the projected result ALWAYS satisfies both bounds
across 300 randomly generated (proposed holding, spot, position cap,
leverage cap, capital) combinations, and its converse: a holding
already inside both bounds is never needlessly altered.

"Concentration" is deliberately not claimed: this repository's hedging
setup is single-underlying per policy (one option, one hedge
instrument), so concentration -- a multi-instrument notion -- is not
independently meaningful here, stated honestly rather than stretched to
fit. The multi-asset analogue already exists in a different setting
(`titan.portfolio.PortfolioConstraints.max_weight_per_asset`, OPT-06,
PR-077).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| HDG-07 (first evidence) | leverage, concentration and position constraints; all proposed actions obey projected feasible region | `hedging.position_constraints.project_onto_feasible_region`/`PositionLimits`; a 300-example Hypothesis property sweep confirms the projected holding always satisfies both the position-size cap and the leverage-implied notional cap, and that an already-feasible holding is never altered; "concentration" explicitly not claimed (not independently meaningful in this repository's single-underlying hedging setup) |

Not covered: not wired into `hedging.simulate.simulate_self_financing_hedge`
or `hedging.comparison`'s existing pipelines as an automatic step --
this is a standalone projection function a caller applies to a policy's
proposed `hedge_ratios` before simulating, not (yet) a mandatory gate
every existing hedging study runs through. No concentration constraint,
per the limitation stated above.
See
[`src/prometheus/hedging/position_constraints.py`](./src/prometheus/hedging/position_constraints.py).

## Evidenced today (PR-079: GDP/inflation/credit definitions, cross-validated -- ECO-15)

ECO-15's acceptance criterion read literally -- "GDP/inflation/credit
definitions documented and validated" -- asks for genuine definitions
checked against the ledger, not merely stated. `econosim.macro_aggregates
.compute_macro_aggregates` defines GDP two independent ways (expenditure
= consumption spending; income = wages + firm profit) and cross-checks
them against each other AND against the firm's own ledger-derived
equity change, a cross-check designed from the start to avoid being a
tautology: `firm_profit_from_ledger` (closing_firm_equity minus
opening_firm_equity, read directly from the ledger) is compared against
`firm_profit_from_flows` (consumption_spending minus wages_paid, the
caller's own running flow totals) -- two genuinely separate code paths,
not one formula checked against itself.

Confirmed on a real `Economy` scenario (Household/Firm/Government, not
a hand-waved example) before being trusted: taxes and transfers, which
touch only Household/Government accounts and never `Firm.equity_account`,
were confirmed to leave GDP completely unaffected even when scaled up
substantially -- exactly what "transfers excluded from GDP" requires
under standard national accounting, verified rather than assumed. A
deliberately dirtied case (an extra mid-period `Firm.capitalize`, an
equity-touching event the caller's flow totals don't know about) was
confirmed to correctly break the reconciliation (`gdp_reconciles=False`)
rather than silently average into profit -- proof the check is a real
discriminator, not one that reports True unconditionally by
construction.

Credit aggregate is the caller's own sum of outstanding bank loans
(this function has no opinion on how many banks exist). Inflation is
the percentage change in a caller-supplied price level between two
periods, honestly scoped to this repository's actual market design:
`econosim.market_clearing` has no endogenous price discovery (its own
docstring: "a buyer and a seller each submit a desired quantity at an
already-given price"), so "the price level" is whatever price the
simulation driver used, not something this module infers.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| ECO-15 (first evidence) | stylized-fact reports and macro aggregate outputs; GDP/inflation/credit definitions documented and validated | `econosim.macro_aggregates.compute_macro_aggregates`; cross-validates GDP's income and expenditure approaches against an independent ledger-derived firm-profit figure on a real Economy scenario, confirms taxes/transfers are correctly excluded from GDP, and confirms a deliberately dirtied period (mid-period capitalization) is correctly flagged rather than silently absorbed |

Not covered: no bank/financial-sector value-added component in the
income approach (interest income/expense is not included in GDP here,
a deliberate simplification stated rather than silently assumed); no
investment or government-purchases category (this model has neither);
no "stylized facts" in the stronger empirical sense (matching known
real-world regularities like procyclical consumption) -- only the
accounting DEFINITIONS and their internal consistency, which is what
the acceptance criterion itself asks for; not wired into any
orchestration module's per-step output yet, a standalone function a
caller applies to its own tracked period totals.
See
[`src/prometheus/econosim/macro_aggregates.py`](./src/prometheus/econosim/macro_aggregates.py).

## Evidenced today (PR-080: automated leakage linter -- DAT-09)

DAT-09's acceptance criterion read literally -- "automated leakage
linter catches future timestamps" -- asks for a DETECTIVE tool, not a
restatement of `econosim.pit`'s existing PREVENTIVE gate
(`require_eligible`/`build_feature_vector`, FP-03, already fail closed
AT ACCESS TIME for any caller that goes through them). A live gate only
protects callers that call it; `econosim.leakage_linter` adds the
complementary batch-audit half: given a LOG of (feature_id/series,
data timestamp, decision time) usage records -- however they were
produced, whether or not the original code even went through
`econosim.pit` -- it flags every one where data was used strictly
before it existed.

`lint_future_timestamp_usage` is the general-purpose core (any raw
timestamp vs. decision-time pair). `lint_pit_store_usage` adapts it to
`PointInTimeStore`, deliberately re-deriving eligibility through the
store's own PUBLIC `as_of` predicate rather than reaching into its
internal records: `PointInTimeStore`'s own docstring states it exposes
no "give me everything regardless of date" accessor specifically so no
caller can bypass the point-in-time rule, and an audit tool earns its
answer through the same gate as everyone else, not a side door. A test
confirms the linter correctly accounts for `asof_eligible_at`
(ingestion-lag), not just raw `published_at` -- a request made after
publication but before the system's own ingestion cutoff is still
flagged, matching `MacroObservation.effective_eligible_at`'s existing
convention exactly.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| DAT-09 (first evidence) | enforce train/validation/test temporal partition on features; automated leakage linter catches future timestamps | `econosim.leakage_linter.lint_future_timestamp_usage` (general) and `lint_pit_store_usage` (PointInTimeStore-integrated, via the store's own public `as_of`, not a privacy-violating direct read); tests cover a clean batch, a flagged leak, multiple simultaneous violations, a never-recorded series, and the asof_eligible_at ingestion-lag case |

Not covered: this is a batch-audit tool a caller runs over an already-
produced usage log, not a CI-wired-in step that automatically scans
every experiment run; no automated discovery of WHERE a usage log comes
from (the caller must already have one). DAT-01..DAT-14's broader
unimplemented scope (FRED-MD/QD ingestion, ALFRED vintages, schema
contracts, freshness monitoring) remains exactly as unimplemented as
`econosim.pit`'s own module docstring already states.
See
[`src/prometheus/econosim/leakage_linter.py`](./src/prometheus/econosim/leakage_linter.py).

## Evidenced today (PR-081: immutable pricing/risk report responses -- API-05)

API-05's acceptance criterion read literally -- "responses reference
market snapshots and model versions" -- had no existing home: `service.
schema.py` generates OpenAPI structural schemas for the research-job
submission/execution API (PR-047), not pricing/risk report response
types, and nothing in the repository bundled a price or risk result
together with an immutable, verifiable reference to the market snapshot
it was computed from.

`service.reports.PricingReportResponse`/`RiskReportResponse` close
that gap: both are frozen dataclasses (confirmed by test to raise
`FrozenInstanceError` on attempted mutation, not merely assumed from
the decorator), carrying `market_snapshot_id` and `model_version`.
`market_snapshot_id` is not an arbitrary caller-chosen label -- it is
`compute_result_hash` (the SAME canonical-JSON SHA256 hash
`evidence.integrity`'s artifact seals already use, reused rather than
reimplemented) applied to the `MarketSnapshot`'s own fields, confirmed
to be deterministic (two separately-constructed but field-identical
snapshots produce the identical id) AND discriminating (changing a
single field changes the id) -- a verifiable property, not a
convention taken on faith. `build_pricing_report`/`build_risk_report`
are the only intended construction path, computing the id from the
snapshot themselves so a response can never carry a snapshot id that
does not actually match the snapshot it claims to describe.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| API-05 (first evidence) | define immutable pricing and risk report responses; responses reference market snapshots and model versions | `service.reports.PricingReportResponse`/`RiskReportResponse` (frozen dataclasses, immutability confirmed by test) plus `build_pricing_report`/`build_risk_report`, which compute `market_snapshot_id` deterministically from the `MarketSnapshot` via the existing `compute_result_hash` utility |

Not covered: not wired into `service.application`'s actual HTTP routes
or `service.schema`'s OpenAPI generator -- these are response TYPES a
caller can build and return, not (yet) an endpoint that serves them;
no model-version REGISTRY (`model_version` is a caller-supplied string,
not independently validated against a known set of deployed versions).
See
[`src/prometheus/service/reports.py`](./src/prometheus/service/reports.py).

## Evidenced today (PR-082: cross-bank transfer settlement-balance preservation, audit -- LED-08)

LED-08's requirement text ("handle deposits, bank reserves, and
interbank settlement") is broad, but its own ACCEPTANCE CRITERION is
narrow and literal: "cross-bank transfer preserves total settlement
balances." Read against that specific wording -- not the broader
requirement text -- this is already substantially satisfied by
pre-existing, separately-tested code: `Bank.reserves_account` (bank
reserves), `InterbankMarket` (direct interbank payments, ECO-11,
PR-075) and `CentralBankLedger.settle_interbank_transfer` (reserve
settlement). An existing test already confirmed total reserve
LIABILITY is preserved across a transfer
(`test_settle_interbank_transfer_reallocates_without_changing_total_liability`,
PR-026); what had never been stated explicitly was the mirror,
ASSET-side claim the acceptance criterion's own words use --
"settlement balances," not "liability."

One new, deliberately more discriminating test closes that gap: it
registers a THIRD bank not party to either transfer at all (the
existing two-bank test is less discriminating here, since summing over
exactly the two parties that swapped funds trivially nets to zero
either way) and confirms the system-wide total of
`settlement_balance_of` across all three registered banks is
unchanged by two separate cross-bank transfers, one of which doesn't
even touch the third bank.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| LED-08 (first evidence) | handle deposits, bank reserves, and interbank settlement; cross-bank transfer preserves total settlement balances | pre-existing `Bank.reserves_account`, `econosim.interbank_market.InterbankMarket` (ECO-11) and `central_bank_ledger.CentralBankLedger.settle_interbank_transfer`; a new three-bank test (`test_cross_bank_transfer_preserves_total_settlement_balances_system_wide`) confirms the system-wide `settlement_balance_of` total is preserved across multiple transfers, including one not touching the third bank at all |

Not covered: the "deposits" half of the broader requirement text
remains the honestly-stated limitation below -- household/firm deposit
balances are not bank-custodied for non-loan flows in this model, so a
general deposit-taking invariant (as opposed to the narrower,
acceptance-criterion-literal settlement-balance check above) would not
yet be a true invariant.
See
[`src/prometheus/econosim/central_bank_ledger.py`](./src/prometheus/econosim/central_bank_ledger.py).

## Evidenced today (PR-083: historical GBM calibration with dated parameter versions -- SDE-10)

SDE-10 was flagged as explicitly open in PR-066/067/069's own
"Not covered" notes above (both the regime-switching and GARCH models
simulate from an already-specified parameter set; neither calibrates
one from data). This PR closes it for GBM specifically, deliberately
NOT for GARCH: a GARCH(1,1) MLE calibration was attempted earlier this
session via three different general-purpose numerical optimizer
configurations (Nelder-Mead with a sigmoid reparameterization, SLSQP
with explicit bounds/`LinearConstraint`, `trust-constr`) and abandoned
after each demonstrated genuine non-robustness -- slow convergence, a
badly identified mean parameter, or solver-dependent failure to
converge from some starting points, exceeding this project's zero-
tolerance-for-flaky-tests standard. GBM carries no such risk: its
log-returns are i.i.d. Gaussian under the model, so the textbook
closed-form sample mean/variance formulas ARE the exact global MLE --
no iterative optimizer, no convergence risk, confirmed rather than
assumed from theory.

The closed-form claim was cross-checked, not just asserted: a general-
purpose numerical optimizer (Nelder-Mead minimizing the negative log-
likelihood directly) was run on the SAME simulated data. A first,
loosely-converged run did NOT match the closed form -- GBM's drift
parameter is famously weakly identified (the likelihood is very flat
along that direction at realistic sample sizes), not a bug -- but
tightening the optimizer's convergence tolerance resolved the
discrepancy to within 1e-4, confirming the closed form was correct all
along and the loose run simply hadn't converged. `CalibrationRecord.
optimizer` is honestly stated as `"closed_form_mle"`, not implying an
iterative search happened.

"Dated parameter versions" is answered by `CalibrationHistory`, reusing
-- not reinventing -- `econosim.pit.PointInTimeStore`'s own point-in-
time discipline: records are queryable only through an `as_of(t)`
predicate (the latest record whose `calibrated_at <= t`), with
deliberately no "give me the latest version regardless of date"
accessor, confirmed order-independent (recording two calibrations out
of chronological order still answers correctly, since the lookup is
driven by `calibrated_at`, not insertion order) and confirmed to
correctly withhold a second, later calibration until its own
`calibrated_at` arrives.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| SDE-10 (first evidence, GBM only) | historical calibration with dated parameter versions; fit windows, optimizer state and calibration error logged | `stochastica.historical_calibration.calibrate_gbm_mle` (closed-form MLE, cross-checked against a tightly-converged general-purpose numerical optimizer) and `CalibrationHistory` (point-in-time versioned lookup, reusing `econosim.pit`'s own as-of convention); GARCH/regime-switching calibration deliberately NOT attempted, see the abandonment reasoning above |

Not covered: GARCH(1,1) and regime-switching calibration remain
unimplemented (see the abandonment reasoning above -- a future attempt
would need either an analytically-derived gradient or a fundamentally
different, less fragile optimization approach before being attempted
again); no rolling/walk-forward recalibration study (the module
supports it structurally via repeated `calibrate_gbm_mle` calls plus
`CalibrationHistory.record`, but no such study has been run here); no
model-selection or out-of-sample validation of the fitted GBM against
alternative models.
See
[`src/prometheus/stochastica/historical_calibration.py`](./src/prometheus/stochastica/historical_calibration.py).

## Evidenced today (PR-084: numerical accuracy budget per API output -- VAL-12)

`service.reports.PricingReportResponse`/`RiskReportResponse` each now
carry a REQUIRED tolerance field per numerical output
(`price_tolerance`; `value_at_risk_tolerance`,
`expected_shortfall_tolerance`) -- VAL-12's own acceptance criterion is
literally "tolerance fields present and tested for violations", so
there is deliberately no default: a silently-defaulted budget would not
be a deliberate declaration by whichever code computed the value, and
`__post_init__` rejects a non-positive tolerance since no computed
value could ever satisfy one. `check_pricing_tolerance`/
`check_risk_tolerance` compare a report's reported value(s) against an
independently obtained reference (a higher-precision recomputation, a
second model, or a Monte Carlo confidence bound) and return a
`ToleranceViolation` (field, reported, reference, absolute error,
tolerance) for each field whose budget is exceeded -- VaR and ES carry
separate budgets and are checked, and reported as violating or not,
independently of each other.

Re-running the full suite to verify this PR surfaced a SEVENTH,
unrelated SDE-12-adjacent crash via `test_extreme_input_robustness.py`'s
own property-based fuzzing (a fresh Hypothesis seed found an input
combination none of PR-061's five or PR-063's sixth finding had ever
drawn): `barrier_options.barrier_call_or_put_price_continuous`'s
discount-factor exponent `-risk_free_rate*maturity` was never checked
against the module's own `_MAX_EXP_ARG` overflow guard at all -- only
the integration bound and the reflected-weight exponent were. Confirmed
directly: rate=-5.0, maturity=142.0 makes `exp(-rate*maturity) =
exp(710)` raise an uncaught `OverflowError`, both (a) from the
knock-out branch's own discounting whenever the integration actually
runs, and (b), independently, from the knock-in vanilla-parity closed
form's two discount factors, which run whenever `knock == "in"`
regardless of whether the knock-out branch's `lower >= upper`
short-circuit skipped discounting entirely. Fixed by folding the
discount exponent into the knock-out branch's existing overflow check,
and adding a second, independent check of both the discount and
dividend-yield exponents immediately before the knock-in parity
computation; re-verified against the exact two failing inputs (both now
raise a clean `ValueError`) and by rerunning the full property suite
five more times with fresh Hypothesis seeds, all passing.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| VAL-12 (first evidence) | set numerical accuracy budget per API output; tolerance fields present and tested for violations | `service.reports.PricingReportResponse`/`RiskReportResponse` carry required per-field tolerances; `check_pricing_tolerance`/`check_risk_tolerance` detect and report violations (`tests/unit/test_service_reports.py`); found and fixed a 7th SDE-12-adjacent crash (barrier option discount-factor overflow, `barrier_options.py`) while re-verifying the full suite |

Not covered: no automatic wiring of these tolerance checks into any
live serving path (`service.application`) -- the dataclasses and check
functions exist and are tested, but nothing in this repository calls
`check_pricing_tolerance`/`check_risk_tolerance` against a live
reference computation as part of handling an actual request; no
registry of per-model-version default tolerances (every tolerance is
supplied explicitly by the caller building the report).
See
[`src/prometheus/service/reports.py`](./src/prometheus/service/reports.py),
[`src/prometheus/volterra/barrier_options.py`](./src/prometheus/volterra/barrier_options.py).

## Evidenced today (PR-085: immutable train/validation/test regime splits -- EXP-04)

EXP-04's own acceptance criterion is literally "immutable split IDs and
holdout manifest", so `experiments.holdout_manifest.DataSplit` is a
frozen dataclass naming one contiguous date range and the regime
("train"/"validation"/"test") it belongs to, and
`build_holdout_manifest` assembles a set of them into a
`HoldoutManifest` whose `manifest_id` is a `compute_result_hash` (the
same canonical-JSON SHA256 hash `evidence.integrity`'s artifact seals
and `service.reports`'s `market_snapshot_id` already use, reused rather
than reinvented) over every split's own fields -- content-addressed, so
changing even one date cutoff by a single day provably changes the id
(confirmed by test, not assumed), while reordering the same splits on
input does not (also confirmed). "Locking the cutoffs" is enforced, not
just claimed: `build_holdout_manifest` rejects duplicate split ids and
any pair of splits whose date ranges overlap (a date must belong to at
most one regime, or a boundary date would ambiguously count as both
train and validation -- exactly the leakage this item exists to
prevent), while deliberately still permitting a gap between regimes
(e.g. a quarantine buffer around a cutoff is legitimate, not an error).
`split_for_date`/`regime_for_date` answer "which regime, if any, does
this date belong to" against a built manifest.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| EXP-04 (first evidence) | lock train/validation/test regimes and date cutoffs; immutable split IDs and holdout manifest | `experiments.holdout_manifest.DataSplit`/`HoldoutManifest`/`build_holdout_manifest` (content-addressed manifest id, order-independent, discriminating on any cutoff change) plus `split_for_date`/`regime_for_date`; 16 tests including overlap rejection, duplicate-id rejection, and a deliberate gap-between-regimes case (`tests/unit/test_holdout_manifest.py`) |

Not covered: no other module in this repository actually CONSTRUCTS a
`HoldoutManifest` for its own train/validation/test data yet -- this is
the general-purpose locking primitive, not (yet) wired into any
specific experiment's own data pipeline; no enforcement that a
downstream model-fitting call actually consults `regime_for_date`
before using a given date's data (that check would need to live in
whichever module owns a concrete dataset, not here).
See
[`src/prometheus/experiments/holdout_manifest.py`](./src/prometheus/experiments/holdout_manifest.py).

## Evidenced today (PR-086: future-data negative control, isolated from any scoreboard -- EXP-05)

EXP-05's own text ("add future-data negative control ONLY for leakage
diagnosis") and acceptance criterion ("diagnostic clearly isolated from
valid model scoreboard") are two separate claims, both evidenced here.
The diagnostic itself (`experiments.leakage_negative_control.
run_future_data_negative_control`) scores the same model twice via two
caller-supplied scoring functions -- one honoring the point-in-time
rule, one deliberately handed data no real deployment could see yet --
and reports `LeakageNegativeControlResult.leakage_gap`
(`leaked_score - valid_score`). Exercised against a genuine
`econosim.pit.PointInTimeStore` scenario, not a toy float pair: a
decision made before the target period's data is published can only
fall back to a naive guess, producing a large positive gap (50.0, the
exact signature a real accidental leak elsewhere would also produce);
the converse case (data already legitimately eligible) confirms the
diagnostic does not manufacture a false-positive gap merely by running.

"Isolated from the scoreboard" is enforced by `assert_
scoreboard_is_leakage_clean`, an `isinstance`-based guard (not a
spoofable string tag) that raises if any entry in a results collection
being assembled is a `LeakageNegativeControlResult` -- a diagnostic
result can be computed and inspected, but cannot be silently folded
into a legitimate reported collection without the assembling code
explicitly bypassing this guard.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| EXP-05 (first evidence) | add future-data negative control only for leakage diagnosis; diagnostic clearly isolated from valid model scoreboard | `experiments.leakage_negative_control.run_future_data_negative_control`/`LeakageNegativeControlResult`/`assert_scoreboard_is_leakage_clean`; 9 tests (`tests/unit/test_leakage_negative_control.py`) including a real `PointInTimeStore` leak scenario (large positive gap), its converse (near-zero gap when already eligible), and the isolation guard rejecting an embedded diagnostic |

Not covered: no automatic wiring of `assert_scoreboard_is_leakage_clean`
into any of this repository's own existing result-producing modules
(`experiments.hedge_benchmark`, `evidence.gate_report`, `evidence.
model_card`) -- the guard exists and is tested standalone, but nothing
currently calls it before assembling those modules' own outputs, since
none of them have ever actually produced a `LeakageNegativeControlResult`
to begin with.
See
[`src/prometheus/experiments/leakage_negative_control.py`](./src/prometheus/experiments/leakage_negative_control.py).

## Evidenced today (PR-087: computational cost and memory benchmarking across methods -- EXP-11)

EXP-11's own acceptance criterion literally names four fields that must
be logged: "hardware, GPU driver, dtype and walltime."
`experiments.cost_benchmark.HardwareInfo` carries `platform`,
`python_version`, `gpu_available` and `gpu_driver`; `MethodCostProfile`
adds `dtype`, `walltime_seconds` and `peak_memory_bytes` (the
"computational cost and memory" half of the requirement text).
`capture_hardware_info` is honest about this environment and this
repository rather than fabricating a GPU reading: this environment's
own PyTorch build is CPU-only (confirmed directly: `torch.cuda.
is_available()` is `False`), and no GPU code exists anywhere in this
repository (the same confirmed limitation VAL-10 already documents), so
`gpu_available=False`/`gpu_driver=None` here -- the fields are PRESENT
and LOGGED, per the literal acceptance criterion, not omitted merely
because there is nothing to report. The `gpu_available=True` branch
(reporting `torch.version.cuda` as the driver) and the "torch not
installed at all" fallback are both exercised by test via monkeypatching
torch's own reporting functions/import, confirmed, not merely trusted
from reading the code, since neither branch can be reached on this
machine's real hardware.

`benchmark_method_cost` times one callable with `time.perf_counter` and
measures its peak memory via the standard library's `tracemalloc` (no
new dependency); verified to actually discriminate, not just return
some number, against a real small-vs-20M-element-array allocation pair.
`benchmark_methods_cost` runs several named methods and returns their
profiles sorted by walltime -- the "across methods" half of the
requirement, verified against a real `time.sleep`-based fast/slow pair.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| EXP-11 (first evidence) | benchmark computational cost and memory across methods; hardware, GPU driver, dtype and walltime logged | `experiments.cost_benchmark.HardwareInfo`/`MethodCostProfile`/`benchmark_method_cost`/`benchmark_methods_cost`; 14 tests (`tests/unit/test_cost_benchmark.py`) including a real memory-discrimination check, a real walltime-ordering check, and monkeypatched GPU-present/torch-absent branches |

Not covered: no automatic wiring of this benchmark harness into any of
this repository's existing pricer/simulator/hedging methods -- the
harness is general-purpose and tested standalone against toy callables,
not yet run against, say, every VOLTERRA pricer or every STOCHASTICA
simulator as a cross-method comparison table; "GPU driver" reports
PyTorch's own build-time CUDA version when a GPU is present, not an
`nvidia-smi`-queried driver string (querying that would need a new
dependency, `pynvml`, unverifiable against real hardware in this
environment regardless).
See
[`src/prometheus/experiments/cost_benchmark.py`](./src/prometheus/experiments/cost_benchmark.py).

## Evidenced today (PR-088: explicit P/Q measure on every report -- AUD-04)

AUD-04's own acceptance criterion is "auditor can differentiate P risk
model from Q pricer." A genuine gap was found, not just an
unevidenced-but-already-true claim: `volterra.market.MarketSnapshot`
already carries a `measure` field (SDE-09), but it is structurally
PINNED to `"Q"` -- every VOLTERRA pricing input is risk-neutral by
construction -- so the snapshot alone can never distinguish a
P-measure risk computation from a Q-measure pricing one. Before this
PR, `PricingReportResponse` and `RiskReportResponse` (API-05/VAL-12,
PR-081/PR-084) were both built from that exact same always-"Q"
snapshot type, with nothing on the RESPONSE itself recording which
measure the reported NUMBER (price, or VaR/ES) was actually computed
under -- an auditor could infer "probably Q" and "probably P" from the
Python class names, but could not read it off the data, and the
inference would be WRONG for a legitimate risk-neutral VaR of a
derivatives book.

Fixed by adding `measure: Literal["P", "Q"]` as its own REQUIRED field
(no default -- `TypeError` if omitted, confirmed by test) directly on
both response types, independent of whatever the underlying
`MarketSnapshot.measure` says. `build_pricing_report`/`build_risk_report`
both require callers to state it explicitly; a discriminating test
confirms a `RiskReportResponse`'s `measure` can genuinely be set to
`"Q"` (not silently forced to `"P"` just because VaR/ES are usually
physical-measure in this repository), and both constructors reject any
value outside `{"P", "Q"}`.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| AUD-04 (first evidence) | capture pricing measure and market snapshot for reports; auditor can differentiate P risk model from Q pricer | `service.reports.PricingReportResponse`/`RiskReportResponse` gain a required `measure` field, independent of `MarketSnapshot`'s own structurally-pinned-to-Q field; 7 new tests (`tests/unit/test_service_reports.py`, 27 total) including the Q-measure-risk-report override case and the no-default `TypeError` check |

Not covered: `MarketSnapshot.measure` itself remains pinned to `"Q"`
only (SDE-09's own design, unchanged) -- a genuinely P-measure pricing
input still has no VOLTERRA-compatible snapshot type to attach to; this
PR only adds the measure tag to the REPORT layer, which is what AUD-04
actually asks for.
See
[`src/prometheus/service/reports.py`](./src/prometheus/service/reports.py).

## Evidenced today (PR-089: a result inventory that retains failed experiment evidence -- AUD-12)

AUD-12's own acceptance criterion is "result inventory contains
exclusions and documented reasons." `experiments.hedge_benchmark`
already retains every seed's own result, but every one of those
results succeeded on its own terms -- there was no concept there of an
ATTEMPT that was tried and explicitly DISCARDED, with a documented
reason, as distinct from one that was tried and kept.
`experiments.result_inventory.ExperimentAttempt` records one attempt
either way: `included=True` requires a `metric_value` (a kept result
with nothing to report would be meaningless); `included=False`
requires the OPPOSITE -- no `metric_value` at all, so an excluded
attempt can never be mistaken for, or used to quietly smuggle back in,
a disguised kept result. `reason` is required unconditionally, for
either outcome.

Demonstrated against this repository's own REAL history, not a
synthetic example: `stochastica.historical_calibration`'s own module
docstring already narrates that three GARCH(1,1) optimizer
configurations (Nelder-Mead with a reparameterization, SLSQP,
trust-constr) were each tried and abandoned for genuine non-robustness
before the GBM closed-form MLE actually implemented there was adopted
-- prose, previously, not a structured, queryable inventory entry per
attempt. The test suite builds a `ResultInventory` recording all three
exclusions with their own distinct, real reasons, plus the one
included attempt carrying an ACTUAL `calibration_error` from a real
`calibrate_gbm_mle` call (not a fabricated metric), and confirms
`.excluded`/`.included` correctly partition all four with no overlap.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| AUD-12 (first evidence) | retain failed experiment evidence, not just best outcomes; result inventory contains exclusions and documented reasons | `experiments.result_inventory.ExperimentAttempt`/`ResultInventory`/`build_result_inventory`; 11 tests (`tests/unit/test_result_inventory.py`) including the real GARCH-abandonment-history case (3 exclusions with distinct real reasons, 1 included attempt with a real `calibrate_gbm_mle` metric) |

Not covered: `historical_calibration.py` itself is NOT changed to
construct a `ResultInventory` as part of its own run (this module adds
the general-purpose primitive and demonstrates it against that real
history as DATA, in tests, rather than retrofitting the production
calibration module to build one at run time); no other experiment-
producing module in this repository (`hedge_benchmark`, `block_
bootstrap`, etc.) has been wired to build a `ResultInventory` either.
See
[`src/prometheus/experiments/result_inventory.py`](./src/prometheus/experiments/result_inventory.py).

## Evidenced today (PR-090: agent and hedge decision audit log -- AUD-05)

AUD-05's own acceptance criterion is "action follows observed state in
audit replay." `experiments.decision_audit_log.DecisionLogEntry`
records one action -- who took it, what it was, when the state it was
based on was observed, and when the decision was actually made --
deliberately domain-agnostic: `econosim` agents are timestamped by
calendar `date` (via `date.toordinal()`) while `hedging.online.
OnlineHedgeAccount` has its own discrete, `dt`-spaced step clock with
no calendar mapping at all, so every timestamp here is a single,
globally comparable `float` rather than one hardcoded time type. Unlike
most validated dataclasses in this repository, `DecisionLogEntry`
deliberately does NOT reject a causally-impossible entry at
construction -- consistent with `econosim.leakage_linter`'s own
detective, not preventive, design (PR-080): an audit log's job is to
faithfully record what a real system did, including a genuine
violation if one occurred. `audit_replay` is the actual check, a
separate, independent pass that flags every entry whose `decided_at`
precedes its own `observed_at` as a `CausalityViolation`.

Demonstrated against two REAL scenarios, not synthetic float pairs: a
genuine `OnlineHedgeAccount` rebalancing simulation (clean when each
decision is timestamped at the same step as the spot it reacted to;
flagged when a decision is deliberately timestamped before the spot it
used was ever observed) and a genuine `econosim.agents.Household.
consume` call (clean when decided after the income was observed;
flagged when backdated before it).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| AUD-05 (first evidence) | capture agent and hedge decisions with timestamps; action follows observed state in audit replay | `experiments.decision_audit_log.DecisionLogEntry`/`CausalityViolation`/`audit_replay`; 13 tests (`tests/unit/test_decision_audit_log.py`) including a real `OnlineHedgeAccount` scenario and a real `Household.consume` scenario, each with both a clean and a caught-violation case |

Not covered: no existing module (`hedging.online`, `econosim.agents`)
is itself changed to build a `DecisionLogEntry` as part of its own
execution -- this PR adds the general-purpose audit primitive and
demonstrates it against real calls to both in tests, rather than
retrofitting either production module to log one at call time.
See
[`src/prometheus/experiments/decision_audit_log.py`](./src/prometheus/experiments/decision_audit_log.py).

## Evidenced today (PR-091: risk reports recomputed from raw facts -- AUD-09)

AUD-09's own acceptance criterion is "each report can be recomputed
from raw facts." The formulas themselves were already documented in
prose, not reinvented here: `titan.risk_metrics.historical_var`/
`historical_expected_shortfall` already state their exact mathematical
definition, interpolation/estimator choice and sign convention in
their own docstrings (RISK-02/RISK-04). What this PR adds is twofold:
`service.report_recomputation.MetricFormula` restates each metric's
formula/units/sign-convention as structured, inspectable DATA (not
prose a reader has to go find), and
`recompute_risk_report_from_raw_losses` closes the loop end to end --
given the RAW loss array a `RiskReportResponse` (API-05/VAL-12/AUD-04)
was supposedly built from, it recomputes VaR/ES independently via
those same documented functions, at the report's OWN `alpha`, and
reports any mismatch through `check_risk_tolerance` (reused, not
reimplemented, from PR-084).

Confirmed against a real raw loss array, not a toy float pair: a report
honestly built from `historical_var`/`historical_expected_shortfall`
on that array reproduces with zero violations; a report whose VaR (or,
separately, ES) is deliberately tampered away from what the SAME raw
losses actually produce is caught, with the exact field and error; a
report at a non-default alpha (0.99) is recomputed at ITS OWN alpha,
confirming no hardcoded default is silently substituted.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| AUD-09 (first evidence) | document reporting metric formulas, units and conventions; each report can be recomputed from raw facts | `service.report_recomputation.MetricFormula`/`VALUE_AT_RISK_FORMULA`/`EXPECTED_SHORTFALL_FORMULA`/`recompute_risk_report_from_raw_losses`; 8 tests (`tests/unit/test_report_recomputation.py`) including honest-reproduction, tampered-VaR, tampered-ES and non-default-alpha cases |

Not covered: only `RiskReportResponse` (VaR/ES) is covered -- no
analogous `MetricFormula`/recomputation pathway exists yet for
`PricingReportResponse` (closed-form option prices), since VOLTERRA
pricers are already independently cross-checked against closed-form
references elsewhere (VAL-01) rather than against a single documented
"raw facts" input the way a historical VaR/ES is; nothing in
`service.application` wires this recomputation into any live serving
path.
See
[`src/prometheus/service/report_recomputation.py`](./src/prometheus/service/report_recomputation.py).

## Evidenced today (PR-092: a training provenance manifest sufficient for replay -- AUD-03)

AUD-03's own acceptance criterion is "stored manifest sufficient for
replay at pinned environment." `experiments.training_provenance.
capture_training_provenance` bundles exactly the three things AUD-03
names: the training `config` (whatever hyperparameters the caller's
own training function takes, as a plain mapping), the integer `seed`
that determines all of a run's RNG state, and `environment` -- reusing
`experiments.manifest.runtime_provenance` (Python version, platform,
pinned dependency versions, source-tree SHA256) rather than reinventing
environment capture. `manifest_id` is a `compute_result_hash` over all
three, the same canonical-JSON convention `evidence.integrity`,
`service.reports` and `experiments.holdout_manifest` already use.

"Sufficient for replay" is demonstrated directly against a real
`hedging.deep_hedge.train_deep_hedge` run, not assumed from the
manifest merely carrying a `seed` field: a manifest is captured from
one real training call, then `train_deep_hedge` is called a SECOND
time unpacking ONLY the manifest's own stored `config` and `seed`
(plus the externally-supplied price-path array, which a manifest
cannot itself hold since it is not JSON-serializable config), and the
resulting `objective_history` is confirmed bit-identical to the
original run, value for value. The discriminating converse is also
confirmed: a manifest captured with a DIFFERENT seed replays to a
genuinely different result, so the match above is not a tautology
(e.g. training trivially converging to the same answer regardless of
seed).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| AUD-03 (first evidence) | capture model training config, environment and RNG state; stored manifest sufficient for replay at pinned environment | `experiments.training_provenance.TrainingProvenanceManifest`/`capture_training_provenance`; 8 tests (`tests/unit/test_training_provenance.py`) including a real bit-identical replay of `train_deep_hedge` from the manifest alone, and its discriminating different-seed converse |

Not covered: `train_deep_hedge` itself is not changed to build one of
these manifests as part of its own call -- this PR adds the
general-purpose provenance primitive and demonstrates it against a
real training call in tests, rather than retrofitting the production
training function to capture one at call time; no other training
function in this repository (`hedging.rate_hedge`, etc.) has been
demonstrated against this primitive.
See
[`src/prometheus/experiments/training_provenance.py`](./src/prometheus/experiments/training_provenance.py).

## Evidenced today (PR-093: a deploy manifest any deployment can be recreated from -- CIQ-11)

CIQ-11's own acceptance criterion is "any deployment can be recreated
from recorded artifacts." `service.deploy_manifest.
capture_deploy_manifest` bundles the real `service.application.
ServicePolicy` an instance of this service was actually configured
with (serialized via `dataclasses.asdict`, not re-described by hand), a
`feature_flags` mapping (this repository has no feature-flag system of
its own yet, so it is honestly `{}` in every deployment this codebase
can actually produce today -- the field is present and captured, not
omitted merely because nothing currently sets one), and `environment`
(reusing `runtime_provenance`, the same convention `training_
provenance`/`holdout_manifest` already use).

"Can be recreated" is demonstrated directly, not assumed from the
manifest merely storing a dict: `recreate_service_policy` reconstructs
a `ServicePolicy` from a captured manifest's own stored fields, and the
test suite confirms the reconstructed policy equals the ORIGINAL,
field for field -- against a deliberately NON-default configuration
(every one of `ServicePolicy`'s 9 fields set away from its default),
not just the all-defaults case, which could otherwise pass trivially
even if capture or reconstruction had silently dropped a field back to
its default.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| CIQ-11 (first evidence) | store complete deploy manifests, config and feature flags; any deployment can be recreated from recorded artifacts | `service.deploy_manifest.DeployManifest`/`capture_deploy_manifest`/`recreate_service_policy`; 10 tests (`tests/unit/test_deploy_manifest.py`) including a full non-default-configuration round trip and manifest-id discrimination on both the policy and the feature flags |

Not covered: `service.application`/`service.__main__` are not changed
to actually CALL `capture_deploy_manifest` as part of starting a real
service process -- this PR adds the general-purpose manifest primitive
and demonstrates it against the real `ServicePolicy` type in tests,
rather than wiring deploy-time capture into the service's own startup
path; `feature_flags` has no real content to capture today since no
feature-flag system exists in this repository.
See
[`src/prometheus/service/deploy_manifest.py`](./src/prometheus/service/deploy_manifest.py).

## Evidenced today (PR-094: secret scanning and a severity-gated release decision -- CIQ-05)

CIQ-05 names three scan types (vulnerability, dependency, secret); only
secret scanning is honestly implemented here. A genuine vulnerability/
dependency scan needs a live, frequently-updated CVE database, which
this repository's own hermetic-test discipline (PR-060's World Bank
connector embeds real recorded responses rather than depending on live
network calls at test time) has no reliable way to query in this
environment -- fabricating scan results against a database that was
never actually queried would misrepresent what was checked.
`evidence.security_scan.secret_scan` needs no such dependency: it
matches a fixed, self-contained set of regex patterns (AWS access key
IDs, PEM private key headers, generic `api_key="..."`-style
assignments) directly against caller-supplied file contents.

`evaluate_release_gate` -- CIQ-05's own acceptance criterion, "high/
critical findings block release unless approved" -- is deliberately
SCANNER-AGNOSTIC: it accepts any `ScanFinding` sequence, so a future
real dependency/vulnerability scanner could plug into the exact same
gate unchanged. Each finding's `finding_id` (a `compute_result_hash`
over scanner/location/description, the same convention this project's
other manifests use) lets one specific finding be approved without
blanket-approving every other finding sharing its category
description -- confirmed by a discriminating test.

Confirmed against both synthetic fixtures AND a genuine self-check:
scanning this repository's own real `src/` tree (100+ files, not an
empty directory) today finds zero secrets.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| CIQ-05 (first evidence, secret scanning only) | run vulnerability, dependency and secret scans; high/critical findings block release unless approved | `evidence.security_scan.ScanFinding`/`secret_scan`/`evaluate_release_gate`/`ReleaseGateDecision`; 15 tests (`tests/unit/test_security_scan.py`) including a real zero-findings self-scan of this repository's own `src/` tree and a discriminating per-finding approval-scoping test |

Not covered: vulnerability and dependency scanning are NOT implemented
(no live CVE database query exists in this environment, see above);
`evaluate_release_gate` is not wired into CI (`.github/workflows/ci.yml`)
or any real release process -- it exists and is tested as a
standalone, scanner-agnostic primitive.
See
[`src/prometheus/evidence/security_scan.py`](./src/prometheus/evidence/security_scan.py).

## Evidenced today (PR-095: per-series data quality monitoring -- DAT-11)

DAT-11's own acceptance criterion is "alerts and quality summary
visible per dataset." `econosim.data_quality.summarize_data_quality`
operates on a plain `Sequence[MacroObservation]` the CALLER already
holds -- deliberately NOT by reading `econosim.pit.PointInTimeStore`'s
own internals, since that store exposes no "give me everything"
accessor (by design, to prevent decision code from bypassing the
point-in-time rule) and a monitoring tool gets no special exemption
from that boundary; `all_eligible_as_of` would not suffice either, since
it collapses to only the latest eligible vintage per key, losing
exactly the duplicate/revision signal this module needs.

Reports, per series: `n_conflicting_duplicates` (the exact same
observation_at/published_at/revision_id recorded more than once with a
DIFFERENT value -- a genuine ingestion conflict; an identical
re-ingestion of the SAME value is correctly NOT flagged, confirmed by
test), `n_revised_observation_dates` (more than one distinct
effective-eligibility date for the same observation_at -- ordinarily
legitimate, counted but not itself an alert), freshness (`staleness_days`
against the SAME effective-eligibility gate -- the later of
`published_at` and `asof_eligible_at` -- `econosim.pit` itself uses,
confirmed by test rather than using raw `published_at` alone), and
completeness (`expected_count` vs. the actual observation count).
Alerts fire only past a caller-supplied threshold, confirmed on both
sides of the boundary for both staleness and completeness.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| DAT-11 (first evidence) | monitor freshness, completeness, duplicates and revisions; alerts and quality summary visible per dataset | `econosim.data_quality.DataQualitySummary`/`summarize_data_quality`; 9 tests (`tests/unit/test_data_quality.py`) including the conflicting-duplicate-vs-harmless-re-ingestion discrimination and the `asof_eligible_at`-honoring freshness case |

Not covered: no existing ingestion pipeline (`data_ingestion.worldbank`)
is itself changed to call `summarize_data_quality` as part of its own
run; no dashboard/UI surface exists to make the summary "visible" in
the sense of a real operator-facing display (UIX remains entirely
unaddressed).
See
[`src/prometheus/econosim/data_quality.py`](./src/prometheus/econosim/data_quality.py).

## Evidenced today (PR-096: dataset fingerprinting for normalized data and feature transformations -- DAT-12)

DAT-12's own acceptance criterion is "every model reproduces dataset
fingerprint exactly." `experiments.dataset_fingerprint.
compute_dataset_fingerprint` hashes a normalized/feature array
together with the name of the transformation that produced it, via
`compute_result_hash` (the same canonical-JSON convention this
project's other manifests already use).

Demonstrated against a REAL transformation, not a synthetic array:
raw GBM price paths (`stochastica.gbm.simulate_gbm_paths`) converted to
log returns, the same feature `stochastica.historical_calibration`
consumes. Two separately-computed log-return arrays from independent
copies of the SAME raw price paths produce the bit-identical
fingerprint ("every model reproduces ... exactly," confirmed directly);
a DIFFERENT transformation (simple returns) on the same raw data, and
even the same numeric values under a different declared
`transformation_id`, each produce a different fingerprint
(discriminating). `verify_dataset_fingerprint` is sensitive to a
genuinely tiny perturbation (1e-9) -- confirming this is a real exact-
reproduction check, not a loose approximate one.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| DAT-12 (first evidence) | hash normalized data and feature transformations; every model reproduces dataset fingerprint exactly | `experiments.dataset_fingerprint.DatasetFingerprint`/`compute_dataset_fingerprint`/`verify_dataset_fingerprint`; 9 tests (`tests/unit/test_dataset_fingerprint.py`) including a real GBM-price-to-log-return reproduction case and a 1e-9-perturbation detection case |

Not covered: no existing module (`historical_calibration`, `data_
quality`, etc.) is itself changed to call `compute_dataset_fingerprint`
as part of its own run -- this PR adds the general-purpose
fingerprinting primitive and demonstrates it against a real
transformation in tests, rather than wiring it into a production
feature pipeline.
See
[`src/prometheus/experiments/dataset_fingerprint.py`](./src/prometheus/experiments/dataset_fingerprint.py).

## Evidenced today (PR-097: capacity/quota rejection with transparent reasons -- REL-10, audit)

REL-10's own acceptance criterion is "requests exceeding quota rejected
with transparent reason." An audit (not new production code) found
this already substantially satisfied by pre-existing, separately-
tested code: `service.application.ServicePolicy`/`Admission` already
define and enforce a per-owner request-RATE quota
(`requests_per_owner`) and a global rate budget (`requests_global`),
each rejecting with the distinct, named error code `"rate_limited"`;
`jobs.store.QueuePolicy`'s `max_pending_per_owner` independently
enforces a PENDING-QUEUE quota, rejecting with the distinct code
`"quota_exceeded"` -- but no existing test had ever stated the REL-10
claim explicitly (that these are genuinely DIFFERENT, so a caller can
tell WHICH quota it exceeded), only exercised each mechanism
separately for its own unrelated purpose.

One new, deliberate test,
`test_rel_10_capacity_quotas_reject_with_distinct_transparent_reasons`,
states the claim directly: both quota types reject with their own
named code, a request within either quota still succeeds, and the two
rejection codes are confirmed genuinely different from each other (not
just individually present).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| REL-10 (first evidence, audit) | define capacity reservation and user quota policies; requests exceeding quota rejected with transparent reason | pre-existing `ServicePolicy.requests_per_owner`/`requests_global` (`"rate_limited"`) and `QueuePolicy.max_pending_per_owner` (`"quota_exceeded"`); one new deliberate test stating the claim explicitly (`tests/unit/test_service_http.py`) |

Not covered: no explicit "capacity RESERVATION" concept (pre-allocating
guaranteed capacity to a specific owner) exists -- only rejection past
a shared budget; `max_inflight` concurrency ("overloaded") is a
related but separate capacity limit, not itself re-claimed here since
it is not phrased as a per-user quota.

## Evidenced today (PR-098: model registry states, transition policy and a promotion gate -- MLO-08, MLO-10)

`evidence.model_registry.ModelRegistryEntry` holds exactly the five
states MLO-08 names (candidate/evaluated/approved/staged/retired) with
a complete, append-only `history` of every `StateTransition` (actor,
timestamp, and a REQUIRED `reason` -- the audit-trail half of MLO-08's
acceptance criterion, "transition policy enforced by code and audit
trail"). `is_allowed_transition` is a pure function stating the policy
itself, not merely documented in prose: the only forward path is
candidate -> evaluated -> approved -> staged -> retired, any
non-retired state may ADDITIONALLY move directly to retired (an
emergency pull is legitimate at any stage), and every other transition
-- including skipping a state or moving backward -- is rejected with
`IllegalTransitionError`, confirmed by a parametrized discriminating
test over 4 distinct illegal moves.

`promote_to_approved` layers MLO-10's own acceptance criterion
("promotion gate test denies incomplete candidates") directly on top
of that SAME policy rather than duplicating it -- it still calls
`entry.transition("approved", ...)`, so a candidate never evaluated is
rejected by the policy exactly as any other illegal move would be,
confirmed by a dedicated test that a complete, passing manifest and
validation result do NOT bypass the underlying state machine. On top
of that, it additionally requires both a `training_provenance.
TrainingProvenanceManifest` (reused from AUD-03, not reinvented) and a
passing validation result, denying promotion -- with the EXACT missing
piece named in the error -- for a missing manifest, a missing
validation result, and a failed validation result, each confirmed
separately.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| MLO-08 (first evidence) | create registry states: candidate/evaluated/approved/staged/retired; transition policy enforced by code and audit trail | `evidence.model_registry.ModelRegistryEntry`/`StateTransition`/`is_allowed_transition`; 25 tests (`tests/unit/test_model_registry.py`) including the full forward path, emergency retirement from every state, and 4 illegal-transition cases |
| MLO-10 (first evidence) | block deployment for missing provenance or validation; promotion gate test denies incomplete candidates | `evidence.model_registry.promote_to_approved`, layered on the same transition policy, reusing `training_provenance.TrainingProvenanceManifest` (AUD-03); separately denies missing provenance, missing validation, and failed validation, and confirms the underlying state machine is not bypassed |

Not covered: no "rejected" or "evaluation failed" state exists outside
the 5 MLO-08 explicitly names -- a candidate that fails evaluation has
no distinct terminal state other than `retired`; no persistence layer
(every `ModelRegistryEntry` is in-memory only, there is no registry-
wide store of multiple entries or a query interface across them).
See
[`src/prometheus/evidence/model_registry.py`](./src/prometheus/evidence/model_registry.py).

## Evidenced today (PR-099: content-hashed, immutable model packages -- MLO-07)

MLO-07's own acceptance criterion is "every model package resolves to
unique content hash." `evidence.model_package.ModelPackage` is a
deliberately LIGHTWEIGHT, frozen record -- a model/version label plus
a `content_hash` -- not a container for the artifact's own
(potentially large) bytes, the same separation `evidence.integrity`'s
checksum seals already draw between a hash and the content it covers.
`build_model_package` computes `content_hash` via plain SHA256 of the
artifact's actual bytes (not the canonical-JSON `compute_result_hash`
convention this project's other manifests use, since an artifact's
bytes are an opaque binary blob, not a JSON-serializable payload).

Grounded in a REAL serialized artifact, not a synthetic byte string: a
`torch.save`d `state_dict` of an actual `HedgePolicyMLP`. Two separate
packaging calls on independently re-serialized copies of the SAME real
model state resolve to the identical hash ("resolves to ... unique
content hash," confirmed deterministic); a genuinely different model
(a different seed's trained weights) resolves to a different hash
(confirmed discriminating, not a tautological constant).
`verify_package_integrity` demonstrates "immutable approved packages"
directly: it independently re-hashes an artifact's bytes (as if
re-reading them from separate storage) and compares against the
package's own recorded hash, catching both a single-byte tamper and a
completely different artifact.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| MLO-07 (first evidence) | version artifacts and keep immutable approved packages; every model package resolves to unique content hash | `evidence.model_package.ModelPackage`/`build_model_package`/`verify_package_integrity`/`PackageIntegrityError`; 11 tests (`tests/unit/test_model_package.py`) grounded in a real `torch.save`d `HedgePolicyMLP` artifact, including a single-byte tamper detection case |

Not covered: no real artifact STORE exists (on disk or otherwise) --
`verify_package_integrity` takes the comparison bytes directly from
the caller rather than reading them back from a storage layer this
repository implements; no integration with `evidence.model_registry`'s
`approved`/`staged` states (a package is not itself wired to block an
`approved` transition the way `promote_to_approved` already checks
training provenance and validation).
See
[`src/prometheus/evidence/model_package.py`](./src/prometheus/evidence/model_package.py).

## Evidenced today (PR-100: controlled model rollback with stale-cache purge -- MLO-12)

MLO-12's own acceptance criterion is "rollback test confirms restored
model and stale-cache purge." `evidence.model_serving.ModelServingSlot`
models a minimal real serving layer: which `model_package.ModelPackage`
(MLO-07) is currently served, plus an inference cache keyed by
`(content_hash, input_key)` -- a realistic reason a stale-cache purge
matters at all: a prediction cached under one model version must never
be served as if it came from a different version, even if the input
happens to match. `rollback_to` restores a target package as current
and purges every cache entry NOT keyed to that package's own
`content_hash`, SELECTIVELY: an entry already computed under the model
being restored TO remains valid and is deliberately preserved, not
needlessly recomputed, confirmed by a dedicated test with a call
counter showing the compute function is genuinely not re-invoked.

Both halves of the acceptance criterion are checked by separate,
dedicated tests: the restored model matches the target's content hash
exactly, and a cache entry belonging to the ABANDONED model is
confirmed absent after rollback (not merely that total cache size
"looks about right").

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| MLO-12 (first evidence) | implement controlled model rollbacks and retirement; rollback test confirms restored model and stale-cache purge | `evidence.model_serving.ModelServingSlot`/`deploy`/`cached_predict`/`rollback_to`; 6 tests (`tests/unit/test_model_serving.py`) including exact-restoration, stale-entry-purged, and valid-entry-preserved cases |

Not covered: "retirement" itself (as opposed to rollback) is not
separately modeled here -- `evidence.model_registry`'s own `retired`
state (MLO-08) already covers that half; this module is not wired to
check the registry's state before allowing a rollback (a package could
be rolled back to even if its own registry entry were `retired`).
See
[`src/prometheus/evidence/model_serving.py`](./src/prometheus/evidence/model_serving.py).

## Evidenced today (PR-101: early stopping that structurally forbids the test regime -- MLO-06)

MLO-06's own acceptance criterion is "test set never used for
hyperparameter selection." `experiments.early_stopping.EarlyStopper.step`
requires its caller to declare, on EVERY call, which
`experiments.holdout_manifest.Regime` (EXP-04's own regime vocabulary,
reused directly) the metric it is reporting came from, and raises
`NonValidationRegimeError` immediately for anything other than
`"validation"` -- the test-set prohibition is enforced structurally, at
the single choke point every stopping decision passes through, not a
convention callers are merely trusted to follow. A rejected call is
confirmed to leave the stopper's internal state completely unchanged
(no partial update before the check fails).

Demonstrated against a real `HoldoutManifest`, not a caller simply
typing the string `"validation"` by hand: a simulated training loop
looks up each epoch's regime from an actual calendar date via
`regime_for_date`, and a separate test confirms that a date which
genuinely resolves to the `"test"` regime is rejected by `step` exactly
as the hand-typed case would be. The patience/improvement logic itself
is also verified independently: an exact stop-epoch over a known loss
sequence, and the discriminating case that a late improvement resets
the no-improvement counter rather than merely updating the recorded
best value while still counting toward patience.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| MLO-06 (first evidence) | implement early stopping using validation only; test set never used for hyperparameter selection | `experiments.early_stopping.EarlyStopper`/`EarlyStoppingDecision`/`NonValidationRegimeError`; 11 tests (`tests/unit/test_early_stopping.py`) including a real `HoldoutManifest`-driven simulated training loop and a genuine test-regime-date rejection |

Not covered: no existing training function in this repository
(`hedging.deep_hedge.train_deep_hedge`, etc.) is itself changed to use
`EarlyStopper` -- this PR adds the general-purpose, leakage-resistant
primitive and demonstrates it against a real `HoldoutManifest` lookup
in tests, rather than wiring it into a production training loop.
See
[`src/prometheus/experiments/early_stopping.py`](./src/prometheus/experiments/early_stopping.py).

## Evidenced today (PR-102: champion/challenger comparison with matched data -- MLO-14)

MLO-14's own acceptance criterion is "champion/challenger report
generated with matched data." `evidence.champion_challenger.
build_champion_challenger_report` checks that the champion genuinely
WAS approved by reading `model_registry.ModelRegistryEntry.history`
(MLO-08's own audit trail, reused rather than trusting an unchecked
caller-asserted label) for at least one `approved` transition --
confirmed to still accept a champion that has since moved on to
`staged` (the "last approved" one need not be CURRENTLY approved), and
confirmed to reject one that was never approved at all.

"Matched data" is enforced, not assumed: `champion_outcomes` and
`challenger_outcomes` must have identical shape, rejected otherwise.
The comparison itself reuses `experiments.bootstrap.
paired_bootstrap_difference` (PR-008) rather than reinventing a
statistical test. `higher_is_better` has no default -- getting it
backwards would silently invert which model the report concludes is
better -- confirmed by a discriminating test that flipping it flips
which side of the confidence interval decides `challenger_is_better`.

Grounded in a REAL comparison, not synthetic arrays: the classic
Black-Scholes delta hedge (champion) against the same hedge with a
cost-reducing no-trade band (challenger, `hedging.baseline.
apply_no_trade_band`), both evaluated on the IDENTICAL simulated price
paths via `hedging.simulate.simulate_self_financing_hedge`, compared on
Expected Shortfall (`titan.risk_metrics.historical_expected_shortfall`).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| MLO-14 (first evidence) | support comparison against last approved champion model; champion/challenger report generated with matched data | `evidence.champion_challenger.ChampionChallengerReport`/`build_champion_challenger_report`/`ChampionNeverApprovedError`; 6 tests (`tests/unit/test_champion_challenger.py`) grounded in a real delta-hedge-vs-no-trade-band comparison, including the never-approved-champion rejection and the higher/lower-is-better convention flip |

Not covered: no persistence or multi-champion registry lookup --
`champion_entry` is supplied directly by the caller rather than
resolved automatically from some larger store of registered models;
no integration with `evidence.model_serving`'s rollback (a
"challenger wins" conclusion does not itself trigger a `deploy`).
See
[`src/prometheus/evidence/champion_challenger.py`](./src/prometheus/evidence/champion_challenger.py).

## Evidenced today (PR-103: restored artifacts are readable and hash-consistent -- REL-11, audit)

REL-11's own acceptance criterion is "restore artifacts are readable and
hash-consistent." An audit (not new production code) found this already
substantially satisfied by `recovery.snapshot.create_snapshot`/
`restore_snapshot` (PR-048) and `jobs.artifacts.ArtifactStore.get`, which
already re-verifies an artifact's content hash on every read via
`audit_evidence_bundle` -- extensively exercised by 31 pre-existing tests
(tampering, encryption, atomic restore, corruption), but none had ever
stated the REL-11 claim explicitly in one place.

One new, deliberate test,
`test_rel_11_restored_artifacts_are_readable_and_hash_consistent`, states
it directly: after a genuine `create_snapshot`/`restore_snapshot` round
trip, the restored artifact is read by its own digest (readable) and this
test INDEPENDENTLY recomputes `artifact_content_hash` on the returned body
and confirms it matches that digest (hash-consistent) -- not merely "no
exception was raised." Writing this test surfaced a genuine subtlety:
an artifact here is content-addressed by a canonical-JSON hash of its
*parsed* body, not a raw-byte file hash (an initial draft of this test
computed `sha256` of the raw file bytes directly and failed, since
re-serialization legitimately changes whitespace/formatting without
changing meaning) -- confirmed, not assumed, before trusting the test.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| REL-11 (first evidence, audit) | run backup restore and integrity validation; restore artifacts are readable and hash-consistent | pre-existing `recovery.snapshot`/`jobs.artifacts.ArtifactStore`, read against REL-11's own acceptance criterion; one new deliberate test (`tests/unit/test_recovery_snapshot.py`) |

## Evidenced today (PR-104: identity, approval, previous state and hash on every registry transition -- AUD-06)

AUD-06's own acceptance criterion is "identity, approval, previous state
and hash recorded." `evidence.model_registry.StateTransition` already had
`actor` (identity) and `from_state` (previous state) from MLO-08; this PR
adds the two still-missing fields: `approved_by`, a separate REQUIRED
field with no default (a silently-defaulted approver would not be a
deliberate declaration -- the same reasoning this project applies to
`measure`/`higher_is_better`/other no-default fields), and `content_hash`,
optional in general (not every transition has a packaged artifact to hash
yet) but made REQUIRED specifically on `promote_to_approved` -- the one
transition AUD-06 names by name ("promotion transitions") -- via a new
required `package: model_package.ModelPackage` (MLO-07) parameter, reused
rather than reinvented. This registry deliberately does NOT itself enforce
`approved_by != actor`, since doing so would need real authentication this
repository does not have; that remains CIQ-08's own, separately unclaimed
"two-person approval" item.

A full-lifecycle test confirms all four AUD-06 fields are genuinely
present where each applies: identity and previous state on every
transition, a genuinely DIFFERENT approver on the promotion step, and a
content hash that appears only once a package exists (correctly absent on
the earlier `candidate -> evaluated` transition, present and matching on
`evaluated -> approved`).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| AUD-06 (first evidence) | capture all model registry and promotion transitions; identity, approval, previous state and hash recorded | `evidence.model_registry.StateTransition`'s `approved_by`/`content_hash` fields, `promote_to_approved`'s new required `package` parameter; a full-lifecycle test confirming all four named fields (`tests/unit/test_model_registry.py`) |

Not covered: `approved_by != actor` is not enforced (would need real
authentication); no transition other than the promotion to `approved`
carries a `content_hash` (none of the others have a natural artifact to
hash yet).
See
[`src/prometheus/evidence/model_registry.py`](./src/prometheus/evidence/model_registry.py),
[`tests/unit/test_recovery_snapshot.py`](./tests/unit/test_recovery_snapshot.py).

## Evidenced today (PR-105: a real, code-derived service inventory and dependency map -- OPS-01)

OPS-01's own acceptance criterion is "every production component has
owner and environment." `evidence.ops_inventory.discover_dependencies`
is not hand-maintained prose that can silently drift from the real
code: it parses every component's actual `.py` source files with the
standard library's `ast` module and reports exactly which OTHER
top-level `prometheus.*` components it imports from. Run against this
repository's own real `src/prometheus` tree, it correctly finds all 14
subpackages plus the standalone `numerics` module, and surfaces a
genuine, non-obvious finding: `stochastica` and `volterra` have a real
PACKAGE-level import cycle (`stochastica.convergence` prices via
`volterra.heston_pricer` for a convergence study, while `volterra`
separately imports several `stochastica` modules for its own pricers)
-- confirmed directly against the source tree, not assumed to be
acyclic. `owner`/`environment` are required, caller-supplied fields
with no default (nothing in this single-maintainer, un-deployed repo
can honestly derive either from the code itself).

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| OPS-01 (first evidence) | create service inventory and dependency map; every production component has owner and environment | `evidence.ops_inventory.ServiceComponent`/`discover_component_names`/`discover_dependencies`/`build_service_inventory`; 9 tests (`tests/unit/test_ops_inventory.py`) run against this repository's own real source tree, including the genuine stochastica/volterra cycle finding |

Not covered: owner/environment are a single caller-supplied label
applied uniformly (this repository has exactly one maintainer and no
deployed environment, so there is honestly nothing more granular to
assign); no visualization of the dependency graph.
See
[`src/prometheus/evidence/ops_inventory.py`](./src/prometheus/evidence/ops_inventory.py).

## Evidenced today (PR-106: simulation jobs benchmarked at small/medium/large scales -- REL-03)

REL-03's own acceptance criterion is "time/memory curves and resource
budget published." `experiments.scale_benchmark` reuses `experiments.
cost_benchmark.benchmark_method_cost` (EXP-11) rather than reimplementing
timing/memory measurement, adding only `ScaleBudget` (a named ceiling per
scale, PUBLISHED before running anything, not fitted after the fact) and
`check_scale_budgets`.

Grounded in a REAL benchmark, not synthetic numbers: a genuine
small/medium/large `stochastica.gbm.simulate_gbm_paths` run. A throwaway
warm-up call was found NECESSARY before trusting the measurements --
confirmed directly: without it, the very first timed call absorbed a
one-time numpy/BLAS warm-up cost large enough to make "small" measure
slower than "medium," which would have been a flaky, misleading test had
it gone unnoticed. With the warm-up call, both the walltime and the peak-
memory curve are confirmed strictly increasing across all three scales,
checked as a real property of the measurements, not merely plotted.

Writing this module's own test also caught a real bug before it shipped:
`zip(ordered, ordered[1:], strict=True)` crashes with `ValueError` on any
input, since the two operands are deliberately one element apart in
length by construction -- `strict=True` was simply wrong here; fixed to
`strict=False`.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| REL-03 (first evidence) | benchmark simulation jobs at small/medium/large scales; time/memory curves and resource budget published | `experiments.scale_benchmark.ScaleBudget`/`check_scale_budgets`/`walltimes_are_monotonically_increasing`; 9 tests (`tests/unit/test_scale_benchmark.py`) grounded in a real GBM benchmark across 3 scales, including a genuine budget-violation case and the warm-up-call methodology note; stable across repeated reruns |

Not covered: only one simulator (`stochastica.gbm`) is benchmarked; no
other job type (e.g. the full `econosim` `StepHooks` loop, or a job-queue
submission) is exercised at scale yet.
See
[`src/prometheus/experiments/scale_benchmark.py`](./src/prometheus/experiments/scale_benchmark.py).

## Evidenced today (PR-107: dataset cards distinguishing synthetic from empirical data -- DAT-14)

DAT-14's own acceptance criterion is "every published result identifies
data lineage and type." `evidence.dataset_card.DataType` is a closed,
two-value vocabulary (`"synthetic"`/`"empirical"`) -- there is no third,
ambiguous category a caller could use to avoid declaring which one
applies -- and `build_dataset_card` has no default for `data_type` or
`lineage`, so a published result's card can never be silently missing
either.

Grounded in two REAL cases, not labels applied to nothing: a genuine
simulated GBM path (`stochastica.gbm.simulate_gbm_paths`) carded as
`"synthetic"`, and a genuine, real captured World Bank API response (the
SAME hermetic fixture `test_worldbank_connector.py` exercises) carded as
`"empirical"`, with its lineage stating the ACTUAL license the real
observation carries (`"CC-BY-4.0 (World Bank Open Data)"`), not a
fabricated string.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| DAT-14 (first evidence) | document synthetic-vs-empirical labels and dataset cards; every published result identifies data lineage and type | `evidence.dataset_card.DatasetCard`/`build_dataset_card`; 8 tests (`tests/unit/test_dataset_card.py`) grounded in a real GBM simulation and a real captured World Bank response with its actual license |

Not covered: no existing module (`service.reports`, `data_ingestion.
worldbank`, etc.) is itself changed to attach a `DatasetCard` to its own
output -- this PR adds the general-purpose card primitive and
demonstrates it against two real data sources in tests, rather than
wiring it into a production publishing path.
See
[`src/prometheus/evidence/dataset_card.py`](./src/prometheus/evidence/dataset_card.py).

## Evidenced today (PR-108: raw/normalized/features/artifacts storage layers with permission and immutability boundaries -- DAT-06)

DAT-06's own acceptance criterion is "layer permissions and immutable
boundaries tested" -- two SEPARATE boundaries, both enforced by code:
`econosim.storage_layers.StorageLayer.write` raises `ImmutableWriteError`
if a key is already written (confirmed per-key, not a blanket freeze: a
second, different key can still be written to the same layer
afterward), and `read_from` enforces that the four named layers form a
strict pipeline -- `raw -> normalized -> features -> artifacts` -- where
a layer may read directly only from the ONE layer immediately upstream
of it, confirmed by a discriminating test that `features` cannot read
directly from `raw`, skipping `normalized`, even though nothing stops
it from knowing a `raw` key's name.

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| DAT-06 (first evidence) | implement raw/normalized/features/artifacts storage layers; layer permissions and immutable boundaries tested | `econosim.storage_layers.StorageLayer`/`ImmutableWriteError`/`LayerPermissionError`; 10 tests (`tests/unit/test_storage_layers.py`) including the per-key (not blanket) immutability check and the skip-a-layer permission rejection |

Not covered: this is an in-memory primitive, not a persisted storage
backend (no actual files/database tables for the four layers); no
existing data pipeline (`data_ingestion.worldbank`, etc.) is itself
changed to route its data through these layers.
See
[`src/prometheus/econosim/storage_layers.py`](./src/prometheus/econosim/storage_layers.py).

## Explicitly NOT done (do not infer otherwise)

- No fixed-payment/level-principal amortization schedule (LED-05 covers capitalizing-compound accrual only). Multi-creditor insolvency now exists (`econosim.insolvency`, PR-049) but only resolves claims the caller has already broken out per creditor; it does not discover per-creditor exposure from the ledger's pooled borrower liability account on its own.
- No general deposit-taking/custody mechanism for non-loan flows (ECO-06; LED-08's own narrower "cross-bank transfer preserves total settlement balances" acceptance criterion IS evidenced, see PR-082 above): household/firm deposit balances are not bank-custodied outside of loan origination in this model, so a general deposit-instrument reconciliation across the household population would not be a true invariant yet.
- `econosim.policy_rate.CentralBank` (PR-012) remains an unchanged, standalone rate-process wrapper, still used by other orchestration scenarios (`multi_step_run.py`, `monetary_run.py`, etc.). `econosim.central_bank_ledger.CentralBankLedger` (PR-026) now OPTIONALLY unifies the two (PR-041): construct it with `rate_rule`/`initial_rate` to get one object that is both the rate-setter and the ledger-backed balance sheet. `econosim.monetary_operations` (PR-028/029) was migrated to that unified constructor (PR-042); the other orchestration scenarios above were not.
- Market clearing (PR-013) is a single-firm-vs-N-households case only: a general many-buyer/many-seller clearing *settled onto the ledger* would need a market-maker/clearing-account abstraction that does not exist. The pure quantity-matching math (`clear_quantity_market`) itself is fully general; only the ledger-execution helpers are restricted.
- Price discovery is restricted to monotone budget-demand/linear-supply schedules. The economic runner has one firm and unvalued physical inventory; general multi-firm settlement, preferences/profit optimization, market-price calibration and competitive general equilibrium remain unimplemented. The financial monthly reference still uses supplied economic quotes.
- PR-019 couples discovered prices/output to policy rates, financial drift/financing and payroll demand through specified synthetic rules. Empirical calibration, a general joint economic/financial balance sheet and a stochastic-rate risk-neutral valuation model remain unimplemented. Earlier standalone runners retain their original supplied-rate/quote conventions.
- Portfolio optimization (PR-023) covers only mean-variance and scenario-CVaR formulations with simple box/budget/turnover constraints. Covariance shrinkage (PR-024) originally covered only a scaled-identity target (Ledoit-Wolf 2004); PR-050 generalizes it to shrink toward any fixed target, including a factor-model-implied one, but there is still no constant-correlation target, no cross-validated/empirical-Bayes choice between candidate targets, and no scenario-based robust covariance method. The multi-period rebalancing simulator (PR-025) connects covariance shrinkage and the optimizer across time but is still a standalone array-in/array-out simulation with no position book and no link to the hedging/monetary/rate studies' outputs or `StepHooks`; it has no out-of-sample train/test comparison, no stress-regime testing, and no market-impact cost model (a single proportional rate only). Licensed ingestion beyond the minimal point-in-time store, deployed API/identity acceptance, complete model lifecycle/security controls and independently accepted governance/compliance remain outstanding. PR-045/046/047 add partial evidence/traceability, local jobs and authenticated research API foundations, as documented above.
- `orchestration.demo_run.run_demo` (PR-011) remains a separate hard-coded pipeline. PR-015's packaged monthly scenario uses `StepHooks`, but only for one firm, two households, one European option and a classical single-asset GBM. No general scheduler, shared economic/hedging balance sheet or full dynamic-policy conditional-risk forecast exists.
- No GRU/LSTM, actor-critic or robust-policy hedging families (section 07's table) -- only the MLP family.
- Risk-neutral calibration (PR-022) covers only implied volatility, per quote, independently across strikes: `risk_free_rate` is still supplied directly, there is no smoothed/parametric surface, no cross-strike arbitrage-free-fit check, and no other code in this repository (hedging, benchmarks, the monetary/rate studies) consumes a calibrated value instead of a directly-supplied one.
- No independent review of any item above — "evidenced" here means "covered by a passing automated test in this repository," not peer- or reviewer-approved per the blueprint's own evidence standard.

## How to verify the evidence above yourself

```bash
python3 -m pip install --require-hashes --only-binary=:all: -r requirements/bootstrap.txt
uv sync --locked --all-extras --group build
uv run --locked --all-extras pytest -q --cov=prometheus --cov-report=term-missing
uv run --locked --all-extras ruff check src tests tools
uv run --locked --all-extras mypy --strict src tools/reproducible_build.py
```
