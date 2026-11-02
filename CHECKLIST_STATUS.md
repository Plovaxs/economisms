# Checklist status

This tracks real status against the blueprint's own checklist IDs
(`docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf`, section
14 — 374 items across 29 categories, all of which the document itself marks
`[ ] NOT VERIFIED`). Per the blueprint's own protocol: "To set [x], link an
immutable artifact (PR, commit, report, ...) and obtain appropriate review."
No independent review has happened here yet, so nothing below is marked
`[x]` — evidence is linked to a test, which is the strongest claim a single
contributor can honestly make before review.

Everything not listed below is unimplemented. This file will grow, item by
item, alongside the code — it is not a target to backfill in one pass.

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

Not covered by PR-005: Heston/Fourier pricing (PRI-04), risk-neutral calibration (PRI-05), barrier/Asian options (PRI-08/09), portfolio-level Greeks aggregation (PRI-10), volatility-surface arbitrage checks (PRI-11), and all of PDE-01..PDE-12 (PINN/deep-BSDE solvers).

## Evidenced today (PR-006)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| RISK-02 | historical VaR with definitional metadata | `titan.risk_metrics.historical_var`; declares its `alpha`/`interpolation` convention explicitly, no hidden default assumption |
| RISK-03 | parametric VaR under explicit distribution | `titan.risk_metrics.parametric_var` (Gaussian); `tests/unit/test_risk_metrics.py::test_parametric_var_known_value` against a literature reference value |
| RISK-04 | Expected Shortfall, tie/atom-safe estimator, discrete and continuous reference examples | `titan.risk_metrics.historical_expected_shortfall`; hand-worked discrete examples with and without ties (`test_expected_shortfall_discrete_worked_example_with_ties` is the one that would break under naive distinct-value tie handling), plus a continuous Gaussian reference check within 1% |
| RISK-06 | historical drawdown | `titan.risk_metrics.max_drawdown`; hand-worked example |
| RISK-08 | VaR exception and coverage tests, expected frequency and CI | `titan.risk_metrics.var_exception_coverage_test` (exact two-sided binomial test); tests confirm a correctly-calibrated model is not flagged and a badly miscalibrated one is |

Not covered by PR-006: RISK-01 (position/snapshot linkage -- there is no position book yet), RISK-05 (covariance/shrinkage estimators), RISK-07 (factor exposure), RISK-09 (ES backtesting/proper scoring rules beyond the coverage test above), RISK-10..13 (stress scenarios, network contagion, concentration decomposition, stale-snapshot rejection), and all of OPT-01..12 (portfolio optimization).

## Explicitly NOT done (do not infer otherwise)

- No interest accrual/amortization (LED-05), no default/write-off path beyond a bare repayment reducer (LED-07, LED-10).
- No deposit-instrument reconciliation across the household population (ECO-06, LED-08): household/firm deposit balances are not bank-custodied for non-loan flows in this model, so that check would not be a true invariant yet.
- No government or central-bank agents, no labor or goods-market clearing beyond direct bilateral consume/wages transfers.
- Shocks are drawn deterministically but are not yet *applied* to any agent state (no production function, no policy-rate transmission) -- they are logged and timestamped only; wiring a shock's magnitude into an actual economic effect is future work.
- No hedging, portfolio optimization, data ingestion (beyond the minimal point-in-time store above), API, MLOps, security, or any governance/compliance item.
- STOCHASTICA, VOLTERRA and TITAN are not wired into the economy/ledger or to each other at all yet: market paths, option prices and risk metrics are each computed standalone from plain arrays/floats the caller supplies, not driven by or feeding back into any agent's state, position book or hedge. That link (section 02's "simulate financial step" / "value and hedge" / "compute portfolio risk", steps 5-7 of the event order) is future work.
- No risk-neutral calibration: `MarketSnapshot`'s `risk_free_rate`/`volatility` are supplied directly, not fit to an observed option-price surface.
- No independent review of any item above — "evidenced" here means "covered by a passing automated test in this repository," not peer- or reviewer-approved per the blueprint's own evidence standard.

## How to verify the evidence above yourself

```bash
pip install -e ".[dev]"
pytest -q                # 35 passed
pytest -q --cov=prometheus --cov-report=term-missing
ruff check src tests
mypy src
```
