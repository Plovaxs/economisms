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

This closes the single most-repeated limitation across PR-003 through PR-010's status entries ("each subsystem is still called standalone"). It does not mean the subsystems are wired together *generally* -- `run_demo` is one specific, hard-coded pipeline for one scenario and one option, not a general orchestration engine, scheduler, or the actual `MacroTimeEngine.advance_step()` loop calling out to pricing/hedging/risk at every step (section 02's steps 5-7 are still not implemented inside `MacroTimeEngine` itself).

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

## Explicitly NOT done (do not infer otherwise)

- No interest accrual/amortization (LED-05), no default/write-off path beyond a bare repayment reducer (LED-07, LED-10).
- No deposit-instrument reconciliation across the household population (ECO-06, LED-08): household/firm deposit balances are not bank-custodied for non-loan flows in this model, so that check would not be a true invariant yet.
- `CentralBank` (PR-012) has no ledger-backed balance sheet: no reserve issuance, no open-market operations, no interbank settlement role. It only tracks a scalar policy rate.
- Market clearing (PR-013) is a single-firm-vs-N-households case only: a general many-buyer/many-seller clearing *settled onto the ledger* would need a market-maker/clearing-account abstraction that does not exist. The pure quantity-matching math (`clear_quantity_market`) itself is fully general; only the ledger-execution helpers are restricted.
- No price discovery: wage and goods prices are supplied by the caller, not adjusted toward a market-clearing price (no tatonnement).
- Shocks are drawn deterministically but are not yet *applied* to any agent state (no production function, no policy-rate transmission) -- they are logged and timestamped only; wiring a shock's magnitude into an actual economic effect is future work.
- No portfolio optimization, data ingestion (beyond the minimal point-in-time store above), API, MLOps, security, or any governance/compliance item.
- `orchestration.demo_run.run_demo` (PR-011) demonstrates every subsystem working together end to end, but it is one hard-coded pipeline for one scenario and one option, not a general orchestration engine. `MacroTimeEngine.advance_step()` itself still only does steps 1/2/8 of section 02's event order; steps 5-7 ("simulate financial step" / "value and hedge" / "compute portfolio risk") are not called from inside the macro step loop -- a caller has to do what `run_demo` does by hand.
- No GRU/LSTM, actor-critic or robust-policy hedging families (section 07's table) -- only the MLP family.
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
