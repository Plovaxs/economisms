# ECONOSIM — Pull Request Evidence Ledger

> This is the detailed, PR-by-PR evidence log: what every pull request
> added, how it was verified, and what it deliberately does not claim.
> For the project overview, quickstart and current status summary, see
> the top-level [README](../README.md). For the condensed, per-category
> checklist view (what's evidenced vs. missing per blueprint category),
> see [CHECKLIST_STATUS.md](../CHECKLIST_STATUS.md).

*(Formerly PROMETHEUS. ECONOSIM: A Unified Multi-Task Deep Learning
Framework for Macroeconomic Forecasting, Financial Risk Modeling, and
Economic Policy Simulation — the project's name going forward, per the
PROMETHEUS-X final-project addendum below.)*

Research platform for computational economics, stochastic finance and neural
risk control. **Research / simulation only — not financial advice, and not
permission or infrastructure for live trading.**

This repository implements a small, real, tested subset of the project's
two governing specifications:

- the original [master specification](./docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf):
  a 57-page design document covering a multi-agent computational economy
  (ECONOSIM-X), neural stochastic market dynamics (STOCHASTICA), derivatives
  pricing (VOLTERRA) and institutional risk analytics (TITAN), plus a
  374-item engineering readiness checklist across 29 categories; and
- the [PROMETHEUS-X final-project addendum](./docs/PROMETHEUS_X_Final_Project_Integrated_Blueprint.md):
  an 8-page extension layered on top (not replacing) the original, adding
  five new Deep Learning subsystems — MACROCORE (shared temporal encoder),
  RECESSIONNET, INFLATIONCAST, CONTAGION-GNN and POLICYLAB-RL, plus a
  generative VOLTERRA-GEN scenario sampler — and its own 24-item
  acceptance checklist (FP-01..FP-24).

**Both specifications are design documents, not status reports.** Treat any
claim that their contents are "included" as a description of their tables
of contents, not of working software. This README and
[CHECKLIST_STATUS.md](./CHECKLIST_STATUS.md) are the actual, current,
test-backed status — the latter now tracks both the original 374-item
register and the addendum's FP-01..FP-24 items in clearly separated
sections. Nothing below is claimed without a passing test behind it.

## What exists today (v0.1)

A multi-sector, double-entry **stock-flow ledger** (`prometheus.core.ledger`)
plus five agent types built on it (`prometheus.econosim.agents`):

- `Money` — exact integer minor-unit currency values (no floating-point
  cent drift).
- `Ledger` — accounts tagged by sector (household / firm / bank / government
  / central bank) and type (asset / liability / equity); every state change
  goes through `Ledger.post()`, which validates a transaction's accounting
  identity **before** mutating any balance (fail closed), not after.
- `Household`, `Firm`, `Bank` — income, consumption, wages, loan
  origination, loan repayment and a bank leverage cap, each implemented as
  one balanced `Transaction`. `Bank` also supports interest accrual
  (capitalizing-compound, PR-043) and single-creditor loan write-off,
  additive to origination/repayment — hand-verified exact compounding
  over multiple periods and an exact loss/debt-forgiveness equity split
  on write-off, validated against each specific borrower's own balance,
  not the bank's pooled aggregate across every borrower. A multi-creditor
  insolvency waterfall (`prometheus.econosim.insolvency`, PR-049) builds
  on top of write-off/repayment: it allocates a short recovery across
  several creditor banks by absolute priority (senior tiers paid in full
  before any junior tier) with exact largest-remainder pro-rata sharing
  within a tier, then applies that allocation through the same two
  existing `Bank` calls, one per creditor.
- `Government` — taxes, transfers, and bond issuance/repayment through a
  `Borrower` protocol shared with `Household`, so a bank's capital/leverage
  limit constrains household and government borrowing *together*, not as
  two separately-maintained mechanisms that could drift apart.
- `CentralBank` (`prometheus.econosim.policy_rate`) — a thin stateful
  wrapper around a mean-reverting policy-rate rule, not itself a
  ledger-backed agent, and still unchanged. A separate, additional
  ledger-backed agent, `CentralBankLedger` (`prometheus.econosim.central_bank_ledger`,
  described further below), can now OPTIONALLY track the policy rate
  too (PR-041) — passing `rate_rule`/`initial_rate` gives one object that
  is both the rate-setter and the balance sheet, confirmed bit-for-bit
  identical to the standalone wrapper's own math. `econosim.monetary_operations`
  (described further below) was migrated onto that unified constructor
  (PR-042); other orchestration scenarios still use the standalone
  rate-only wrapper.
- `clear_quantity_market` (`prometheus.econosim.market_clearing`) —
  quantity-based pro-rata rationing on the short side of a labor or goods
  market, for one firm against N households; realized (not desired)
  quantities are what actually get paid/charged on the ledger. This
  original API uses supplied quotes; bounded integer-tick discovery and
  exact batch settlement are available in `price_discovery` and `market_settlement`.
- `Economy` — thin wiring over the above plus an integrity check.

Every one of those behaviors is covered by a unit test, and the ledger's
core conservation property (no sector's books can go out of balance, and
total economy-wide equity equals exactly the sum of exogenous injections) is
checked by a Hypothesis property test over randomized action sequences —
see `tests/property/test_ledger_invariants.py`.

Plus a **macro time engine** (`prometheus.econosim.time_engine`):

- `BusinessDayCalendar` — weekend/holiday-aware date stepping.
- `SeedHierarchy` — deterministic, order-independent named RNG streams from
  one root seed, so replaying a simulation with the same seed reproduces
  every stream's draws regardless of what order they're first requested in.
- `PointInTimeStore` — macro observations keyed by both the period they
  describe and when they were published; `as_of(t)` enforces the strict
  `published_at <= t` inclusion rule, so a simulated step can never see a
  data revision before it actually existed (the concrete mitigation for
  R-03 in the risk register: lookahead leakage). `MacroObservation` (PR-055)
  additionally carries a full point-in-time provenance schema (`vintage_at`,
  `asof_eligible_at`, `ingested_at`, `source_url`, `source_license`,
  format-validated `raw_hash`, `quality_flags`) — all additive with
  defaults, so no pre-existing caller changed. `asof_eligible_at` closes a
  real gap the original predicate had: it only ever gated on the SOURCE's
  `published_at`, silently assuming this system's own ingestion finishes
  instantaneously at that moment. The gate is now
  `max(published_at, asof_eligible_at)`, confirmed identical to the old
  behavior whenever `asof_eligible_at` is left unset. `require_eligible`/
  `build_feature_vector` add the active-rejection counterpart to `as_of`'s
  silent `None` — a `FutureDataError` fail-closed fixture for a future
  forecasting pipeline's feature-vector builder, confirmed to reject the
  WHOLE request (not a silently-partial one) when even one requested
  series isn't yet eligible.
- `ShockGenerator` — deterministic exogenous shocks tagged with the step
  they arrive at, drawn from a seeded stream.
- `MacroTimeEngine` — steps the clock one calendar month at a time (snapped
  to the next business day), releasing only currently-eligible macro data
  and drawing that step's shocks, then re-checks the ledger's accounting
  identities and emits a content hash of the resulting state.
- `StepHooks` (`prometheus.econosim.step_hooks`) — optional, strictly
  ordered callbacks for section 02's steps 3-7 (agent decisions, market
  clearing, financial-step simulation, valuation/hedging, portfolio risk),
  invoked by `advance_step()` itself. Proven end to end against the real
  market-clearing, GBM, Black-Scholes and VaR subsystems in one test, not
  mocked; each hook only ever sees data already known as of that step, and
  a hook that posts a ledger transaction is confirmed to change the
  step's resulting state hash.

Plus physical-measure **stochastic market dynamics** (`prometheus.stochastica`),
used by both demonstration and monthly orchestration:

- `simulate_gbm_paths` — exact lognormal-transition GBM (no discretization
  bias to characterize), checked against closed-form terminal moments.
- `simulate_correlated_gbm_paths` — multi-asset GBM with correlated shocks.
- `simulate_heston_paths` — log-Euler price / full-truncation-Euler variance
  Heston, guaranteed non-negative variance by construction, checked against
  the CIR process's exact first moment.
- `correlated.validate_and_repair_covariance` — rejects a non-PSD covariance
  matrix outright, but repairs (with a warning) one that is PSD except for
  floating-point-sized negative eigenvalues.
- `simulate_jump_diffusion_paths` (`prometheus.stochastica.jump_diffusion`,
  PR-052) — Merton (1976) compound-Poisson jump-diffusion: a second
  non-GBM model, with an EXACT (not Euler-approximated) per-step jump
  allocation, since a Poisson jump count convolved with its matching
  sum-of-normals jump-size distribution has a closed form.

Plus risk-neutral (Q) **derivatives pricing** (`prometheus.volterra`):

- `MarketSnapshot` — structurally requires `measure="Q"`; constructing one
  tagged `"P"` raises immediately, so a physical-measure calibration can't
  be fed into a pricing call by accident (SDE-09).
- `black_scholes_price` / `black_scholes_greeks` — the closed form plus
  delta/gamma/vega/theta/rho, matched against a central finite-difference
  of the same price function (an independent formula check, not an
  independent *pricer* check) and against put-call parity to floating-point
  precision.
- `monte_carlo_price_vanilla` — always simulates under Q (drift =
  risk-free rate minus dividend yield, never a physical `mu`), always
  returns a standard error alongside the price, and optionally applies a
  control variate (the discounted terminal spot, whose risk-neutral mean is
  known in closed form) — cuts the standard error by roughly 2-3x at the
  tested settings.

Plus institutional-style **risk metrics** (`prometheus.titan`), also not
yet wired to any position book:

- `historical_var` / `parametric_var` — empirical and Gaussian VaR, each
  declaring its convention (interpolation method / distributional
  assumption) explicitly rather than silently defaulting.
- `historical_expected_shortfall` — a tie/atom-safe quantile-integral
  estimator that operates on order statistics (so a run of tied loss values
  is handled correctly with no special-casing), checked against hand-worked
  discrete examples and against the exact Gaussian ES formula for a
  continuous reference.
- `max_drawdown` — peak-to-trough decline in a cumulative P&L/value series.
- `var_exception_coverage_test` — an exact two-sided binomial test of
  whether observed VaR breaches match the expected rate; confirmed to pass
  a correctly-calibrated model and flag (p < 1e-10) a badly miscalibrated
  one in testing.

Plus **deep hedging and stochastic control** (`prometheus.hedging`), the
first subsystem that uses PyTorch:

- `black_scholes_delta_hedge_ratios` / `apply_no_trade_band` — a causal
  (no-future-information) delta baseline and a cost-aware no-trade-band
  variant that cuts turnover by roughly 30% at a 0.1 band width in testing.
- `simulate_self_financing_hedge` — one shared, explicitly self-financing
  P&L simulator used for *every* policy, baseline and learned alike, so
  nothing can look better just by using a different accounting convention.
  Checked against an exact closed form (a zero-hedge naked short position)
  and against a brute-force manual recomputation.
- `HedgePolicyMLP` / `train_deep_hedge` — a small MLP trained to minimize
  CVaR of terminal loss plus a turnover penalty (Buehler et al., 2019),
  differentiating straight through a PyTorch rollout that mirrors the
  numpy simulator's accounting exactly. Training is deterministic given a
  seed; a negative-control test requires at least a factor-two CVaR
  improvement over an untrained policy. No test assumes it beats delta.
  NumPy evaluation, PyTorch training and online accounts all trade first
  and then accrue financing on the resulting cash until the next price.

Plus a first **research benchmark** (`prometheus.experiments`):

- `paired_bootstrap_difference` — a percentile bootstrap CI for the
  difference between two policies evaluated on the *same* simulated paths.
  The pairing is load-bearing, not cosmetic: a planted constant per-path
  difference collapses to an exact-point CI in testing, which an unpaired
  bootstrap would not do.
- `RunManifest` / `compute_result_hash` — a reproducibility manifest whose
  result hash is a canonical, key-order-independent hash of the full
  per-seed results payload, confirmed identical across independent runs of
  the same config; `run_id`/`created_at` are wall-clock-derived and
  explicitly documented as *not* part of that reproducibility claim.
- `run_hedge_benchmark` — compares the delta baseline against a trained MLP
  policy across several independent held-out seeds, with a primary endpoint
  fixed in advance (`PRIMARY_ENDPOINT`). Per-seed results include CVaR,
  mean loss, mean transaction cost and turnover. Path generation and
  bootstrap resampling use separate named RNG streams, so test-seed order
  cannot change a seed's result. Every report also states,
  in plain text, exactly which axes of the blueprint's full factorial
  matrix it does *not* cover (only the hedge dimension is varied; no
  learned economy or neural-SDE market model exists yet).

Plus a first **macro-financial link** (`prometheus.econosim.policy_rate`,
`prometheus.econosim.macro_market_link`, and an extension to
`prometheus.stochastica.gbm`) — explicitly a deterministic, non-neural v0
of STOCHASTICA's eventual Tier 3 ("macro conditioned"), not a claim that
Tier 3 itself is done:

- `PolicyRateRule` — a mean-reverting central-bank rate process perturbed
  by the deterministic `"policy_rate"` shocks already built in PR-003,
  matching the exact closed-form discrete Ornstein-Uhlenbeck recursion to
  floating-point precision when unperturbed.
- `simulate_piecewise_drift_gbm_paths` / `piecewise_gbm_terminal_moments` —
  a GBM variant whose drift changes period by period (here, driven by the
  policy rate), checked against an exact closed-form reference that reduces
  identically to the ordinary constant-drift GBM formula when the path is
  flat.
- The whole chain — seeded shocks → policy rate → macro-conditioned market
  — is deterministic end to end and provably has no lookahead: a late
  shock, or a wildly different late-period drift, leaves every earlier
  simulated value bit-identical in testing.

Plus a first **orchestrated end-to-end run** (`prometheus.orchestration`),
implementing section 16's "Minimum v0.1 demonstration script" literally —
closing the single most-repeated limitation in every PR above ("called
standalone, not wired to anything else"), for one specific scenario:

```python
from prometheus.orchestration.demo_run import DemoRunConfig, run_demo
result = run_demo(DemoRunConfig())  # ~1s
```

This simulates a small closed economy and verifies its ledger; applies
Appendix B's own SC-01 scenario (an unanticipated +200bp policy-rate
shock) through `PolicyRateRule`; generates both a macro-conditioned GBM
path and an independent Heston diagnostic; prices a European option under
a separately-tagged Q-measure snapshot, cross-checked by an independent
Monte Carlo run; trains and evaluates an MLP hedge against the delta
baseline on the realized macro-conditioned paths; computes CVaR for both;
and exports an evidence bundle. The blueprint's own instruction — *"If any
invariant, valuation tolerance or data-timing check fails, the run must be
marked invalid rather than silently published"* — is implemented as three
named, independently-triggerable checks (`DemoRunResult.invalid_reasons`),
not just a comment: tests force a genuine ledger corruption and a genuine
valuation-tolerance breach and confirm the run reports itself invalid
*while still returning a full report*, rather than crashing or looking
clean. This remains a standalone pipeline. The monthly scenario below
uses `MacroTimeEngine` hooks for repeated pricing, hedging and risk.

Plus a **monthly reference scenario** (`orchestration.multi_step_run`):

```bash
python -m prometheus.orchestration.multi_step_run \
  --seed 42 --start-date 2026-01-02 --steps 12 \
  --output evidence/my_monthly_run.json
```

This runs labor/goods settlement, a policy-rate shock, one physical GBM
increment, risk-neutral option valuation, delta/MLP rehedging and
conditional portfolio CVaR through all five `StepHooks` every month.
Hedges start at t=0, cash finances each interval at its current rate,
and expiry uses the exact payoff without opening another position.
Monthly financial time is 1/12 year; dates follow the engine's business-day
stepping convention. Maturity defaults to `n_steps / 12`; an explicit
`option_maturity_years` must match that horizon.

The JSON includes the full configuration, named training seeds, policy
hash, training history, every step's balances/costs/risk/ledger hash,
terminal wealth, model card and gate report. Its result hash covers the
configuration and full simulation payload. Exported JSON can be checked
with `compute_result_hash(bundle["simulation"])`. Run IDs and export dates
remain wall-clock metadata, outside the deterministic result hash.
Step failures retain completed steps, record the error, omit terminal
wealth and return CLI exit code 1; invalid CLI arguments return code 2.

Conditional CVaR measures losses on the short-option hedge portfolio under
physical GBM continuation with frozen current holdings and rates. It does
not predict future rehedging or unknown policy shocks. At maturity it
equals the realized terminal loss. Model cards label the single scenario's
metric `realized_terminal_loss`; a single path is not a CVaR estimate.
The economic ledger and floating-point hedge accounts remain separate.
See [the generated reference run](./evidence/multi_step_reference.json).

Plus a **reproducible benchmark runner and evidence replay** (PR-016):

```bash
python -m prometheus.orchestration.benchmark_run \
  --output evidence/my_benchmark.json
python -m prometheus.orchestration.replay evidence/my_benchmark.json \
  --output evidence/my_benchmark_replayed.json
python -m prometheus.orchestration.replay evidence/multi_step_reference.json
```

The benchmark recipe includes training path/policy seeds, all training
hyperparameters, held-out seeds, pricing inputs, payoff and evaluation
settings. It records a digest of the actual training paths, the policy
weights and all per-seed financial/bootstrap results. Training and test
seed labels must be distinct, and duplicate test seeds are rejected.
The [corrected reference benchmark](./evidence/hedge_benchmark_reference.json)
uses the trade-then-accrue convention. Its decision rule requires every
seed's confidence interval to exclude zero in the same direction; it can
return `policy_better`, `delta_better` or `inconclusive`. These intervals
condition on one fitted policy and do not measure retraining uncertainty.
Model cards label seed-averaged metrics explicitly; averaging seed CVaRs
does not produce pooled CVaR.

Replay validates the payload hash, manifest/config agreement, schema and
accounting convention before training, then reconstructs the full recipe
and compares the recomputed result hash. Missing or unknown configuration
fields are rejected. A fabricated result with a newly computed file hash
still fails if the actual rerun disagrees. A match returns exit code 0;
a result mismatch returns 1; malformed input or incompatible recipes
return 2. Reproducing an invalid simulation reproduces its failure, not a
validity approval. The source artifact is preserved.

Evidence bundles observe Python/dependency versions and a digest of the
package's Python source files. Replay reports changes in that runtime
metadata separately from computational result differences. These records
are observations, not a dependency lock, digital signature or scientific
approval. Hashing and export reject NaN/Infinity and unsupported values.
JSON replay also rejects duplicate keys. Exports serialize fully before
atomically replacing the destination; failed writes preserve the old file.

Plus a **crossed retraining/stress study** (`orchestration.study_run`, PR-017):

```bash
python -m prometheus.orchestration.study_run \
  --output evidence/my_study.json
python -m prometheus.orchestration.replay evidence/my_study.json \
  --output evidence/my_study_replayed.json
```

The default design trains three policies on independent policy/data seed
pairs, then crosses them with three held-out path banks in three declared
scenarios: baseline, realized volatility 0.35 instead of 0.20, and doubled
execution cost. All 27 cells are retained with CVaR, paired conditional
intervals, mean loss/cost/turnover and the actual test-path hash. Models
train once and are not refitted for stress cases. Every model sees the
same paths in a scenario/bank. The initial premium, financing rate and
delta's assumed volatility stay at training values, so neither hedge gets
an oracle update under stress. Drift/volatility/cost scenarios can be
specified through `StudyRunConfig` and are fully recorded in the recipe.

The endpoint averages cell-level delta-minus-policy CVaR differences; it
does not pool losses or select the best fitted seed. The exploratory
[pigeonhole bootstrap](https://arxiv.org/abs/0712.1111) separately resamples
complete training rows and shared test-bank columns. The report includes
crossed and single-axis intervals plus conditional seed dispersions.
These diagnostics do not decompose variance into independent components.
The study allocates nominal tail error across scenarios with Bonferroni
and requires all scenario intervals to exceed the predeclared economic
margin in one direction for an overall directional verdict. Only crossed
intervals drive that decision; single-axis intervals remain diagnostics.
With few seed
levels, percentile intervals have no exact coverage guarantee; nominal
tail allocation does not establish calibrated family coverage.

The full study, training-data/model hashes and canonical seed/scenario
order are covered by the result hash. Replay retrains all models and
recomputes every scenario. See the generated
[reference study](./evidence/hedge_study_reference.json) and
[validation record](./evidence/validation_pr017.md). This extends parameter
stress and retraining diagnostics; historical-data, Heston/jump, macro
factorial and independent-review coverage remain open.

Plus a **price-discovery economy** (`orchestration.economy_run`, PR-018):

```bash
python -m prometheus.orchestration.economy_run \
  --output evidence/my_price_economy.json
python -m prometheus.orchestration.replay evidence/my_price_economy.json \
  --output evidence/my_price_economy_replayed.json
```

Every month, a cash-capped firm payroll bid meets elastic household labor
supply. The realized labor produces goods that enter physical inventory;
household demand is capped by realized wage income and cash. Both wage
and goods price are discovered from monotone budget-demand/linear-supply
schedules by bounded integer-tick bisection. Quantities, allocations and
inventory use exact rational arithmetic. Price bounds, adjacent ticks,
unmet demand and evaluation limits have distinct recorded statuses.
`valid=true` establishes simulation/accounting checks, not exact market
equilibrium at every quote. The default productivity shock halves output
per labor hour at step 4; optional seeded productivity noise is recorded,
including any zero-floor clipping.

Each exact market settles as one balanced journal batch after all parties,
currencies and funding requirements are checked. Deterministic
largest-remainder allocation distributes the integer floor of the entire
market's nominal value; the exact remainder is recorded and stays below
one minor unit per market. Original fixed-quote helpers retain their
per-household floor convention and now preflight the complete payment plan.
Ledger currency checks happen before any account changes. Rejected
transactions leave automatic IDs available; duplicate IDs are rejected,
and economic-state balance mappings are detached and read-only.

The example tracks cash/equity conservation, non-negative balances, labor
hours, production, sales, inventory, full quote-search traces and journal
batches. It records explicit opening capital/endowments and introduces no
later cash injections. These are specified behavioral rules, with a fixed
nominal payroll target and unvalued physical inventory; they do not claim
profit maximization or competitive general equilibrium. The economy
runner uses the action/settlement hooks. Financial pricing/hedging remains
in the separate monthly reference scenario. Atomicity covers individual
markets; failed multi-market steps halt without rollback or resumption.

See the [generated reference economy](./evidence/economy_price_reference.json)
and [validation record](./evidence/validation_pr018.md).

Plus a **published-data monetary feedback scenario**
(`orchestration.monetary_run`, PR-019):

```bash
python -m prometheus.orchestration.monetary_run \
  --output evidence/my_monetary_run.json
python -m prometheus.orchestration.replay evidence/my_monetary_run.json \
  --output evidence/my_monetary_replay.json
```

The reusable `econosim.price_economy.PriceEconomy` supplies actual traded
goods prices and physical production to the point-in-time store, with a
publication lag of at least one model month. Two published prices establish
an annualized log price change; released model-step metadata keeps business-day
date adjustments out of its annualization. A bounded inflation/output rule
sets a smoothed closing policy rate. No-trade quotes create no macro data;
the rule holds its previous rate during warmup. Latest published inputs can
remain stale when trading stops.

Each financial interval uses its opening rate, inherited from the previous
close, for GBM physical drift and hedge cash accrual. The current closing
rate sets Black-Scholes marks and rehedging, then finances the next interval.
The firm's desired payroll also responds to the opening rate through an
explicit exponential demand rule, closing the feedback loop into production
and prices. The default sensitivity is 2; `--payroll-rate-sensitivity 0`
disables that channel. The default publication lag is one month and can be
changed with `--publication-lag`. The exported nested recipe records all
economy, policy, training, execution and risk settings, every publication,
policy input, opening/closing rate, trade and conservation check.

Economic cash and hedge accounts retain separate balance sheets; the payroll
rule creates no loan or interest postings. This is an uncalibrated synthetic
feedback experiment. Black-Scholes marks assume the current closing rate
stays flat until expiry; no joint stochastic-rate risk-neutral valuation is
solved. Conditional CVaR freezes current holdings and rates, and the MLP
trains on constant-initial-rate GBM. One realized trajectory establishes no
policy superiority. The original standalone price-economy recipe and import
paths remain supported and its historical result replays exactly.

See the [coupled reference](./evidence/monetary_reference.json),
[replay](./evidence/monetary_replay.json) and
[validation record](./evidence/validation_pr019.md).

Plus a **crossed macro-feedback hedge study**
(`orchestration.monetary_study`, PR-020):

```bash
python -m prometheus.orchestration.monetary_study \
  --output evidence/my_monetary_study.json
python -m prometheus.orchestration.replay evidence/my_monetary_study.json \
  --output evidence/my_monetary_study_replayed.json
```

The default design crosses three independently retrained policies with
three shared economy/market banks in four scenarios: baseline, two-month
publication lag, disabled payroll-rate feedback and a more severe supply
shock. Each bank has one stochastic productivity/economy path and 512
conditional GBM market paths over twelve months. Scenario variants share
economy noise and market normals; every trained policy and delta see the
same market prices within a bank. Models train once per replicate on the
original constant-rate distribution, before any scenario evaluation.
The shared `MonetaryProcess` supplies exactly the online runner's economic
and publication hooks, without retraining or risk Monte Carlo per path.

Batch hedging accepts an explicit interval funding schedule and retains
trade-then-accrue accounting. Delta uses each current closing rate and the
original pricing volatility, even under an optional realized-volatility
stress; the MLP receives its original three causal features. Neither hedge
receives future rates. Scenario settings also support execution-cost stress.

The endpoint averages bank-conditional CVaR differences, delta minus MLP.
It is not an unconditional CVaR obtained by pooling macro/market losses.
Exploratory crossed bootstrap intervals resample complete training rows and
shared bank columns, with nominal Bonferroni tail allocation across the
declared scenario family. All scenario intervals must exceed the economic
margin in the same direction for the corresponding overall verdict. Few
seed levels limit coverage reliability. A failed macro bank invalidates
the entire experiment and suppresses training/inference, retaining all
bank records instead of selecting a successful subset.

For a custom run, pass `--recipe path/to/complete_config.json`. A complete
recipe is the exported `monetary_study.config` object, or a JSON encoding of
`dataclasses.asdict(MonetaryStudyConfig())` using
`experiments.manifest.json_default`. Missing nested fields, duplicate JSON
keys and non-finite JSON constants are rejected. Bank seeds replace the
economy template's seed; each scenario replaces its shock multiplier.
`hedge.risk_eval_n_paths` is retained by the shared hedge settings schema
but is unused here: this study evaluates realized losses on `n_eval_paths`
market paths, rather than the online runner's frozen-holdings risk estimate.

The exported study contains every macro trace, observation date, decision
rate, training hash, bank-normal/price hash, cell-level loss hash, CVaR,
cost, turnover and bootstrap diagnostic. Replay retrains all models and
reconstructs every bank. This evaluates specified synthetic channels; it
does not identify an optimal monetary policy or add empirical validation.
See the [reference study](./evidence/monetary_study_reference.json),
[replay](./evidence/monetary_study_replay.json) and
[validation record](./evidence/validation_pr020.md).

Plus a **matched current-rate feature experiment**
(`orchestration.rate_study`, PR-021):

```bash
python -m prometheus.orchestration.rate_study \
  --output evidence/my_rate_study.json
python -m prometheus.orchestration.replay evidence/my_rate_study.json \
  --output evidence/my_rate_study_replayed.json
```

Each training replicate fits two four-input MLPs on identical changing-rate
macro/market training data. Both networks have two hidden layers of 32 and
tanh-bounded holdings. They share parameter initialization, sampled
minibatches, optimizer settings and gradient clipping. Their sole feature
difference is the fourth input:

| Input | Rate-aware arm | Matched rate-blind arm |
|-------|----------------|-----------------------|
| 1–3 | log-moneyness, remaining time fraction, previous holding | same |
| 4 | (current rate - initial rate) / configured scale | zero |

The scale defaults to .1 and is fixed before evaluation. The current rate
is known at the hedge decision; no future rates or unreported macro data
enter features. Both policies train through the same trade-then-accrue cash
recursion used in the batch simulator, including path-specific rates.
The default gradient norm bound is 10. Epoch diagnostics record objective,
CVaR, mean loss/turnover, gradient norm before clipping and action saturation.
Policy hashes bind feature masking/scaling as well as network parameters.

Each row's training data combines three independent stochastic economies
from a separately configured training scenario, with 1,500 market paths
allocated evenly among them. Named training economy/market streams differ
from held-out evaluation streams. Three independent rows produce six
fitted models. Evaluation reuses PR-020's bank builder and four scenarios,
with delta, rate-blind and rate-aware arms on the same prices in each of
36 cells. The original three-input constant-rate experiment remains
available through PR-020 and its historical reference still replays.

The primary contrast is rate-blind minus rate-aware bank-conditional CVaR;
delta minus rate-aware is a declared secondary contrast. Crossed bootstrap
intervals retain shared rows/banks. Nominal Bonferroni allocation covers
all eight scenario/contrast pairs. The overall primary verdict requires
all scenarios to exceed the economic margin in one direction. Additional
information is not assumed to improve performance, and few independent
seed levels still limit coverage reliability.

For a custom run, use `--recipe` with the complete exported
`rate_study.config`. Training macro labels must be unique and disjoint from
test labels; role-specific streams also separate their actual draws. A
failure in any training or evaluation macro bank suppresses all fitting
and inference. Financial/training numerical failures raise without selecting
successful arms. Complete trace, data/model/minibatch hashes, diagnostics,
cell metrics and intervals are exported and recomputed by replay.

This adds one current-rate feature, without a macro-history encoder or
empirical identification. Training uses a finite macro-path mixture;
evaluation still averages conditional CVaRs rather than estimating pooled
unconditional macro/market CVaR. See the
[reference](./evidence/rate_study_reference.json),
[replay](./evidence/rate_study_replay.json) and
[validation record](./evidence/validation_pr021.md).

Plus **empirical macro/market-mixture tail risk**
(`orchestration.mixture_study`, PR-044):

```bash
python -m prometheus.orchestration.mixture_study \
  --output evidence/my_mixture_study.json
python -m prometheus.orchestration.replay evidence/my_mixture_study.json \
  --output evidence/my_mixture_replay.json
```

This reuses the matched rate experiment's fitted models and evaluation
banks, collecting detached terminal-loss samples after each cell's metrics
are computed. Each fitted model's macro/market losses are pooled before
CVaR; the endpoint then averages differences across retrainings. Macro
banks receive equal weight, with equal conditional path weights. The
original conditional-risk endpoint remains available as an auxiliary
diagnostic: a mixture's CVaR can give a different ordering from the average
of bank-conditional CVaRs. Different fitted policies are never pooled into
a synthetic ensemble.

Nested bootstrap draws complete training rows, shared macro banks and
paired market indices within each drawn bank occurrence. Every hedge arm
and training row shares the same bank/market selections. Repeated draws of
one bank get fresh inner path samples. Training-only, macro-only and
market-only intervals diagnose individual sampled axes; they are not
additive variance components. The declared mixture scenario/contrast
family receives nominal Bonferroni allocation. Original conditional-risk
intervals have a separate family and do not determine the new verdict.

The exported bundle retains full terminal-loss cubes, cell/cube hashes,
the complete conditional-study recipe/trace, mixture CVaRs for each fitted
model, all uncertainty diagnostics and model-card mixture metrics. Actual
replay retrains the models and reconstructs both risk calculations. Complete
recipes use `--recipe`; missing fields, non-finite samples, mismatched loss
shapes, invalid resampling counts and overflowing risk calculations fail
explicitly. An invalid CLI recipe preserves an existing output artifact.

This is a finite empirical mixture of synthetic macro banks. It does not
estimate calibrated unconditional population tail risk, and few independent
macro/training levels leave bootstrap coverage uncertain. The new endpoint
is declared in code before results are inspected. See the
[reference](./evidence/mixture_study_reference.json),
[replay](./evidence/mixture_study_replay.json) and
[validation record](./evidence/validation_pr044.md).

Plus **sealed artifact audit and full-blueprint traceability**
(`prometheus.evidence`, PR-045):

```bash
python -m prometheus.evidence.verify evidence/my_mixture_study.json
python -m prometheus.orchestration.replay evidence/my_mixture_study.json \
  --require-integrity --output evidence/my_mixture_replay.json
python -m prometheus.evidence.requirements \
  --pdf docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf \
  --output docs/implementation/blueprint_register.json
```

New exports seal a detached JSON snapshot of the whole artifact, covering
model cards, gate, runtime, recipe, results and replay metadata. Export
refuses an invalid existing seal instead of silently blessing a changed
artifact. Validation runs before temporary-file creation and atomic replace.
Approval/reviewer fields require names; malformed dates, non-finite metrics
and model-card fingerprints inconsistent with training metadata are rejected.

The offline auditor defaults to requiring a valid seal and does not train
models or simulate paths. `--expected-content-sha256` additionally checks
an independently supplied artifact pin. Checksums establish consistency,
not authorship or scientific approval. `--allow-legacy` explicitly permits
unsealed historical artifacts. Replay retains legacy compatibility, reports
the input's integrity mode, and can require a seal. Computational result
hashes retain their existing meaning and reproducibility.

The [complete requirement register](./docs/implementation/blueprint_register.json)
preserves all 374 blueprint items, their acceptance criteria and source
pages: 362 research/enterprise items plus 12 separately gated live-extension
items. Repository-note links are unreviewed hints; none is automatically
marked accepted. The [implementation plan](./docs/IMPLEMENTATION_PLAN.md)
keeps all 29 categories in scope and distinguishes remaining code work from
human review/authorization requirements. See
[validation](./evidence/validation_pr045.md).

Plus **bounded durable local research jobs** (`prometheus.jobs`, PR-046):

```bash
python -m prometheus.orchestration.recipes --kind economy
python -m prometheus.jobs --root .prometheus/demo submit \
  --kind economy --owner local --idempotency-key economy-example-v1
python -m prometheus.jobs --root .prometheus/demo work --once
python -m prometheus.jobs --root .prometheus/demo list --owner local
python -m prometheus.jobs --root .prometheus/demo audit
```

The shared recipe registry allowlists all nine research runners, validates
complete typed configurations, normalizes recipes and estimates admitted
work before queue submission. Bounds cover recipe structure/precision,
steps, agents, paths, epochs, training/evaluation work and crossed/nested
bootstrap work. These are admission estimates, not calibrated runtime or
hard RSS guarantees. Trusted standalone replay retains its historical
configuration range. Custom job requests use `--recipe` with the complete
flat configuration object for the selected runner.

SQLite transactions persist jobs, idempotency identities, observed source/
dependency snapshots and append-only hash-chained events. Retrying the same
owner/key/request returns the same job; changed requests conflict. Pending
and running capacities are enforced transactionally. Owner-scoped reads
and cursor pagination support isolated lookups. The local CLI relies on OS
permissions; it is a trusted-operator interface, with no authenticated HTTP
service added in this slice.

Each Linux worker attempt runs in a fresh process. Wall/CPU/file bounds,
process-group cancellation and parent-death termination stop abandoned
execution. Attempt tokens fence stale workers after lease recovery. A
cancellation request prevents successful publication; invalid simulations
retain their failed evidence. Runtime/source changes reject queued work
before execution. Service credentials are excluded from the child
environment allowlist. Job/trace/recipe identifiers bind output artifacts
to the current attempt. No user-supplied Python module or shell is run.

Artifacts publish by verified content address with atomic no-clobber links,
file/directory sync and a cross-process storage quota lock. Reads verify
the complete seal and declared metadata. Defaults allow 128 MiB per
artifact and 1 GiB total object bytes; existing valid objects deduplicate
even at capacity. Known inactive staging attempts can be cleaned after
recovery; active, unknown and symlinked directories are preserved. Metadata
and audit retention are separate remaining requirements.

Use the printed job ID with `show JOB_ID --owner local`,
`cancel JOB_ID --owner local`, or `artifact JOB_ID --owner local --output
evidence/my_job.json`, after the same `--root` option. `work --once` reports
whether a job was processed; inspect the returned terminal status/error code
for its outcome. Successful execution does not change the artifact's gate
decision. Queue policy changes require an explicit migration/new store.

This is a single-host Linux research backend. PR-047 supplies the HTTP
boundary below. Distributed workers, cgroup RAM limits, full untrusted
code sandboxing, signed audit checkpoints, backup/restore exercises and
production SLOs remain in the full-blueprint plan. See
[design/operations notes](./docs/LOCAL_JOBS.md) and
[validation](./evidence/validation_pr046.md).

Plus **authenticated versioned research-job HTTP API and typed SDK**
(`prometheus.service`, PR-047):

```bash
python -m prometheus.service init-auth \
  --credentials .prometheus/api/auth.json --token-file .prometheus/api/token \
  --owner local
python -m prometheus.service serve --root .prometheus/api \
  --credentials .prometheus/api/auth.json
# Run a worker separately against the same root:
python -m prometheus.jobs --root .prometheus/api work
```

Install the `service` extra for serving. The default listener is loopback;
non-loopback binding requires a TLS certificate/key. The ASGI app derives
owner and read/write scopes from private server credentials. It ignores
forwarded identity/scheme headers, reloads credential hashes per request,
and never accepts owner or executable code from the submit body. Rotating
the private file revokes tokens without restarting the API.

The [OpenAPI contract](./docs/api/openapi-v1.json) defines complete typed
recipes for all nine runners, submit/status/cancellation, owner-scoped
cursor lists, verified artifact retrieval and health endpoints. Submission
requires an idempotency key. Requests have byte/header/depth/work budgets,
body read deadlines, per-process rate and concurrency limits. Diagnostic
IDs and structured logs correlate HTTP requests to job/trace identities.
Readiness probes credential availability, SQLite writer admission and
artifact-directory access; it does not certify worker capacity or free disk.

```python
from pathlib import Path
from prometheus.orchestration.recipes import default_recipe
from prometheus.service.client import ResearchClient

client = ResearchClient("http://127.0.0.1:8765",
                        Path(".prometheus/api/token").read_text().strip())
job = client.submit("economy", default_recipe("economy"),
                    idempotency_key="economy-example-v1")
status = client.get_job(job.job_id)
# After the worker finishes, this verifies the seal and job lineage:
# artifact = client.get_artifact(job.job_id)
```

SDK reads have bounded bytes and socket-operation timeouts. Redirects and
environment proxies are disabled. Network integration tests exercise the
SDK against a real ASGI server and separate worker. SSO/OIDC, vault-backed
secrets, externally verified TLS/primary-storage encryption, distributed limits,
deployment/load/SLO validation and independent approval remain open. See
[API operations and compatibility](./docs/RESEARCH_API.md) and
[local validation](./evidence/validation_pr047.md).

Plus **locked builds and encrypted local recovery** (PR-048):

`uv.lock` fixes dependency versions, artifact hashes and the dedicated PyTorch
CPU source. Build tools and the uv bootstrap are pinned too. The build checker
uses a fresh environment and two explicit source snapshots with different
paths/file times, verifies wheel RECORD/package bytes, and requires identical
wheel hashes. CI now installs that wheel and runs its tests against the locked
dependencies. The tracked CycloneDX SBOM describes the resolved service/recovery
dependency profiles; it is not a deployed inventory or vulnerability report.

```bash
python -m prometheus.recovery keygen --output .prometheus/backup.key
python -m prometheus.recovery create --root .prometheus/api \
  --output .prometheus/backups/research.enc --key-file .prometheus/backup.key
python -m prometheus.recovery verify --input .prometheus/backups/research.enc \
  --key-file .prometheus/backup.key
python -m prometheus.recovery restore --input .prometheus/backups/research.enc \
  --key-file .prometheus/backup.key --destination .prometheus/restored-api
```

Recovery snapshots authenticate/encrypt a consistent SQLite backup and only
its referenced immutable artifacts. Verification checks database integrity,
audit/job projection, complete artifact seals and lineage. Restore authenticates
before parsing, rejects unsafe/malformed content, fences copied worker leases,
and atomically publishes a new root without replacing an existing directory.
Credentials, encryption keys and in-flight working directories are excluded.
The original service must be isolated before promoting a restored copy.

Container rebuild/digest verification, signed provenance, offsite storage,
vault/key custody, approved RPO/RTO and production failover remain open.
See [build instructions](./docs/REPRODUCIBLE_BUILDS.md),
[recovery operations](./docs/RECOVERY.md), and
[local validation](./evidence/validation_pr048.md).

Plus **evidence export** (`prometheus.evidence`), applying the same
"cannot construct an invalid claim" discipline used everywhere else in this
codebase to the paperwork itself:

- `ModelCard` — every mandatory section (section 16) is a required field;
  omitting one raises at construction. Marking one `"APPROVED"` without
  naming `independent_reviewer` raises too.
- `GateDecisionForm` — mirrors section 16's gate decision form. Constructing
  one with `decision="GO"` or `"CONDITIONAL"` *without* naming both
  `scientific_approval` and `security_ops_approval`, and a `sunset_date`,
  raises. There is no code path that produces an unsigned GO record.
- `current_repository_gate_report()` — generates this repository's actual,
  current gate status from code. It returns `decision="NO-GO"`, matching
  the blueprint's own section 19 verdict — because no independent review of
  anything here has happened yet, not because the code says so by default.
  The real, generated artifact is committed at
  [`evidence/gate_report_r0.json`](./evidence/gate_report_r0.json).
- `build_evidence_bundle` — every bundle unconditionally carries a
  simulation/non-advice disclaimer and a machine-readable source tag
  (AUD-08); there is no way to export one without them.

Plus a first piece of **risk-neutral calibration** (`prometheus.volterra.calibration`),
not yet consumed anywhere else in this repository:

- `calibrate_implied_volatility` — recovers the Black-Scholes implied
  volatility from one observed option price via bracketed root-finding
  (`scipy.optimize.brentq`). A quote is checked against the model's
  volatility-independent no-arbitrage bounds *before* any search is
  attempted; a quote no volatility could rationalize raises
  `CalibrationError` naming those exact bounds, rather than being handed to
  a root-finder that would fail opaquely. A 27-case round-trip test (3
  strikes x 2 option types x 3 volatility regimes) recovers the true
  volatility to within `1e-8` in every case, not just one convenient one.
- `calibrate_volatility_smile` — applies the above independently across a
  list of (strike, price) quotes at a shared spot/rate/maturity. Tested
  against both a flat true surface (recovers a constant implied vol) and a
  genuine non-flat smile shape (recovers the exact strike-by-strike shape),
  confirming the fit captures real cross-strike variation rather than just
  averaging. No cross-strike smoothness or arbitrage-free-surface
  constraint is imposed — that remains a separate, unimplemented concern.

Plus a first piece of **portfolio optimization** (`prometheus.titan.portfolio`),
the first evidence anywhere in this repository for TITAN's OPT-* checklist
category, which had none before it, and also not yet consumed elsewhere:

- `minimum_variance_portfolio` / `target_return_portfolio` — the classic
  global minimum-variance and Markowitz target-return formulations (SLSQP),
  each checked against its exact closed-form analytical solution (the
  `Sigma^-1 1` global-min-variance formula and the two-fund target-return
  formula) to within `1e-7`, not an approximate or qualitative check. A
  box constraint that makes the budget unreachable (e.g. `max_weight *
  n_assets < budget`) is confirmed to report `success=False` with a
  diagnostic message, not a silently-wrong allocation.
- `cvar_optimal_portfolio` — Rockafellar-Uryasev scenario-CVaR minimization
  via linear programming (`scipy.optimize.linprog`, HiGHS). Cross-checked
  against an *independent* brute-force grid search over a 2-asset weight,
  computed with `titan.risk_metrics.historical_expected_shortfall` directly
  — a different code path from the LP, not the same implementation checked
  against itself — and matched to within 1% of the optimal weight.
- A turnover penalty (`target_return_portfolio`'s `turnover_penalty`/
  `prior_weights`) is confirmed to strictly reduce realized turnover
  relative to a given prior portfolio, holding the return target fixed.
- Every result (`OptimizationResult`/`CVaROptimizationResult`) carries its
  solver name, success flag and termination message unconditionally —
  there is no code path that returns an infeasible solve's weights without
  also saying so (OPT-09).

Plus **covariance shrinkage** (`prometheus.titan.covariance`), connecting
directly to the portfolio optimizer above:

- `shrink_covariance_ledoit_wolf` — Ledoit & Wolf's (2004) analytic
  shrinkage of the sample covariance toward a scaled-identity target. The
  formula was derived by reading scikit-learn's own source, not
  reimplemented from memory of the paper, and is cross-checked against
  that reference implementation to within `1e-9` across six
  (observations, assets) regimes — including the n < p case, where the raw
  sample covariance is mathematically singular and the shrunk one is
  confirmed strictly positive definite instead. scikit-learn is a dev-only
  dependency here (the test oracle), not a runtime one.
- The practical payoff is demonstrated, not just asserted: across repeated
  small-sample draws (15 observations, 10 assets) from a fixed true
  covariance, a minimum-variance portfolio built from the *shrunk*
  covariance has lower **true** (population, not sample) out-of-sample
  variance than one built from the raw sample covariance — on average and
  in the majority of individual trials.
- `shrinkage_intensity_to_target`/`shrink_covariance_to_target` (PR-050)
  generalize the above from "shrink toward scaled identity" to "shrink
  toward any fixed target matrix" — an independently-written
  implementation confirmed to reproduce `shrink_covariance_ledoit_wolf`
  exactly at that special case, not a refactor of it. Combined with the
  factor model below, shrinking toward a believed factor structure instead
  of toward "no structure at all" is shown, across 200 repeated
  modest-sample draws from a genuinely factor-structured true covariance,
  to lower both the estimate's own error and the resulting minimum-variance
  portfolio's true out-of-sample variance, versus the identity target.

Plus a **multi-period rebalancing simulator** (`prometheus.titan.rebalancing`),
the first module connecting the two sections above across simulated time
rather than as standalone single-period calls:

- `simulate_rebalancing` — walks a plain `(n_total_periods, n_assets)`
  returns array period by period, periodically re-estimating a (optionally
  Ledoit-Wolf shrunk) covariance from a trailing window and re-optimizing
  (minimum-variance or Markowitz target-return) against the realized prior
  holdings with an optional turnover penalty, executing the resulting
  trade under a proportional transaction cost. It takes any return source
  (stochastica-generated paths, historical data, or a hand-built array) —
  it does not generate its own.
- No-lookahead causality is tested directly, not just claimed: perturbing
  returns far beyond any early period's estimation window leaves that
  period's weights, realized return and wealth bit-identical to an
  unperturbed run. Wealth is also independently recomputed outside the
  module from each period's reported return and cost and confirmed to
  match the reported path to `1e-10`.
- A scheduled rebalance whose optimization is infeasible raises a
  dedicated `RebalancingFailure` — the simulation stops rather than
  silently carrying forward stale weights under a label of having
  rebalanced.
- Higher transaction costs and more frequent rebalancing both show the
  expected monotone effect on final wealth and total turnover,
  demonstrated empirically with the return path held fixed.

Plus a **central-bank ledger-backed balance sheet**
(`prometheus.econosim.central_bank_ledger.CentralBankLedger`), built the
same way every other agent in `econosim.agents` is (open its own accounts,
post one balanced `Transaction` per economically meaningful operation) --
`econosim.policy_rate.CentralBank` (the rate-process wrapper used
everywhere else in this repository) is untouched and still has no balance
sheet; this is a new, separate agent:

- `purchase_government_bonds` / `sell_government_bonds` — open market
  operations: the central bank buys/sells a registered bank's
  loans-receivable balance in exchange for reserves credited to that
  bank's settlement account. A full buy-then-sell round trip is confirmed
  to return every balance involved to its exact starting value.
- `lend_to_bank` / `repay_central_bank_loan` — discount-window lending, a
  second reserve-issuance channel matched by a central-bank receivable
  rather than by securities, also confirmed to round-trip exactly.
- `settle_interbank_transfer` — moves reserves between two *different*
  `Bank` instances' accounts at this central bank: the first transaction
  anywhere in this repository posting against two distinct agent
  instances that share one `Sector` (`Sector.BANK`) within a single
  Transaction. Confirmed to reallocate an existing liability between the
  two banks' sub-accounts without changing the central bank's total
  reserve liability.
- A real limitation was caught by writing this module's own tests, not
  asserted after the fact: `settle_interbank_transfer` is balanced only at
  the whole-`Sector.BANK` level (what `Ledger.check_identities` actually
  checks), not on either individual bank's own book in isolation — a true
  settlement is paired with a matching customer-deposit movement that this
  repository cannot post, since no cross-bank customer deposit mechanism
  exists yet. The other two channels (OMO, discount window) *are*
  confirmed balanced on each individual bank's own book, by hand-summing
  only that bank's accounts — a strictly finer check than the ledger
  provides natively.
- The central bank's own equity account is opened for structural symmetry
  with every other agent but is never posted to by any operation here —
  every issuance channel is exactly asset-for-liability, confirmed to
  leave central-bank equity at zero throughout.

Plus a **factor exposure model and risk decomposition**
(`prometheus.titan.factor_model`), the first evidence anywhere in this
repository for TITAN's RISK-07:

- `estimate_factor_exposures` — per-asset OLS alpha, factor betas, residual
  variance and R^2 against a set of common factor returns, solved for
  every asset at once from one shared design matrix. Cross-checked against
  `numpy.linalg.lstsq` — a different algorithm (SVD-based, not matrix
  inversion) — to within `1e-9`.
- `decompose_portfolio_variance` — splits a portfolio's total variance
  into factor-driven and idiosyncratic components under the standard APT
  assumption that idiosyncratic shocks are uncorrelated across assets,
  plus a per-factor Euler marginal-contribution breakdown that sums
  exactly to the factor total. Independently cross-checked against a
  direct `w' Sigma w` quadratic form over the full implied covariance
  matrix, a completely different computational path.
- The practical payoff is demonstrated, not just asserted: exposures
  estimated from 5,000 simulated observations of a KNOWN factor model
  produce a decomposition that converges to within 5% of the one computed
  from the ground-truth parameters — a genuine statistical recovery check.
- Composes naturally with earlier TITAN modules: a `minimum_variance_portfolio`
  (PR-023) built from a `shrink_covariance_ledoit_wolf`-shrunk covariance
  (PR-024) has its risk decomposed through the factor route and confirmed
  to match the direct quadratic-form risk under the same factor-implied
  covariance, in one connecting test.
- `factor_model_implied_covariance` (PR-050) promotes that direct
  quadratic-form matrix — previously built inline, test-only, in two
  separate test functions — into its own reusable function, so it can
  (and now does) serve as a `titan.covariance` shrinkage target.

Plus **the central bank wired into the real StepHooks event order**
(`prometheus.econosim.monetary_operations`), the first scenario anywhere
in this repository to drive `CentralBankLedger` (PR-026) through
`MacroTimeEngine.advance_step()` rather than standalone calls:

- Each step, the existing rate-only `policy_rate.CentralBank` decides the
  policy rate (the same rule, the same `.step(shocks)` call
  `multi_step_run.py` already uses); the rate's *change* that step sizes
  an open market operation — buy when easing, sell when tightening —
  executed through `CentralBankLedger`.
- A fixed discount-window loan is drawn once and amortized on a schedule;
  a periodic interbank reserve transfer moves reserves between two banks
  — exercising all three `CentralBankLedger` channels together, across
  simulated time, for the first time.
- A failed/infeasible operation (insufficient bonds to sell, insufficient
  settlement balance to transfer or repay) is skipped and recorded rather
  than halting the run or silently corrupting the amortization schedule —
  confirmed directly: a repay attempt that fails leaves the internal
  remaining-balance tracker exactly unchanged.
- An exact reconciliation, not an approximate one: after a full seeded
  run, a bank's final reserve balance is confirmed to equal precisely the
  count of successfully executed interbank transfers times the configured
  transfer amount, once the (separately amortizing) discount-window loan
  has netted to exactly zero.
- `Economy.add_central_bank_ledger` tracks a `CentralBankLedger` the same
  `add_*`-by-id way every other agent is tracked, closing PR-026's own
  "not wired into `Economy`" admission.
- (PR-034) A genuine direct interbank loan (`InterbankMarket`, PR-033)
  between the two banks, amortized on its own independent schedule, and a
  periodic LIVE systemic-risk check — every few steps,
  `network_risk.run_contagion_analysis` clears the real network and the
  result is recorded directly in that step's settlement. A real default
  engineered inside a running process is confirmed detected by this exact
  wired-in check, not by testing contagion analysis in isolation again.
  Building this caught a genuine bug in its own first draft — an
  unguarded capacity-constrained operation, copied from the discount
  window's unconditional central-bank lending, that could have crashed a
  step — fixed before the feature was evidenced as done.
- (PR-036) The check now ACTS on what it finds: a one-way circuit breaker
  suspends new discount-window/interbank lending for the rest of the run
  the first time a default is ever detected, while existing debt keeps
  amortizing normally and OMO/reserve-transfer activity continues
  unaffected. The freeze is set at the end of the step that detects it
  and consulted only at the start of the NEXT step's decision — a step's
  lending choice never depends on information only available at the end
  of that same step.

Plus a **position book with snapshot linkage**
(`prometheus.titan.positions`), the first evidence anywhere in this
repository for RISK-01/RISK-13:

- `Position` ties a signed quantity to the exact `MarketSnapshot` it was
  entered against and its per-unit entry price; `value_position`/
  `value_book` mark it (or a whole `PositionBook`) to a CURRENT snapshot
  and instrument, computing mark price, market value and unrealized P&L.
  Deliberately does not invent a day-count convention to decay maturity
  from calendar dates — the caller supplies the current remaining
  maturity explicitly, the same way `multi_step_run.py` already does.
- Two independent flavors of stale-snapshot rejection, both tested
  separately: a current snapshot dated before the position's own entry
  snapshot (structurally nonsensical), and, when a caller supplies an
  `as_of`/freshness tolerance, a snapshot older than that tolerance.
- A current instrument's identifying terms must match the position's
  original contract exactly — strike and option type for an option,
  delivery price for a forward (below) — only remaining maturity may
  differ — and maturity is rejected from running backward.
- The practical payoff is demonstrated end to end: a position is marked
  to 200 simulated daily spot moves, the resulting realized daily P&L
  series is fed directly into PR-006's `historical_var` — composing a
  VOLTERRA pricing module with a TITAN risk module for the first time.

Plus **forward contracts** (`prometheus.volterra.forwards`), a second
instrument type (PR-037) generalizing the position book above beyond
options:

- `forward_price`/`forward_contract_value` price by cost of carry: a
  brand-new contract's fair delivery price is `F = S * exp((r-q)T)`, and
  an existing contract's value, `S*exp(-qT) - K*exp(-rT)`, is
  cross-checked against the economically equivalent `(F_now - K) * exp(-rT)`
  form — two independently-derivable expressions for the same
  no-arbitrage value.
- `titan.positions.Instrument` is now `EuropeanOption | ForwardContract`;
  a `PositionBook` can mix both kinds in one call, and repricing a
  position as the WRONG instrument type (not just the wrong terms) is
  rejected in both directions.

Plus **American options via a binomial tree**
(`prometheus.volterra.american_options`), the first non-closed-form,
non-Monte-Carlo pricing method in this repository:

- A Cox-Ross-Rubinstein tree prices `AmericanOption` (early exercise
  allowed at every node) and, with the IDENTICAL code path and early
  exercise simply disabled, `EuropeanOption` too — so comparing the two
  is a true apples-to-apples cross-check, not two independently-written
  pricers that might coincidentally agree.
- The European tree price converges monotonically to PR-005's
  closed-form Black-Scholes price as steps increase (50 → 200 → 800),
  to below a cent — a genuine numerical-convergence check.
- Two classical early-exercise theorems are tested as the exact
  equality/inequality they are, not approximate plausibility checks: an
  American call matches the European call exactly (to `1e-9`) absent
  dividends (never optimal to exercise early), and strictly exceeds it
  once dividends make early exercise valuable; an American put is always
  at least as valuable as the European put.
- Wired into `titan.positions` as a third instrument type (PR-039,
  below) — `value_position`/`value_book` gained an optional `n_steps`,
  required only when the instrument being valued is an `AmericanOption`
  and purely additive to every existing caller otherwise. Even with
  identical strike and option type, an American and a European option
  are confirmed to be different instrument TYPES that cannot be repriced
  as each other — the same discipline the forward/option check already
  established, generalizing to a third type cleanly.
- (PR-040) **Greeks** for American options, via `volterra.american_greeks`:
  delta/gamma are read directly from one binomial tree's own early
  nodes, not by bumping spot and rebuilding the tree — a real pitfall
  caught and demonstrated directly: naive central differences on a
  rebuilt tree are off by more than 10x even with a "reasonable" bump,
  because the tree price is piecewise-linear, not smooth, in spot.
  Vega/theta/rho don't share that pathology and use ordinary
  bump-and-reprice. All five Greeks are confirmed converging to the
  closed-form Black-Scholes Greeks in the no-dividend case, where
  PR-038 already proved the prices themselves are identical.

Plus a **Heston characteristic-function option pricer**
(`prometheus.volterra.heston_pricer`, PR-051), the first stochastic-
volatility pricer in VOLTERRA's ladder (every pricer before it was
GBM/deterministic-volatility):

- Uses the branch-stable "little trap" characteristic function
  (Albrecher, Mayer, Schoutens & Tistaert, 2007), not the original 1993
  formulation, which has a documented complex-logarithm branch cut that
  silently returns a wrong price for some parameter/strike combinations.
- Cross-checked four independent ways: two exact algebraic identities on
  the characteristic function itself (phi(0) == 1, phi(-i) == the
  forward price); put-call parity against a SEPARATELY, independently
  coded mirror-image integral (not the production put formula's own
  parity shortcut); the Black-Scholes degenerate limit (vol-of-vol -> 0);
  and Monte Carlo agreement with the pre-existing, independently-written
  `stochastica.heston` path simulator.
- `market.volatility` is deliberately unused (the variance process comes
  from the Heston parameters instead) — confirmed by a test that two
  markets differing only in that field price identically.

Plus a **Merton jump-diffusion model and closed-form pricer**
(`prometheus.stochastica.jump_diffusion` /
`prometheus.volterra.merton_pricer`, PR-052), a second non-GBM model with
its own matching price:

- The simulator's jump allocation is EXACT per step, not Euler-
  approximated: a Poisson jump count convolved with the matching sum-of-
  normals jump-size distribution has a closed form, so there is no
  discretization bias to characterize.
- The closed-form price is the classical Poisson-weighted Black-Scholes
  sum — but getting the Poisson weight right is a real, easy-to-make
  mistake: it must be the risk-neutral-ADJUSTED jump intensity
  `lambda*(1+k)`, not the physical `lambda` the simulator itself draws
  jump counts from. Both look equally plausible on paper; the wrong one
  was caught, before any production code was written, by deriving the
  formula independently from first principles and cross-checking both
  candidates against high-path-count (40 million) Monte Carlo — a lower
  path count could not actually tell the two apart, which would have let
  the wrong formula through silently.
- Cross-checked against the Black-Scholes zero-jump-intensity limit (call
  and put, with and without dividends), put-call parity, and Monte Carlo
  agreement with the independently-written simulator.

Plus **single-barrier options with a discretization correction**
(`prometheus.volterra.barrier_options`, PR-053), the first path-dependent
VOLTERRA pricer (every pricer before it only needed the terminal price):

- Priced from a reflection-principle derivation worked out from scratch,
  not transcribed from a reference table — the classical Reiner-
  Rubinstein closed form has roughly eight case-dependent sub-formulas
  that are easy to mis-transcribe from memory without catching the
  error, so this derives the GBM survival density directly and prices
  via numerical integration against it (the same style of semi-closed-
  form the Heston pricer already uses).
- Down/up barriers, knock-in/knock-out, calls and puts, with the
  knock-in side obtained via in-out parity against the Black-Scholes
  vanilla (matching the existing convention of deriving one side of a
  pricer from parity rather than a second formula).
- Adds the Broadie-Glasserman-Kou (1997) continuity correction for
  discretely- (not continuously-) monitored barriers: shifts the barrier
  away from the spot by `beta*sigma*sqrt(T/n_observations)` before
  repricing with the continuous formula. Confirmed, not just asserted, to
  cut pricing error by roughly one to two orders of magnitude versus the
  uncorrected continuous formula, against a direct simulation of the
  actual discretely-monitored process.
- The verification process itself caught a subtle trap: an initial Monte
  Carlo check using a naive "only look at discrete simulation grid
  points" barrier test showed small but consistent mismatches against the
  closed form — not because the formula was wrong, but because that kind
  of Monte Carlo has its own well-known discretization bias (it misses
  barrier crossings that happen between sampled points). Reweighting each
  simulated path by its Brownian-bridge continuity-corrected survival
  probability instead of a hard discrete check removed the bias and
  confirmed the formula was correct all along.

Plus **Asian options with a Kemna-Vorst control variate**
(`prometheus.volterra.asian_options`, PR-054), the second path-dependent
VOLTERRA pricer:

- Geometric-average Asian options have an exact closed form: a geometric
  average of GBM log-prices is itself Gaussian, so the standard lognormal
  option-pricing expectation applies directly, with a Gaussian mean/
  variance derived from a known identity for the covariance of equally-
  spaced Brownian motion samples.
- Arithmetic-average Asian options have no closed form (a sum of
  lognormals is not lognormal), so they're priced by Monte Carlo using
  the geometric average's exact price as a Kemna & Vorst (1990) control
  variate — the two are highly correlated (identical at zero volatility,
  differing only by Jensen's-inequality convexity otherwise), cutting
  standard error by roughly 20-30x versus plain simulation at the tested
  settings.
- The covariance identity behind the closed form was independently
  re-derived by brute-force double summation over every pair of fixing
  times, not assumed from the shortcut formula the production code uses.
  An AM-GM model-free sanity floor — the arithmetic price can never be
  below the otherwise-identical geometric price, true on every single
  path — was tested directly, not just asserted.
- The verification process caught one more subtlety: an initial
  zero-volatility limit check compared the priced geometric average
  against the *arithmetic* mean of the per-date forward prices and found
  a small mismatch — not a formula bug, but a bug in that check itself,
  since the geometric mean of several different forward levels sits
  strictly below their arithmetic mean whenever rates and dividend yield
  differ. Comparing against the geometric mean of the same forwards
  instead matched to six decimal places.

Plus **classical forecasting baselines and a rolling-origin backtest**
(`prometheus.macrocore`, PR-056), the first PR under the new addendum to
close an FP-NN item with genuinely new code (PR-055 extended a
pre-existing module; this one is new): Persistence, AR(p) and VAR(p):

- All three are deterministic OLS fits (`numpy.linalg.lstsq`, no
  stochastic optimizer) with closed-form Gaussian multi-step forecast
  intervals, derived from the AR/VAR polynomial's own MA(infinity)
  "psi-weight" expansion — not an ad hoc uncertainty band bolted on
  afterward.
- "ARIMA" in the addendum's own experiment-matrix language is
  represented here by AR(p) (ARIMA(p, 0, 0)) — a deliberate, documented
  scope cut against a full differenced, moving-average Box-Jenkins
  ARIMA(p, d, q), whose maximum-likelihood MA-term estimation is a kind
  of hidden complexity this project's own verify-before-trusting
  discipline is built to avoid.
- Backtested by a rolling-origin harness (`macrocore.evaluation`) that
  reads EVERY value — both the training window and the eventual scoring
  target — through `econosim.pit.require_eligible` at the correct
  `as_of` date, never through a bare ground-truth array, so a leakage
  bug in the harness's own indexing would raise `FutureDataError`
  immediately rather than silently inflating accuracy; confirmed
  directly by a test that engineers exactly that failure.
- The forecast-interval math was verified against independent Monte
  Carlo (millions of re-simulated paths from a fixed origin, under 0.5%
  relative error at every tested horizon) before being trusted in
  production code, then re-verified by a second, independently-coded
  psi-weight recursion written directly into the test suite — the same
  two-stage discipline already used for the Heston/Merton/barrier/Asian
  pricers.
- A model-free, exact sanity check: a stationary AR(1)'s long-horizon
  forecast variance must converge to its own unconditional variance
  `sigma^2/(1-phi^2)`, confirmed to 1e-6 relative error at h=200 — cheap
  and independent of the Monte Carlo check above.
- All synthetic data this module generates is labeled
  `source_license="synthetic-generated-for-testing-only"` and
  `quality_flags=("synthetic",)`; no real FRED-MD/ALFRED/Treasury data
  is ingested anywhere in this repository yet.

Plus a **Heston weak-convergence study** (`prometheus.stochastica.convergence`,
PR-057), the first evidence anywhere in this repository for SDE-05/VAL-03:

- GBM and jump-diffusion are both EXACT simulations (no Euler
  discretization, so no bias to study); Heston's log-Euler/full-
  truncation scheme is the one simulator here with genuine,
  non-zero discretization bias as a function of step size, so it's
  the one this module targets.
- `estimate_weak_convergence_order` (a log-log OLS slope of bias
  against dt) was independently verified against two synthetic cases
  of EXACTLY known order — pure `dt^1` and pure `dt^2` decay, recovered
  to `1e-9` — before being trusted on the real Monte Carlo result,
  which lands at order ≈ 0.78 (theory predicts ≈ 1 for this scheme).
- This PR started as a skeptical, literal re-audit of six "PARTIAL
  (pre-existing)" rows an earlier PR had added to the addendum
  checklist, after a prior misattribution (tagging VAL-01/03/14 to
  unrelated forecasting work) showed that "the evidence is nearby and
  roughly the right shape" is not the same bar as "this evidence
  literally satisfies what the ID requires." Two of the six really
  were over-credited and got corrected rather than left standing: FP-12
  falsely implied Greeks exist for all 5 VOLTERRA pricers (only
  Black-Scholes and American options actually have them); FP-16
  falsely implied some TITAN report carries horizon + units + cost
  together (none does — every risk function returns a bare `float`).
- A near-miss during this module's own pre-implementation verification
  directly shaped its design: an early draft allocated the full
  `(n_paths, n_steps+1)` Heston path array at `n_paths=4,000,000`,
  driving system memory from 4GB to 26GB/31GB used (swap nearly
  exhausted) before being killed and rewritten to batch paths,
  accumulating only running sum/sum-of-squares — the shipped function
  was written batched from the start as a direct result.

Plus **Greeks for Heston, Merton, barrier and geometric Asian options**
(`heston_greeks.py` / `merton_greeks.py` / `barrier_greeks.py` /
`asian_greeks.py`, PR-058), closing the gap PR-057's audit found:

- All four reuse the same `black_scholes.Greeks` dataclass and the same
  central-difference bump-and-reprice pattern `greeks_fd.py` already
  uses for Black-Scholes, cross-checked against Black-Scholes' own
  analytical Greeks in each model's degenerate (or, for Asian at
  `n_fixings=1`, EXACT — the average of one observation is that
  observation) limit.
- Caught, not assumed: Heston's vega (`d(price)/d(v0)`, since Heston has
  no single "volatility" input) is not simply Black-Scholes vega in
  different units, even after the chain-rule unit conversion
  (`d(price)/d(sigma) = d(price)/d(v0) * 2*sigma`). At a realistic
  mean-reversion speed (kappa=1.5) the converted value came out roughly
  half of Black-Scholes vega — a real economic effect (variance reverts
  from v0 toward theta over the option's life, damping the pure-v0
  sensitivity relative to a constant-sigma model), confirmed by
  separately testing kappa → 0, where the converted vega DOES match
  closely.
- Caught, not assumed: barrier gamma needed a ~50x larger
  finite-difference bump than Black-Scholes' usual default. The barrier
  pricer is a numerical quadrature with its own noise floor; gamma's
  central-difference formula divides by `spot_bump^2`, amplifying that
  floor by roughly 1e6 at a Black-Scholes-sized bump — measured
  directly as a 7.8% gamma error at `spot_bump=1e-3` versus 4-
  significant-figure agreement at `spot_bump=0.05`, now the module's
  default.
- Arithmetic-average Asian Greeks are explicitly NOT implemented: that
  variant's Monte Carlo pricer has no common-random-numbers machinery,
  so a naive bump-and-reprice would have unknown, likely-unreliable
  precision. `asian_greeks.py` raises rather than silently returning a
  number of unknown quality.

Plus **portfolio-level Greeks aggregation** (`prometheus.titan.portfolio_greeks`,
PR-059), the first evidence anywhere in this repository for PRI-10:

- `titan.positions` already aggregates market VALUE across a portfolio
  (RISK-01), but only for 3 instrument types, and nothing aggregated
  Greeks. Rather than redesign `Position`/`Instrument` to carry every
  pricer's own extra parameters (Heston needs `HestonParams`, Merton
  needs `MertonJumpParams`) and risk that existing, already-tested
  repricing path, this module is deliberately decoupled: it sums
  whatever quantity-scaled per-unit `Greeks` the caller supplies,
  computed via whichever of the now 6 pricer-specific Greeks functions
  actually applies.
- Demonstrated, not just claimed, to work across different pricing
  models in one portfolio: a test builds a 3-line book with one line's
  Greeks from Black-Scholes, one from Heston, one from Merton, and
  confirms the aggregate total is the correct weighted sum across all
  three — the module never inspects or special-cases which model
  produced a given `Greeks` object.
- `verify_reconciliation` independently re-derives the total from the
  lines rather than trusting it was computed correctly just because it
  came from the same function; a dedicated test constructs a
  deliberately tampered report and confirms the check actually catches
  the mismatch, not just that it returns `True` on the happy path.
- Connects to the existing `PositionBook` (reads quantities directly,
  no duplicated bookkeeping) without modifying `titan.positions` itself.

Plus the **first real, live-verified external data connector**
(`prometheus.data_ingestion`, PR-060) — World Bank Open Data:

- Every prior mention of macro data in this repository was either fully
  synthetic (`macrocore.synthetic_data`) or a schema/predicate with no
  real source behind it (`econosim.pit`). World Bank's indicator API
  needs no API key, unlike FRED/ALFRED, for which no `FRED_API_KEY` is
  configured in this environment — so this is the one source that could
  actually be exercised live before writing any production code: a full
  round trip (real HTTP fetch → JSON parse → `MacroObservation` →
  point-in-time eligibility query) was run by hand against the live API,
  confirming the response shape, pagination and missing-value convention
  all behave as documented.
- The 4 real response pages from that verification are embedded
  verbatim in the committed test suite — not hand-typed fake JSON — so
  the tests exercise the parser against data they did not invent, while
  staying fully hermetic (a scripted test double serves the captured
  pages; no committed test makes a live network call).
- Closes the ECONOSIM-X addendum's FP-02 for real: PR-055 built the
  schema (`vintage_at`, `raw_hash`, `source_license`, etc.) with no real
  dataset behind it; this connector is the first real dataset flowing
  through that schema end to end, with a real CC-BY-4.0 license, a real
  SHA256 hash of the actual fetched bytes, and a real publication date.
- Applies the lesson from the VAL-01/03/14 misattribution two PRs ago
  directly: DAT-01 (source catalog), DAT-02 (that ID is specifically
  FRED-MD/QD, a different source), DAT-06/12/13/14 (storage layers,
  normalized-data hashing, release gating, dataset cards) are all
  adjacent to this PR's subject matter but deliberately NOT claimed,
  since none of them are literally satisfied by what was actually built.
- A defensive pagination safety cap was added after noticing, while
  writing the fetch loop, that a malformed API response reporting an
  ever-larger page count could otherwise spin forever — caught by
  review before it could become a real incident.

Plus **extreme-input solver robustness** (SDE-12/VAL-13, PR-061),
closing two original-blueprint items left explicitly open since PR-057:

- An empirical probe across every VOLTERRA pricer and STOCHASTICA
  simulator, followed by a broad Hypothesis property-test file
  (`tests/property/test_extreme_input_robustness.py`) that is NOT
  seeded — re-running it against fresh random examples kept finding
  more bugs until none were left — surfaced six distinct, real,
  previously-undiscovered defects, not one or two.
- Barrier options had TWO bugs stacked on each other: a silently
  wrong-answer bug (integration bounds centered on log-return 0 instead
  of the true drift, returning `0.0` instead of matching the vanilla
  price at tiny volatility), and, once that was fixed, a SECOND,
  previously-dormant bug it exposed — `scipy.integrate.quad` is not
  automatically aware of the payoff's non-smooth kink, and its own
  reported error estimate was unreliable near it, confirmed against an
  independent Simpson's-rule ground truth on a 4-million-point grid.
- Merton jump-diffusion had a FOURTH overflow path survive the first
  three fixes: `r_0 = r - jump_intensity*k` alone can already overflow
  `exp(-r_n*maturity)` at the very first term, even when the jump
  compensator is finite and the Poisson mean is nowhere near its own
  cap — found only because the property test ranged widely rather than
  re-testing the same three known cases.
- Heston had a genuine removable 0/0 singularity (whenever `kappa ==
  rho*xi` exactly, its own `phi(-i)` identity divides zero by zero) and
  a separate long-maturity numerical instability where the TRUE
  characteristic function always satisfies `|phi(u)| <= 1` for real `u`,
  so an overflow there is a pure artifact of the formula's own
  cancellation, not an unrepresentable answer — converted to a clear,
  named rejection rather than a cryptic crash, since no closed-form
  bound on exactly which inputs trigger it was derived.
- Black-Scholes itself — the simplest, most foundational pricer — was
  not immune: a negative rate with a long maturity overflows
  `exp(-r*t)` directly, and at a nearby input the discount factor and a
  risk-neutral weight that had independently underflowed to exactly
  `0.0` combined as `inf * 0.0 == nan`, silently, with no exception at
  all. Fixed by checking the weight BEFORE ever evaluating the discount
  factor — the true contribution of a zero-probability term is
  unambiguously zero regardless of the notional's size.
- A 7th defect was found only during this PR's own final
  re-verification pass, re-running the same non-seeded property file
  after the first six fixes were already written up: GBM's own path
  simulators (`simulate_gbm_paths` and two siblings sharing the same
  `s0*exp(cumsum(...))` pattern) silently return `inf` at a large
  enough positive drift over a long enough maturity — the OPPOSITE
  direction from the pre-existing, genuinely unfixable underflow-to-
  `0.0` boundary that an earlier version of this module's own docstring
  had already documented (and had wrongly generalized into claiming
  finiteness as an unconditional guarantee). Fixed by checking each
  simulator's own output for non-finite values after simulating and
  raising a clear `ValueError`, rather than a pre-check on the
  deterministic drift alone (whether any individual random path
  actually overflows depends on the realized draws, not just the
  inputs).
- VAL-13 specifically requires NaN/Inf INJECTION as input, a genuinely
  different test from (and not assumed to be covered by) the
  extreme-but-finite inputs above. Checking directly found a real,
  separate gap: every instrument/market/parameter dataclass validates
  with ordinary comparisons like `if spot <= 0: raise`, and EVERY
  comparison involving NaN is `False` under IEEE754 — so
  `MarketSnapshot(spot=float("nan"), ...)` raised nothing at all before
  this PR, and the NaN propagated silently into every downstream
  pricing formula. `prometheus.numerics.require_finite` closes this as
  the first check in all eight pricing-input dataclasses.
- Not covered: the raw, non-dataclass-gated simulator functions
  (`simulate_gbm_paths` and siblings) still validate with the same
  NaN-blind comparison pattern and were not hardened by this PR. No
  closed-form bound was derived for Heston's long-maturity instability.
  SDE-11 (parameter-identifiability diagnostics) remains separately
  open.

Plus **parameter sensitivity/identifiability diagnostics** (SDE-11,
PR-062), closing the last item left open since PR-057:

- `volterra.identifiability` reports an elasticity (d(ln price)/d(ln
  param)) for each of Heston's 5 and Merton's 4 model parameters, via
  the same central-difference bump-and-reprice pattern the existing
  Greeks modules already use — dimensionless and comparable across
  parameters of very different units and scales, unlike a raw partial
  derivative.
- Cross-checked, not a new untested formula: Heston's v0 elasticity,
  converted back to a raw derivative, matches the pre-existing
  `heston_greeks` vega to 9+ significant figures — both differentiate
  the same pricer the same way.
- Two genuine findings, confirmed by actually computing them at several
  maturities rather than assumed from outside literature: Heston's
  kappa (mean-reversion speed) and rho (spot-variance correlation) are
  CONSISTENTLY the two least price-identifiable parameters across
  short, medium and long maturity — matching well-known calibration
  folklore, confirmed here directly; Merton's jump_mean is analogously
  its least identifiable parameter, by 9x-34x depending on maturity. An
  earlier, less careful probe compared a semi-elasticity for jump_mean
  against proper elasticities for Merton's other parameters — an
  inconsistent comparison, caught and corrected before trusting the
  "no standout weak parameter" conclusion it seemed to support.
- SDE-11's OTHER acceptance clause ("impossible values rejected") was
  already satisfied before this PR by each model's own dataclass
  validation (`kappa <= 0`, `rho` outside `[-1, 1]`, etc.), hardened
  this session against NaN/Inf injection too (PR-061).
- Not covered: no profile-likelihood sweep (the other half of "profile
  OR sensitivity" this ID's acceptance criterion allows as an
  alternative) — `volterra.calibration` only fits a single parameter
  (implied volatility), so there is no multi-parameter objective to
  profile against. No joint collinearity/condition-number diagnostic.

Plus a **golden reference-value suite and Monte Carlo confidence-
interval coverage check** (VAL-01, VAL-02, PR-063), correctly closing
two items left open since the VAL-01/03/14 misattempt several PRs ago
(VAL-03 was separately closed, correctly, by PR-057):

- `tests/unit/test_golden_reference_values.py` consolidates and extends
  scattered pre-existing evidence into an explicit, labeled "golden"
  suite: the classic S=100/K=100/r=5%/sigma=20%/T=1 Black-Scholes
  textbook call AND put values, each independently re-derived via a
  direct N(d1)/N(d2) computation in the test itself rather than calling
  this project's own `_d1_d2` helper; put-call parity as an exact
  algebraic identity; GBM's driftless martingale property
  (E[S_T] = S0 exactly at mu=0, for any sigma/T); an independently
  computed GBM terminal variance; and GBM's zero-volatility exact
  deterministic limit. Runs under this repository's existing GitHub
  Actions CI on every push/PR across 4 Python versions.
- A single Monte Carlo run landing within a few standard errors of the
  true price (already tested) cannot distinguish a correctly
  calibrated standard error from a systematically too-wide or
  too-narrow one.
  `test_confidence_interval_achieves_its_nominal_coverage_rate` runs
  `monte_carlo_price_vanilla` independently 300 times (disjoint fixed
  seeds, fully deterministic) and checks that the true closed-form
  price falls inside each run's own reported 95% interval close to 95%
  of the time (94.7% observed), sized against the analytic standard
  error of a binomial proportion rather than a magic tolerance —
  confirmed empirically first, in a pre-production probe, before
  writing the production assertion's band.
- Not covered: the coverage check runs once, for vanilla European
  options only — the Asian/control-variate Monte Carlo path shares the
  same sample-standard-error mechanism but is not separately re-tested.

Plus a **property-based metamorphic test suite** (VAL-11, PR-064):

- `tests/property/test_metamorphic_suite.py` builds one Hypothesis test
  for each of the four DIFFERENT relationships VAL-11 names, not four
  synonyms for "test more cases": scaling (portfolio Greeks aggregation
  is exactly linear in quantity), parity (Call-Put=S-K*exp(-rT) swept
  across a wide parameter range for Black-Scholes, Heston AND Merton —
  a genuine upgrade from each pricer's own existing parity tests, which
  check only a handful of hand-picked parameter sets), relabeling
  (reordering portfolio lines, or stress-test asset weights and their
  shocks together, doesn't change the total — summation is
  commutative), and zero-shock (an all-zero stress scenario produces
  exactly zero loss, for both the factor-shock and asset-shock paths in
  `titan.stress_testing`).
- Writing the Merton parity test found a 6th real, previously-untested
  crash, on top of the five SDE-12 findings above: `jump_intensity ==
  0.0` — a perfectly ORDINARY parameter `MertonJumpParams` explicitly
  permits, not an extreme one — makes `poisson_mean` exactly `0.0`, and
  the per-term pricing loop's `n=1` iteration then computes
  `math.log(0.0)`, which Python's `math.log` raises on. No existing
  test had ever called the closed-form pricer (as opposed to the
  simulator) at zero jump intensity. Fixed by collapsing the sum to its
  single `n=0` term there, confirmed to then match Black-Scholes
  EXACTLY, not approximately.

Plus an **action-feasibility invariant audit** (VAL-08, PR-065):

- Rather than write new production code, this audited every mutating
  method in `econosim.agents` first: budget/capital feasibility
  (`InsufficientFundsError`, before `Household.consume`,
  `Firm.pay_wages`, `Bank.receive_repayment`, `Government.collect_tax`
  and `Government.pay_transfer`) and leverage feasibility
  (`CreditLimitExceededError`, before `Bank.originate_loan` and
  `Government.issue_bonds` through the same code path) were already
  implemented, as named structured exceptions carrying the relevant
  amounts — never a bare `ValueError`, a silent clamp, or a no-op.
- Strengthened with a new Hypothesis property sweep
  (`tests/property/test_action_feasibility_invariants.py`) over
  randomly generated capital/leverage/spend amounts, confirming both
  the rejection AND its converse — an in-budget or at-the-cap action is
  never over-rejected either — stronger evidence than the pre-existing
  hand-picked cases in `test_agents.py` alone.
- One deliberate exception recorded explicitly, not glossed over:
  `Bank.accrue_interest` capitalizes unpaid interest directly into the
  loan balance without re-checking the leverage cap, so
  `loans_outstanding` can organically drift past `capital*max_leverage`
  through compounding alone. Not treated as a violation — passive
  interest accrual isn't a discretionary action extending new credit,
  which is specifically what `originate_loan` represents and gates.

Plus a **regime-switching market baseline** (`stochastica.regime_switching`,
SDE-06, PR-066) — a genuinely new model, not another test/documentation
PR:

- A discrete-time Markov chain with any number of regimes, each
  carrying its own drift AND volatility (generalizing the existing
  `gbm.simulate_piecewise_drift_gbm_paths`'s drift-only piecewise path
  to a stochastic, Markov-driven regime path rather than a
  caller-fixed schedule), sampling the next regime from the current
  regime's row of a transition matrix at every step.
- `RegimeSwitchingParams` enforces a genuinely row-stochastic
  transition matrix (every row sums to exactly 1.0, every entry in
  `[0, 1]`) — SDE-06's "transition probabilities valid" clause.
- `stationary_distribution` computes the regime-occupancy distribution
  generally (any number of regimes, via the eigenvector/null-space
  method, not just a 2-state closed form); `is_stationary_distribution`
  independently tests that fixed-point equation on any candidate —
  SDE-06's "stationary test available" clause, confirmed to actually
  discriminate a non-stationary candidate from a true one. Both were
  cross-checked three ways: against a 2-state closed form derived
  directly from the stationarity equation, a 2,000,000-step empirical
  long-run simulation, and the simulator's own long-run regime
  occupancy converging to the same distribution.
- Found and fixed a minor accuracy issue before trusting the
  simulator: `exp(log(s0))` is not bit-exact in float64, so the
  initial column of simulated paths was off by a few ULPs — fixed by
  assigning it directly, matching `stochastica.gbm`'s own convention.

Plus a **volatility clustering benchmark** (`stochastica.garch`, SDE-07,
PR-067) — another genuinely new model:

- GARCH(1,1) is the classical benchmark for volatility CLUSTERING
  specifically — serially correlated squared returns — a phenomenon
  none of GBM (constant volatility), Heston (variance driven by its
  own independent Brownian motion, not by past squared returns) or
  Merton exhibit by construction, the literal "where appropriate"
  qualifier in SDE-07's text.
- `GarchParams` enforces Bollerslev's (1986) stationarity condition
  `alpha + beta < 1` directly, not just non-negativity of each
  separately, since the unconditional variance is otherwise
  infinite/undefined. Calibrating these parameters to real historical
  data is deliberately not attempted — that is SDE-10's own, separate,
  still-open item.
- `volatility_clustering_diagnostics` returns a structured report
  (squared- and absolute-return autocorrelation at several lags, mean
  conditional variance, realized variance) rather than loose values —
  SDE-07's "autocorrelation and conditional variance diagnostics
  recorded" clause, literally.
- Found and fixed a real aggregation bug before trusting it: the
  underlying `autocorrelation` helper's first draft flattened a
  multi-path batch into one concatenated series before computing
  autocorrelation, which spuriously pairs the last observation of one
  path with the first of the next at every path boundary — confirmed
  to introduce a real, if small, bias via a direct comparison against
  the correctly path-aggregated value, then fixed.
- Confirmed the behavioral signature itself, not just that the code
  runs: GARCH-simulated squared returns show strongly positive
  autocorrelation (~0.17-0.21 at lags 1-5 across several runs), while
  i.i.d. Gaussian returns with the SAME unconditional variance show
  essentially none — a contrasting negative control proving the
  clustering is a genuine model property.

Plus an **out-of-sample optimization comparison** (`titan.out_of_sample`,
OPT-08, PR-068):

- `titan.rebalancing` already walks forward causally (period t's
  weights come only from a trailing window strictly before it), but
  reports a single multi-period wealth path, not an explicit
  split-sample comparison. This does the narrower, literal thing
  OPT-08 asks for: split a returns history into one TRAIN block and
  one TEST block, fit minimum-variance weights using ONLY the train
  block, then score those SAME frozen weights on both.
- The comparison exists because the two numbers are not expected to
  match, and reporting both — not only the flattering one — is the
  point. Confirmed empirically before writing any production code:
  across 300 independent trials drawn from the SAME known covariance,
  mean in-sample variance (0.00281) < the true optimal portfolio's
  variance (0.00325, computed directly, not estimated) < mean
  out-of-sample variance (0.00364). Minimum-variance optimization fits
  the ESTIMATED covariance, not the true one, so in-sample performance
  is systematically optimistic and out-of-sample performance is
  systematically pessimistic — pinned as a regression guard on trial
  averages, since any single trial is noisy enough that either side
  can win by chance.

Plus a **default/loss-allocation reconciliation audit** (ECO-10,
PR-069):

- Rather than write new production code, this audited
  `econosim.insolvency` (PR-049) first: "implement defaults and orderly
  loss allocation" is literally what `resolve_insolvency`/
  `allocate_recovery` already do (a borrower defaulting with
  insufficient cash; recovery allocated across creditors under the
  absolute priority rule — senior claims paid first, same-tier claims
  split pro rata by size, not arrival order).
- What was genuinely missing was an explicit, deliberate "claims and
  equity loss reconciliation" check stated as its own identity, rather
  than inferred from scattered per-bank capital assertions elsewhere. A
  new toy case (3 creditors across all three priority tiers, a partial
  recovery) checks that the TOTAL amount written off across every
  creditor equals EXACTLY the TOTAL equity lost by those creditors — no
  claim extinguished without a matching loss recognized somewhere, and
  vice versa.

Plus a **bid/ask spread and liquidity cost model**
(`econosim.liquidity`, LED-09, PR-070) — genuinely new functionality,
not another audit:

- Every trade in this repository's econosim ledger (`Household.consume`,
  `Firm.pay_wages`, market clearing/settlement) executes at a single
  price with no bid/ask spread at all — not because frictionless
  trading was ever a deliberate baseline, but because no spread
  concept existed to apply. `LiquidityAssumptions` adds one as a pure,
  composable quoting/cost model, deliberately NOT wired into the
  existing, already-tested ledger-posting code (the same "caller
  composes it" pattern `econosim.insolvency.allocate_recovery` already
  uses for loss allocation): a buyer pays the ASK
  (`mid*(1+spread/2)`), a seller receives the BID
  (`mid*(1-spread/2)`), and `round_trip_cost` reports the resulting
  friction in currency units.
- "No zero-cost trades unless explicit frictionless baseline" is
  enforced directly in the constructor, not left as a convention a
  caller might forget: `spread_bps == 0` requires `frictionless=True`
  to be set in the same call, and `frictionless=True` requires
  `spread_bps == 0` — a caller cannot get a zero-cost quote by
  accident.
- Demonstrated against the real, unmodified ledger, not just the pure
  quoting math in isolation: a household buying the same quantity at
  the ASK price ends up with strictly less cash than the identical
  trade at the frictionless mid price, confirmed by composing
  `LiquidityAssumptions` with `Household.consume` on two otherwise-
  identical toy economies.

Plus **trade execution/settlement event ordering**
(`econosim.trade_lifecycle`, LED-10, PR-071), a direct companion to
PR-070's liquidity model:

- Every trade this repository's econosim ledger posts today is ATOMIC
  — execution and settlement happen in the same instant, the same
  `ledger.post()` call — so there has never been a gap between "trade
  agreed" and "trade settled" for any accounting logic to accidentally
  anticipate. `TradeLedger` adds that gap explicitly, as a standalone,
  pure in-memory tracker (not wired into the real ledger, the same
  scope cut as PR-070, for the same reason): a `Trade` carries both
  `executed_at_step` and `settles_at_step`, and `net_position_as_of`
  counts only trades settled by the queried step.
- "Track execution... event order": `TradeLedger.execute` rejects a
  trade recorded earlier than the last one already recorded —
  executions must arrive in non-decreasing step order.
- "Trade accounting never anticipates later settlement states": a
  direct test executes a trade at step 5 settling at step 10, then
  checks the buyer's and seller's position at EVERY step from 5
  through 9 — not just one spot-check — confirming it contributes
  nothing to either position until step 10 exactly, even though it has
  already executed.

Plus **inventory nonnegativity enforcement** (`econosim.inventory`,
LED-03, PR-072), a third companion in the same series:

- `price_economy.py`'s own step logic already has a nonnegative-
  inventory guard, but it is a bare `ValueError` with no attributes,
  deeply nested in a complex multi-market settlement step, and
  effectively unreachable through normal price discovery (the goods
  market's own supply curve is capped at available inventory by
  construction) — confirmed, not assumed, before deciding not to force
  an artificial test through that narrow path.
- `InventoryAccount`/`InsufficientInventoryError` implement the same
  invariant as a standalone, directly testable primitive: a structured
  error carrying `available`, `requested` and `floor` (the same
  convention `InsufficientFundsError` already uses for cash), and a
  rejected withdrawal confirmed to leave the balance unchanged.
- "Unless specified financing exists" is a genuine, per-call opt-in
  (`financed=True` on that specific withdrawal), not a clause satisfied
  by never offering one — and confirmed NOT to be implicitly authorized
  just by configuring a nonzero `financing_limit` on the account; an
  un-financed over-withdrawal still rejects exactly as if no limit
  were configured.

Plus an **equity rollforward reconciliation** (`econosim.equity_rollforward`,
LED-04, PR-073), a fourth companion in the same series:

- Every agent already carries a running equity balance (`Household.
  net_worth`, `Firm.net_worth`, `Bank.capital`, `Government.net_worth`),
  updated by `Account._apply` on every posting — but nothing
  independently recomputed that balance from the transaction history
  and confirmed the two agree. `reconcile_equity_rollforward` does
  exactly that: opening balance plus every credit minus every debit
  posted to an account, compared against the account's own reported
  closing balance, through genuinely separate code paths.
- "Across all agent sectors" is checked literally: one shared toy
  economy runs a representative mix of transactions (income,
  consumption, wages, loan origination/repayment, tax, transfer,
  interest accrual) touching Household, Firm, Bank AND Government,
  then independently reconciles each of the four equity accounts
  against the same journal.
- A tampered-balance test confirms the check actually discriminates a
  wrong closing balance from a correct one, not just `True` on the
  happy path; a mid-simulation test confirms it works as a genuine
  rollforward from a non-zero opening balance, not only from zero.

Plus **Expected Shortfall backtesting/calibration diagnostics**
(`titan.risk_metrics`, RISK-09, PR-074), closing a gap flagged explicitly
back in PR-006:

- `quantile_score` — the pinball/quantile loss (Gneiting 2011), the
  strictly consistent scoring function for a VaR quantile forecast; a
  grid search against a known Gaussian reference confirmed its
  expectation is minimized exactly at the true quantile, not some other
  plausible-looking candidate. Ranks competing VaR forecasts; not a
  pass/fail gate by itself.
- `expected_shortfall_exceedance_residual_test` — the McNeil & Frey
  (2000) ES backtest, derived directly from ES's own definition
  (ES_alpha = E[loss \| loss > VaR_alpha]): the residual loss -
  es_forecast, averaged only over observations exceeding var_forecast,
  must be zero under correct calibration. A 400-trial simulation at
  nominal size 0.05 produced an observed false-positive rate of exactly
  0.05; a forecast with ES deliberately halved was flagged essentially
  every time.
- `es_unconditional_calibration_test` — an Acerbi-Szekely
  (2014)-style statistic usable even with zero VaR exceedances in a
  sample (the exceedance-residual test needs at least 2, structurally).
  Its bootstrap-standard-error-plus-normal-approximation p-value was
  confirmed, via a 1,500-trial simulation, to reproduce its nominal
  size closely (0.0953 observed vs. 0.10 nominal). A real shape bug —
  dividing the summed tail mass by one ES value, correct only for a
  constant forecast — was caught by mypy's strict `no-any-return` check
  before it reached a formal test; the fix normalizes each term by its
  own per-observation ES forecast before summing.
- Both new tests accept either a constant threshold or a per-observation
  forecast array, supporting genuine time-varying (e.g. rolling
  GARCH-based) backtesting, not only a fixed threshold.

Plus an **interbank payments and reserve settlement audit**
(ECO-11, PR-075): `econosim.interbank_market.InterbankMarket` (direct
bilateral interbank lending/repayment, moving each bank's own vault
reserves) and `econosim.central_bank_ledger.CentralBankLedger.
settle_interbank_transfer` (central-bank-mediated reserve reallocation
between banks) were already implemented and separately tested, just
never tagged against this specific ID. One new test file,
`test_eco_11_interbank_coverage.py`, states the claim explicitly in a
combined scenario exercising both mechanisms together, plus a
discriminating test that empirically confirms a claim the central-bank
module's own docstring already made but never tested directly: a
bank's central-bank settlement balance and its own vault reserves are
genuinely unreconciled instruments — moving money through one channel
leaves the other's balance completely unchanged.

Plus a **moving block bootstrap for serial dependence**
(`experiments.block_bootstrap`, EXP-09, PR-076): every bootstrap in this
repository until now resampled individual observations or paired rows,
correct only when those are exchangeable — none were valid for a
genuinely serially-dependent series. `moving_block_bootstrap` (Kunsch
1989) resamples whole contiguous blocks instead, preserving the
within-block dependence a single-observation resample destroys.
Verified on a correlated synthetic test case, matching EXP-09's own
acceptance criterion literally: against an exactly-known AR(1) ground
truth (phi=0.7, its sample mean's finite-sample variance is computable
analytically from the known covariance structure, no simulation error
of its own), the naive single-observation bootstrap's CI width came out
at only ~41% of the truth-implied width and its 95%-nominal CI covered
the true mean just 56% of the time across 150 trials — badly
miscalibrated, as expected, since it discards the positive serial
dependence that genuinely inflates the sampling variance. The block
bootstrap's width was ~85% of the truth-implied value and its coverage
87% — a large, genuine improvement, stated honestly as an improvement
rather than an exact restoration of nominal coverage (a known
limitation of the method for short, strongly correlated series,
documented rather than glossed over).

Plus **liquidity and position-capacity constraints**
(`titan.portfolio`, OPT-06, PR-077): the existing `PortfolioConstraints`
only had a uniform box bound applied identically to every asset (OPT-02)
— no way to express a genuine liquidity/participation-limit cap, e.g.
"no more than 10% of THIS asset's own average daily volume," naturally
different per asset. A new optional `max_weight_per_asset` field closes
that gap, purely additively (`None` by default, reproducing every
existing caller's behavior unchanged — confirmed by rerunning the full
pre-existing portfolio/rebalancing/out-of-sample test suites before
adding anything new). The effective bound on each asset is always the
tighter of the uniform `max_weight` and its own cap, never the looser.
Tested as a genuinely discriminating case, not a vacuous one: a
covariance matrix was chosen so the UNCONSTRAINED optimum wants over
76% in the one asset a cap then restricts to 10%, confirming the cap
actually changes the solution — and OPT-09's existing "no infeasible
solution silently labeled optimal" guarantee was re-confirmed to still
hold once a cap makes a requested target return genuinely unreachable.

Plus a **leverage and position-size constraint projection**
(`hedging.position_constraints`, HDG-07, PR-078): this closes a gap
this document itself had flagged by name back in PR-065 — VAL-08's
ledger-level feasibility checks (`InsufficientFundsError`/
`CreditLimitExceededError`) are a different mechanism from HDG-07's own
"projected feasible region" wording, which calls for an action-
projection step applied to a hedging policy's proposed trade,
independently of whatever policy produced it. `HedgePolicyMLP`'s
existing tanh squashing to [-1, 1] (HDG-04) is a fixed architectural
bound, not a configurable, economically-stated limit checked after the
fact. `project_onto_feasible_region` clips a proposed holding to the
intersection of a flat position-size cap and a leverage-implied notional
cap (capital × max_leverage, converted via the current spot price) — the
tighter of the two always binds. A 300-example Hypothesis property
sweep (mirroring VAL-08's own precedent for an "always"-worded
requirement) confirms the projected result always satisfies both
bounds, and that an already-feasible holding is never needlessly
altered. "Concentration" is deliberately not claimed — this
repository's hedging setup is single-underlying per policy, so
concentration is not an independently meaningful notion here; the
multi-asset analogue already exists in a different setting
(`titan.portfolio.PortfolioConstraints.max_weight_per_asset`, OPT-06).

Plus **GDP/inflation/credit definitions, cross-validated**
(`econosim.macro_aggregates`, ECO-15, PR-079): GDP is defined two
independent ways (expenditure = consumption spending; income = wages +
firm profit) and cross-checked against each other AND against the
firm's own ledger-derived equity change — designed from the start to
avoid being a tautology, since the ledger-derived profit and the
caller's flow-tracked profit come from genuinely separate code paths.
Confirmed on a real Household/Firm/Government `Economy` scenario, not a
hand-waved example: taxes and transfers were confirmed to leave GDP
completely unaffected even when scaled up substantially (exactly what
"transfers excluded from GDP" requires under standard national
accounting), and a deliberately dirtied period (an extra mid-period
capitalization the caller's flow totals don't know about) was confirmed
to correctly break the reconciliation rather than silently average into
profit — proof the check discriminates, not one that reports success
unconditionally by construction. Credit aggregate is the caller's own
sum of outstanding bank loans; inflation is the percentage change in a
caller-supplied price level, honestly scoped to this repository's
actual market design (no endogenous price discovery exists to infer one
from).

Plus an **automated leakage linter** (`econosim.leakage_linter`,
DAT-09, PR-080): `econosim.pit`'s existing `require_eligible`/
`build_feature_vector` already fail closed AT ACCESS TIME for a caller
that goes through them (FP-03) — but that only protects callers that
call it. This adds the complementary DETECTIVE half: a batch-audit
linter run over a LOG of (feature, data timestamp, decision time)
usage records, however they were produced, flagging every one where
data was used strictly before it existed. The `PointInTimeStore`-
integrated variant deliberately re-derives eligibility through the
store's own public `as_of` predicate rather than reading its internal
records directly — the store's own docstring states it exposes no
"give me everything regardless of date" accessor specifically so no
caller can bypass the point-in-time rule, and an audit tool earns its
answer through the same gate as everyone else. Tested to correctly
account for ingestion-lag (`asof_eligible_at`), not just raw
publication date.

Plus **immutable pricing/risk report responses**
(`service.reports`, API-05, PR-081): nothing in this repository
previously bundled a price or risk result together with a verifiable
reference to the market snapshot it was computed from.
`PricingReportResponse`/`RiskReportResponse` are frozen dataclasses
(confirmed by test to raise `FrozenInstanceError` on attempted
mutation, not merely assumed from the decorator) carrying a
`market_snapshot_id` — not an arbitrary label, but `compute_result_hash`
(the same canonical-JSON SHA256 hash `evidence.integrity`'s artifact
seals already use, reused rather than reimplemented) applied to the
`MarketSnapshot`'s own fields, confirmed deterministic for identical
snapshots and discriminating for different ones. `build_pricing_report`/
`build_risk_report` are the only intended construction path, so a
response can never carry a snapshot id that doesn't actually match the
snapshot it claims to describe.

Plus a **cross-bank transfer settlement-balance preservation audit**
(LED-08, PR-082): LED-08's requirement text is broad ("deposits, bank
reserves, and interbank settlement") but its own acceptance criterion
is narrow and literal — "cross-bank transfer preserves total settlement
balances" — and that narrower claim is already substantially satisfied
by pre-existing code (`Bank.reserves_account`, `InterbankMarket`'s
ECO-11 evidence, `CentralBankLedger.settle_interbank_transfer`). A new,
deliberately more discriminating test registers a THIRD bank not party
to either of two transfers and confirms the system-wide total of
`settlement_balance_of` across all three is unchanged — a stronger
check than summing over only the two parties that swapped funds, where
"total preserved" would be true almost trivially. The "deposits" half
of the broader requirement text remains an honestly-stated limitation:
household/firm deposit balances still aren't bank-custodied for
non-loan flows in this model.

Plus **historical GBM calibration with dated parameter versions**
(`stochastica.historical_calibration`, SDE-10, PR-083): a GARCH(1,1)
calibration attempt earlier this session was abandoned after three
different numerical-optimizer configurations each demonstrated genuine
non-robustness, exceeding this project's zero-tolerance-for-flaky-tests
standard. GBM carries no such risk — its log-returns are i.i.d. Gaussian
under the model, so the closed-form sample mean/variance formulas ARE
the exact global MLE, no iterative optimizer needed. That claim was
cross-checked, not assumed: a general-purpose numerical optimizer
(Nelder-Mead on the negative log-likelihood) matched the closed form
to within 1e-4 once its convergence tolerance was tightened — a first,
looser run did not match, a known GBM drift-identifiability fact
(the likelihood is very flat along that direction), not a bug.
`CalibrationHistory` answers "which parameter version was in effect as
of date t" by reusing — not reinventing — `econosim.pit.
PointInTimeStore`'s own point-in-time discipline, confirmed
order-independent and confirmed to correctly withhold a later
calibration until its own `calibrated_at` arrives. GARCH/regime-
switching calibration remains deliberately unimplemented.

Plus **a numerical accuracy budget per API output**
(`service.reports`, VAL-12, PR-084): `PricingReportResponse`/
`RiskReportResponse` each now carry a REQUIRED tolerance field per
numerical output (`price_tolerance`; `value_at_risk_tolerance`,
`expected_shortfall_tolerance`), matching VAL-12's own literal
acceptance criterion — "tolerance fields present and tested for
violations." There is no default: a silently-defaulted budget would not
be a deliberate declaration by whichever code computed the value, and
`__post_init__` rejects a non-positive tolerance since no computed
value could ever satisfy one. `check_pricing_tolerance`/
`check_risk_tolerance` compare a report against an independently
obtained reference and return a `ToleranceViolation` for each field
whose own budget is exceeded — VaR and ES carry separate budgets and
are checked independently. Re-verifying the full suite for this PR
surfaced a SEVENTH, unrelated SDE-12-adjacent crash via property-based
fuzzing: `barrier_options.barrier_call_or_put_price_continuous`'s
discount-factor exponent was never checked against the module's own
overflow guard, so `rate=-5.0, maturity=142.0` raised an uncaught
`OverflowError` instead of a clean `ValueError`, from two independent
code paths (the knock-out branch's own discounting, and the knock-in
vanilla-parity closed form). Fixed by folding the discount exponent
into the existing checks; re-verified against the exact failing inputs
and five more fresh-seed property-suite reruns, all passing. Not
covered: nothing in `service.application` wires these checks into a
live serving path yet, and there is no registry of per-model-version
default tolerances — every tolerance is supplied explicitly by the
caller building the report.

Plus **immutable train/validation/test regime splits**
(`experiments.holdout_manifest`, EXP-04, PR-085): `DataSplit` is a
frozen dataclass naming one contiguous date range and its regime, and
`build_holdout_manifest` assembles a set of them into a
`HoldoutManifest` whose `manifest_id` is content-addressed — the same
`compute_result_hash` utility `evidence.integrity` and `service.reports`
already reuse — so changing even one cutoff by a single day provably
changes the id, while reordering the same splits on input does not
(both confirmed by test). "Locking the cutoffs" is enforced: duplicate
split ids and any pair of overlapping date ranges are rejected (a date
must belong to at most one regime, or a boundary date would ambiguously
count as both train and validation), while a deliberate gap between
regimes — a quarantine buffer around a cutoff — is still permitted, not
an error. Not covered: no other module here actually builds a
`HoldoutManifest` for its own data yet, and nothing enforces that a
model-fitting call consults `regime_for_date` before using a date's
data — this is the general-purpose locking primitive, not yet wired
into a concrete pipeline.

Plus **a future-data negative control, isolated from the scoreboard**
(`experiments.leakage_negative_control`, EXP-05, PR-086):
`run_future_data_negative_control` scores the same model via two
caller-supplied functions — one honoring the point-in-time rule, one
deliberately handed data no real deployment could see yet — and
reports the gap. Exercised against a genuine `econosim.pit.
PointInTimeStore` scenario: a decision made before the target period's
data is published produces a large positive gap (the exact signature a
real accidental leak would also produce), while the converse case
(data already legitimately eligible) confirms no false-positive gap.
"Isolated from the scoreboard" is enforced, not asserted:
`assert_scoreboard_is_leakage_clean` is an `isinstance`-based guard
that raises if any entry in a results collection is a
`LeakageNegativeControlResult` — a diagnostic result cannot be folded
into a legitimate reported collection without explicitly bypassing it.
Not covered: no existing module here (`experiments.hedge_benchmark`,
`evidence.gate_report`, `evidence.model_card`) actually calls this
guard yet, since none of them has ever produced a diagnostic result to
begin with.

Plus **computational cost and memory benchmarking across methods**
(`experiments.cost_benchmark`, EXP-11, PR-087): `HardwareInfo` carries
`platform`, `python_version`, `gpu_available` and `gpu_driver`;
`MethodCostProfile` adds `dtype`, `walltime_seconds` and
`peak_memory_bytes` — the four fields EXP-11's own acceptance criterion
names ("hardware, GPU driver, dtype and walltime logged"). Honest about
this environment and this repository rather than fabricating a GPU
reading: this environment's own PyTorch build is CPU-only (confirmed:
`torch.cuda.is_available()` is `False`), and no GPU code exists
anywhere here (the same limitation VAL-10 already documents), so
`gpu_available=False`/`gpu_driver=None` — present and logged, not
omitted. The GPU-present branch and the torch-not-installed fallback
are both exercised by monkeypatching, since neither is reachable on
this machine's real hardware. `benchmark_method_cost` times a callable
with `time.perf_counter` and measures peak memory via the standard
library's `tracemalloc`, verified to discriminate against a real
small-vs-20M-element allocation pair; `benchmark_methods_cost` runs
several named methods and sorts by walltime — the "across methods"
half. Not covered: not yet wired into any existing pricer/simulator as
a real cross-method comparison table; `gpu_driver` reports PyTorch's
own build-time CUDA version, not an `nvidia-smi` driver string.

Plus **an explicit P/Q measure on every report** (`service.reports`,
AUD-04, PR-088): a genuine gap, not just an unevidenced-but-already-true
claim — `volterra.market.MarketSnapshot` already carries a `measure`
field (SDE-09), but it is structurally pinned to `"Q"`, so it can never
distinguish a P-measure risk computation from a Q-measure pricing one.
Before this PR, both `PricingReportResponse` and `RiskReportResponse`
were built from that same always-Q snapshot type, with nothing on the
response itself recording which measure the reported number was
actually computed under — an auditor could only infer it from the
Python class name, which would be WRONG for a legitimate risk-neutral
VaR. Fixed by adding `measure: Literal["P", "Q"]` as its own required
field (no default — `TypeError` if omitted) directly on both response
types; a discriminating test confirms a risk report's measure can
genuinely be set to `"Q"`, not silently forced to `"P"`. Not covered:
`MarketSnapshot.measure` itself remains pinned to `"Q"` only — this PR
tags the report layer, which is what AUD-04 asks for, not the snapshot.

Plus **a result inventory that retains failed experiment evidence**
(`experiments.result_inventory`, AUD-12, PR-089): `ExperimentAttempt`
records one attempt either kept (`included=True`, requires a
`metric_value`) or discarded (`included=False`, requires the OPPOSITE —
no metric value at all, so a discard can never be mistaken for a
disguised kept result); `reason` is required unconditionally either
way. Demonstrated against this repository's own real history, not a
synthetic example: `stochastica.historical_calibration`'s own
docstring already narrates that three GARCH(1,1) optimizer
configurations were each tried and abandoned for genuine non-robustness
before the GBM closed-form MLE was adopted instead — prose, previously,
not a structured, queryable entry per attempt. The test suite builds a
`ResultInventory` recording all three exclusions with their own real
reasons plus the included attempt's ACTUAL `calibration_error` from a
real `calibrate_gbm_mle` call. Not covered: `historical_calibration.py`
itself is not changed to build one of these at run time; no other
experiment-producing module here has been wired to build one either.

Plus **an agent and hedge decision audit log**
(`experiments.decision_audit_log`, AUD-05, PR-090):
`DecisionLogEntry` records who took an action, what it was, when the
state it was based on was observed, and when the decision was actually
made — deliberately domain-agnostic (a single comparable `float`
timestamp, since `econosim` agents use calendar dates while
`hedging.online.OnlineHedgeAccount` has its own discrete step clock
with no calendar mapping). Unlike most validated dataclasses here, it
does NOT reject a causally-impossible entry at construction — matching
`econosim.leakage_linter`'s own detective design: an audit log records
what happened, including a real violation. `audit_replay` is the
actual check, flagging every entry whose decision preceded its own
observation as a `CausalityViolation`. Demonstrated against two real
scenarios: a genuine `OnlineHedgeAccount` rebalancing simulation and a
genuine `Household.consume` call, each with both a clean case and a
caught violation. Not covered: neither production module is itself
changed to build one of these at call time.

Plus **risk reports recomputed from raw facts**
(`service.report_recomputation`, AUD-09, PR-091): the formulas
themselves were already documented in prose (`titan.risk_metrics`'s own
docstrings, RISK-02/RISK-04); this adds `MetricFormula` restating each
metric's formula/units/sign-convention as structured, inspectable data,
plus `recompute_risk_report_from_raw_losses`, which closes the loop —
given the raw loss array a `RiskReportResponse` was supposedly built
from, it recomputes VaR/ES independently at the report's own `alpha`
and reports any mismatch through `check_risk_tolerance` (reused from
PR-084). Confirmed against a real raw loss array: an honestly-built
report reproduces with zero violations; a report with a deliberately
tampered VaR (or ES) is caught with the exact field and error; a report
at a non-default alpha (0.99) is recomputed at its own alpha, not a
hardcoded default. Not covered: only VaR/ES is covered, not pricing
(VOLTERRA pricers are already cross-checked elsewhere, VAL-01); nothing
wires this into a live serving path.

Plus **a training provenance manifest sufficient for replay**
(`experiments.training_provenance`, AUD-03, PR-092):
`capture_training_provenance` bundles the training `config`, the
integer `seed` determining a run's RNG state, and `environment`
(reusing `runtime_provenance`) into a content-addressed manifest.
"Sufficient for replay" is demonstrated directly against a real
`hedging.deep_hedge.train_deep_hedge` run: a manifest captured from one
training call, then `train_deep_hedge` called a second time unpacking
ONLY the manifest's own stored config and seed, reproduces a
bit-identical `objective_history` — and the discriminating converse
(a different-seed manifest replays to a genuinely different result)
confirms the match isn't a tautology. Not covered: `train_deep_hedge`
itself isn't changed to build one of these at call time.

Plus **a deploy manifest any deployment can be recreated from**
(`service.deploy_manifest`, CIQ-11, PR-093): `capture_deploy_manifest`
bundles the real `service.application.ServicePolicy` an instance was
actually configured with, a `feature_flags` mapping (honestly `{}` —
this repository has no feature-flag system yet, so the field is
present and captured, not omitted), and `environment` (reusing
`runtime_provenance`). "Can be recreated" is demonstrated directly:
`recreate_service_policy` reconstructs a `ServicePolicy` from the
manifest's own stored fields, confirmed equal to the original against
a deliberately non-default configuration (all 9 fields away from
default), not just the all-defaults case that could pass trivially even
with a dropped field. Not covered: `service.application` itself isn't
changed to call this at real startup; feature flags have no real
content to capture since none exist yet.

Plus **secret scanning and a severity-gated release decision**
(`evidence.security_scan`, CIQ-05, PR-094): of the three scan types
CIQ-05 names, only secret scanning is honestly implemented — a genuine
vulnerability/dependency scan needs a live CVE database this
environment has no reliable way to query, and fabricating results
against one never actually queried would misrepresent what was
checked. `secret_scan` matches self-contained regex patterns (AWS
keys, PEM private key headers, generic credential assignments)
against caller-supplied file contents. `evaluate_release_gate` — "high/
critical findings block release unless approved" — is deliberately
scanner-agnostic, so a future real vulnerability scanner could plug
into the same gate unchanged; each finding's content-addressed
`finding_id` lets one specific finding be approved without
blanket-approving its whole category. Confirmed against synthetic
fixtures and a genuine self-check: scanning this repository's own real
`src/` tree (100+ files) today finds zero secrets. Not covered:
vulnerability/dependency scanning itself; no CI wiring.

Plus **per-series data quality monitoring**
(`econosim.data_quality`, DAT-11, PR-095): operates on a plain sequence
of `MacroObservation`s the caller already holds, deliberately not by
reading `PointInTimeStore`'s own internals (which exposes no "give me
everything" accessor, by design) — a monitoring tool gets no special
exemption from that boundary, and `all_eligible_as_of` wouldn't suffice
anyway since it collapses to only the latest vintage per key. Reports
conflicting duplicates (same key, different value — a genuine
ingestion conflict; a harmless identical re-ingestion is correctly not
flagged), revision counts, freshness (honoring the same effective-
eligibility gate `econosim.pit` itself uses), and completeness against
an expected count, with alerts firing only past a caller-supplied
threshold. Not covered: no existing ingestion pipeline calls this yet;
no dashboard surface exists.

Plus **dataset fingerprinting for normalized data and feature
transformations** (`experiments.dataset_fingerprint`, DAT-12, PR-096):
`compute_dataset_fingerprint` hashes a normalized array together with
the name of the transformation that produced it. Demonstrated against
a real transformation, not a synthetic array: raw GBM price paths
converted to log returns — two separately-computed arrays from
independent copies of the same raw prices produce the bit-identical
fingerprint, while a different transformation (simple returns), or
even the same values under a different declared transformation id,
each produce a different one. `verify_dataset_fingerprint` catches a
genuinely tiny perturbation (1e-9), confirming this is a real exact-
reproduction check. Not covered: no existing module calls this yet.

Plus **an explicit statement of capacity/quota rejection with
transparent reasons** (REL-10, PR-097, audit): already substantially
satisfied by pre-existing, separately-tested code —
`service.application.ServicePolicy`/`Admission` reject a per-owner
request-rate quota and a global rate budget with the distinct code
`"rate_limited"`; `jobs.store.QueuePolicy`'s pending-queue quota
rejects with the distinct code `"quota_exceeded"` — but no existing
test had ever stated the claim that these are genuinely DIFFERENT,
transparent reasons explicitly. One new deliberate test does: both
quota types reject with their own named code, a request within either
quota still succeeds, and the two codes are confirmed different from
each other. Not covered: no explicit capacity-reservation concept
(pre-allocated guaranteed capacity per owner) exists, only rejection
past a shared budget.

Plus **model registry states, a transition policy and a promotion
gate** (`evidence.model_registry`, MLO-08/MLO-10, PR-098):
`ModelRegistryEntry` holds exactly the five states MLO-08 names, with a
complete, append-only `history` of every `StateTransition` (actor,
timestamp, required reason). `is_allowed_transition` states the policy
as a pure function — the only forward path is candidate → evaluated →
approved → staged → retired, any non-retired state may additionally
retire directly, and every other move (skipping a state, going
backward) is rejected. `promote_to_approved` layers MLO-10's gate on
top of that same policy rather than duplicating it, additionally
requiring both a `TrainingProvenanceManifest` (reused from AUD-03) and
a passing validation result — denying promotion with the exact missing
piece named, for a missing manifest, missing validation, or failed
validation, each confirmed separately; a complete passing candidate
still can't skip the underlying state machine. Not covered: no
"rejected"/"evaluation failed" state beyond the 5 named; no
persistence layer or multi-entry registry store.

Plus **content-hashed, immutable model packages**
(`evidence.model_package`, MLO-07, PR-099): `ModelPackage` is a
lightweight, frozen record — a model/version label plus a
`content_hash` — not a container for the artifact's own bytes, the
same separation `evidence.integrity`'s checksum seals already draw.
Grounded in a real serialized artifact, not a synthetic byte string: a
`torch.save`d `state_dict` of an actual `HedgePolicyMLP`. Two separate
packaging calls on independently re-serialized copies of the same real
model state resolve to the identical hash; a genuinely different
model's trained weights resolve to a different one.
`verify_package_integrity` demonstrates "immutable approved packages"
directly — re-hashing bytes as if re-read from separate storage and
comparing against the recorded hash — catching both a single-byte
tamper and a completely different artifact. Not covered: no real
artifact store exists; not yet integrated with `model_registry`'s
`approved` transition.

Plus **controlled model rollback with stale-cache purge**
(`evidence.model_serving`, MLO-12, PR-100): `ModelServingSlot` models a
minimal real serving layer — which `ModelPackage` is currently served,
plus an inference cache keyed by `(content_hash, input_key)`, since a
prediction cached under one model version must never be served as if
from a different one. `rollback_to` restores a target package and
purges every cache entry NOT keyed to its content hash, selectively —
an entry already valid for the restored model is preserved, not
recomputed, confirmed with a call counter. Both halves of the
acceptance criterion get dedicated tests: exact restoration, and the
abandoned model's cache entry confirmed absent, not just "cache size
looks about right." Not covered: retirement itself is `model_registry`'s
job (MLO-08); no check against the registry's own state before
allowing a rollback.

Plus **early stopping that structurally forbids the test regime**
(`experiments.early_stopping`, MLO-06, PR-101): `EarlyStopper.step`
requires its caller to declare, on every call, which `HoldoutManifest`
regime (EXP-04's own vocabulary) the metric came from, raising
`NonValidationRegimeError` immediately for anything other than
`"validation"` — enforced at the single choke point every stopping
decision passes through, not a convention callers are trusted to
follow; a rejected call leaves the stopper's state unchanged.
Demonstrated against a real `HoldoutManifest`: a simulated training
loop looks up each epoch's regime from an actual calendar date via
`regime_for_date`, and a date that genuinely resolves to `"test"` is
rejected exactly as the hand-typed case would be. The patience logic
itself is separately verified, including the case that a late
improvement resets the no-improvement counter rather than just
updating the recorded best. Not covered: no existing training function
is itself changed to use this yet.

Plus **champion/challenger comparison with matched data**
(`evidence.champion_challenger`, MLO-14, PR-102):
`build_champion_challenger_report` checks that the champion genuinely
WAS approved by reading `model_registry`'s own audit trail (MLO-08),
not trusting an unchecked caller-asserted label — confirmed to still
accept a champion since moved on to `staged`, and to reject one never
approved at all. `champion_outcomes`/`challenger_outcomes` must have
identical shape ("matched data," enforced not assumed); the comparison
reuses `paired_bootstrap_difference` (PR-008); `higher_is_better` has
no default, since getting it backwards would silently invert the
conclusion. Grounded in a real comparison, not synthetic arrays: the
classic Black-Scholes delta hedge against the same hedge with a
cost-reducing no-trade band, both evaluated on identical simulated
price paths, compared on Expected Shortfall. Not covered: no
persistence/multi-champion lookup; no integration with
`model_serving`'s rollback.

Plus **restored artifacts are readable and hash-consistent**
(REL-11, PR-103, audit): already substantially satisfied by pre-existing
`recovery.snapshot`/`jobs.artifacts.ArtifactStore` (31 pre-existing
tests), but none had stated the claim explicitly. One new deliberate
test does: after a genuine backup/restore round trip, the restored
artifact is read by its own digest and this test independently
recomputes its canonical-JSON content hash and confirms it matches —
surfacing a genuine subtlety along the way (content-addressing here is
a canonical-JSON hash of the parsed body, not a raw-byte file hash; an
initial draft using raw bytes legitimately failed).

Plus **identity, approval, previous state and hash on every registry
transition** (AUD-06, PR-104): `StateTransition` already had `actor`
and `from_state` from MLO-08; this adds a required `approved_by` (no
default, and deliberately NOT enforced to differ from `actor`, since
that would need real authentication this repository doesn't have — see
CIQ-08) and `content_hash`, required specifically on `promote_to_approved`
via a new required `ModelPackage` parameter (reused from MLO-07). A
full-lifecycle test confirms all four fields appear exactly where they
should, including a genuinely different approver on the promotion step.

Plus **a real, code-derived service inventory and dependency map**
(OPS-01, PR-105): `discover_dependencies` parses every component's
actual `.py` files with `ast` rather than hand-maintaining a diagram
that can drift from the code. Run against this repository's own real
`src/prometheus` tree, it finds all 14 subpackages plus the standalone
`numerics` module, and surfaces a genuine package-level import cycle
between `stochastica` and `volterra`, confirmed directly against the
source. `owner`/`environment` are required fields with no default,
since nothing in this single-maintainer, un-deployed repo can honestly
derive either from the code.

Plus **simulation jobs benchmarked at small/medium/large scales**
(REL-03, PR-106): reuses `cost_benchmark.benchmark_method_cost`
(EXP-11), adding only a published `ScaleBudget` per scale and
`check_scale_budgets`. Grounded in a real small/medium/large GBM
benchmark — a throwaway warm-up call was found NECESSARY first
(confirmed directly: without it, the very first timed call absorbed a
one-time numpy/BLAS warm-up cost large enough to make "small" measure
slower than "medium," which would have been a flaky, misleading test).
With it, both the walltime and peak-memory curves are confirmed
strictly increasing across all three scales. Writing this module's own
test also caught a real bug: `zip(ordered, ordered[1:], strict=True)`
crashes on any input since the two operands are deliberately one
element apart in length; fixed to `strict=False`. Not covered: only
GBM is benchmarked, not the full `econosim` loop or job-queue
submission.

Plus **dataset cards distinguishing synthetic from empirical data**
(DAT-14, PR-107): `DataType` is a closed, two-value vocabulary with no
default, so a card can never be silently missing its type or lineage.
Grounded in two real cases: a genuine simulated GBM path carded
`"synthetic"`, and the same real captured World Bank API response
`test_worldbank_connector.py` exercises carded `"empirical"`, with its
lineage stating the actual license the real observation carries. Not
covered: no existing module attaches a card to its own output yet.

Plus **raw/normalized/features/artifacts storage layers with
permission and immutability boundaries** (DAT-06, PR-108): `write`
raises `ImmutableWriteError` if a key is already written (per-key, not
a blanket freeze); `read_from` enforces the four layers form a strict
pipeline where a layer may read directly only from the one immediately
upstream of it — confirmed by a discriminating test that `features`
cannot skip past `normalized` to read `raw` directly. Not covered:
in-memory only, no persisted backend; no existing pipeline routes
through these layers yet.

Plus **schema contracts with quarantine, unit normalization and
currency mapping** (DAT-10, PR-109): `validate_against_contract` never
raises on a mismatch and never silently drops the record — it returns
a `QuarantinedRecord` with the specific reason, confirmed to report a
unit mismatch and a currency mismatch distinctly, not conflated.
`normalize_unit` does exact scale conversion only (never currency
exchange-rate conversion, which would need live market data this
repository doesn't have and won't fabricate); `map_currency_code` only
normalizes spelling to ISO 4217 codes, never converts an amount.

Plus **retraining triggers with pre-registered thresholds** (MLO-13,
PR-110): `RetrainingThreshold` is frozen and `evaluate_retraining_trigger`
rejects any monitoring observation dated earlier than the threshold's
own recorded date — a threshold can never be back-dated to fit an
already-known outcome. Demonstrated against RISK-09's own
`es_unconditional_calibration_test` with real p-values: a genuinely
well-calibrated forecast (p=0.33) doesn't escalate, a genuinely
miscalibrated one (p≈3.6e-10) does.

Plus **a tamper-evident hash-chained log for access-control changes
and privileged actions** (AUD-07, PR-111): reuses the same
hash-chaining technique `jobs.store.JobStore.verify_audit_chain`
already established, generalized to any caller-supplied event since
access-control changes have no natural home in that job-specific
schema. There is deliberately no "edit" method; `verify` re-derives
every hash from scratch rather than trusting stored values. "Tamper-
evident" is proven: a direct tamper and a more sophisticated
forged-hash tamper are both caught (the forged entry no longer chains
from the preceding entry's real hash), and truncating the log changes
the verified head. Not covered: `CredentialStore` itself isn't wired
to write to this log yet; in-memory only.

Plus **a real p95 load report for the metadata API, with request mix
and concurrency** (REL-02, PR-112): `build_load_report` computes
p50/p95/p99 from real latency samples and requires `request_mix`/
`concurrency` as named fields. Grounded in a real measurement: a
genuine `ResearchService` ASGI app's `GET /v1/jobs` endpoint hit at an
actual concurrency of 8 via `asyncio.gather`, over 15 batches (120 real
requests), timed per request. "Reference hardware" is honestly this
machine; the published target (1.0s) is correspondingly generous and
confirmed stable across repeated runs. Not covered: only one endpoint;
not a deployed production reference.

Plus **a long-horizon numerical-stability and memory-leak soak test**
(REL-09, PR-113): `run_soak_test` checks every returned array for
finiteness across the whole horizon and samples traced memory at
regular intervals, reporting growth as the last sample minus the
first (not the raw baseline). Grounded in a real 60-iteration GBM
soak run (~3 KB growth against a 5 MB budget). Two discriminating
cases: a step function that deliberately retains every array is
caught exceeding the same budget by over 8x, and a single NaN injected
at one iteration out of 60 is still detected. Not covered: a 60-iteration
proxy, not a literal multi-hour production soak; no `StepHooks` loop
exercised yet.

Plus **internal service SLO/SLI definitions, closing the loop with
REL-02** (REL-01, PR-114): `ServiceLevelObjective` is structured,
testable data, with `workload_assumption`/`approved_by` required and
no default. The metadata API's SLO names the same endpoint and
workload shape (concurrency 8) REL-02's own real load test exercises,
and `slo_is_met` confirms a genuine `LoadReport` from that real test
satisfies it — not a fabricated report built to pass; it also rejects
being checked against a report for a different endpoint. Not covered:
only one SLO defined; no broader sheet or non-latency SLIs.

Plus **reproducible inference against approved reference outputs**
(MLO-11, PR-115): `InputContract` names exactly the features an
inference function expects and rejects a mismatched shape — "container"
is interpreted as reproducible inference, not a literal Docker/OCI
container, which this repository has none of and does not claim.
Grounded in a real, deterministically-seeded `HedgePolicyMLP`: reference
outputs are recorded by actually running inference once, then confirmed
reproducible on a second, independently constructed same-seed instance.
A tampered approved output is caught with the exact input and both
values. Not covered: only `HedgePolicyMLP` is demonstrated.

Plus **unambiguous dataset provenance composed from four existing
primitives** (MLO-03, PR-116): `DatasetProvenance` composes
`ModelPackage` (MLO-07), `DatasetFingerprint` (DAT-12), `InputContract`
(MLO-11) and `HoldoutManifest` (EXP-04) rather than reinventing any of
them. "Unambiguous" is enforced: `build_dataset_provenance` rejects a
feature contract naming a different model than its package, and
`training_cutoff_date` is read directly from the manifest's own
latest `"train"` split rather than a separately-typed date that could
disagree with it. Not covered: no existing training function
constructs one of these yet.

Plus **checkpoint/resume and a per-epoch learning-curve/gradient log
for deep hedge training** (MLO-04, MLO-05, PR-117): extends
`train_deep_hedge` additively — every new field has a default, so
every pre-existing caller is confirmed unaffected. Every run now
returns a `TrainingCheckpoint`; a training run split at an arbitrary
midpoint with a genuine checkpoint/resume in between reproduces the
uninterrupted run's final policy weights EXACTLY (bit-for-bit), not
merely "within tolerance," because minibatch sampling uses its own
local generator snapshotted/restored independently of the global RNG.
Every epoch also appends an `EpochRecord` (epoch/seed/objective/a real
gradient-norm diagnostic), confirmed non-trivial. Re-verifying coverage
surfaced an unrelated pre-existing gap — `_rollout`'s "put" branch had
never been tested — closed with one new cross-checked test. Not
covered: no learning-rate scheduler exists to persist; no other
training function has this capability yet.

Plus **Kenneth French factor ingestion with version tracking** (DAT-05,
PR-118): `data_ingestion.french_factors`, following the same
transport-injected, hermetic-test pattern as `data_ingestion.worldbank`.
A real round trip against the live Kenneth French Data Library was run
before any production code was written, confirming the ZIP archive's
exact structure — three free-text header lines (the second naming the
CRSP database vintage this release was built from, the version-tracking
signal this item asks for), a monthly `Mkt-RF,SMB,HML,RF` table keyed
by `YYYYMM`, and an annual table of the same four factors keyed by
`YYYY`, distinguished by the LENGTH of the leading date key rather than
a hardcoded line number. The real captured response (4,812 monthly +
396 annual observations, vintage "202609") is embedded in the test file
as a base64 string literal, kept hermetic, and every asserted row count,
date and value was read back from the parser's own output. Not covered:
only the 3-factor "Research Data Factors" file is ingested, not French's
other factor sets; like `worldbank.py`, every observation in one fetch
shares a single dataset-level `published_at` approximation.

Plus **external data source inventory and license catalog** (DAT-01,
PR-119): `data_ingestion.source_inventory`, following the same
ast-based, code-derived discovery pattern `evidence.ops_inventory`
already uses for the service inventory. Rather than a second,
hand-maintained catalog that could drift from the connectors that
actually make the request, it parses every `data_ingestion` module
with `ast` and reads each connector's OWN already-declared
`*_URL`/`*LICENSE` constants directly. Run against this repository's
real `data_ingestion` package, it finds exactly the two real
connectors (`worldbank`, `french_factors`) with their real URL and
license strings, correctly excluding `transport` and `__init__`; a
module declaring only one of a URL/license constant raises explicitly.
`approved_by`/`allowed_use` are required, caller-supplied fields with
no default, so the catalog never claims an approval it was not
deliberately told. Not covered: no real organizational approval
record backs `approved_by` yet.

Plus **a sandbox validator for untrusted uploaded dataset archives**
(SEC-08, PR-120): `data_ingestion.dataset_sandbox.validate_zip_archive`
rejects Zip Slip entry names and decompression bombs. The default 100x
compression-ratio threshold was checked, not guessed: the real Kenneth
French archive compresses ~4x (accepted), a genuine DEFLATE-compressed
50MB-of-zeros bomb built for this module's own test compresses ~1029x
(rejected). A relative path containing a harmless `".."` that
normalizes back inside the archive is confirmed NOT rejected,
distinguishing it from a real escape attempt. A 600-case Hypothesis
fuzz test over random entry names and arbitrary bytes, mirroring this
repository's `test_extreme_input_robustness.py` pattern, confirms the
validator never raises anything other than `UnsafeDatasetError`. Not
covered: Zip Slip is not actually exploitable through this
repository's current connectors today (none extract to disk); the
validator is not yet wired into them.

Plus **a restricted-data-license scan composing through the existing
release gate** (DAT-13, PR-121): extends `evidence.security_scan`
additively with `license_scan`, mirroring `secret_scan`'s exact
structure but for restricted-redistribution data vendor names
(Bloomberg Terminal, Refinitiv, FactSet, S&P Capital IQ, LSEG,
Morningstar Direct) and no-redistribution marker phrases.
`evaluate_release_gate` was already scanner-agnostic, so a real
`license_scan` finding is confirmed to block the SAME gate
`secret_scan` does, with zero new gating logic. A real self-check of
this repository's own tracked `src/` tree (excluding
`security_scan.py` itself, which must name the vendors it detects)
finds zero restricted markers today -- every source this project
actually uses is free/open. This is CI-enforced without touching any
workflow file: the new test rides the existing unconditional
`pytest -q` CI step. Not covered: a fixed denylist, not a live license
database.

Plus **job queue depth, runtime and cancellation metrics with warning/
critical thresholds** (OPS-04, PR-122): `evidence.queue_metrics`,
grounded in this repository's own real job queue
(`jobs.store.JobStore`) rather than a disconnected toy.
`compute_queue_metrics` takes the same real `Job` records
`JobStore.list_jobs` returns and reports queue depth, running count,
cancellation count, and median/p95 runtime. Confirmed against a REAL
`JobStore` lifecycle (submit/claim/cancel/finish) with a deterministic
injected clock: a queued, a running, a cancelled, and two succeeded
jobs with distinct real elapsed times (11s/21s) produce exactly the
metrics that lifecycle actually produced, not assumed values.
`classify_queue_health` is worst-of across queue depth and p95 runtime
independently, confirmed by a case where each dimension alone gives a
different severity and the worse one wins; an empty queue (`p95` is
`None`) never contributes a severity. Not covered: no real dashboard
UI, no scheduled poller.

Plus **inference throughput, latency and failure rate per endpoint and
model** (OPS-05, PR-123): `evidence.inference_metrics.run_inference_benchmark`
times any zero-argument callable over real attempts, tallying failures
by letting each attempt's own exception actually propagate. An
alternating success/failure callable gives exactly a 0.5 failure rate,
confirming the loop runs through all `n_requests` rather than stopping
at the first exception. Grounded in two genuinely different real
backends: a real trained `HedgePolicyMLP` forward pass (succeeding on
its correct input shape, failing with a real `RuntimeError` on a
malformed one) and a real ASGI HTTP call against the same
`ResearchService` endpoint REL-02 already measures, run through the
identical function. Not covered: no dashboard/visualization of trends.

Plus **data staleness and failed-ingest-count alerting** (OPS-06,
PR-124): `evidence.data_health.measure_staleness` takes a plain
`Sequence[MacroObservation]` rather than reaching into
`PointInTimeStore`, whose own docstring deliberately forbids a
"latest value regardless of date" accessor. "Failed ingest counts"
needed no new function: wrapping a real connector call in the
existing `run_inference_benchmark` already works, confirmed against a
genuinely flaky transport (HTTP 503 three times then the real captured
Kenneth French archive) giving exactly a 0.3 failure rate. The
acceptance criterion's own "alert exercise" runs for real against that
same real archive: not stale near its real latest observation, stale
far past it. Not covered: no scheduled poller; "critical" is
caller-designated.

Plus **high-severity numerical event monitoring with assigned
ownership** (OPS-07, PR-125): `evidence.numerical_event_monitor`.
`monitor_call` runs any zero-argument callable, classifying a raised
exception as a `solver_failure` event and a non-finite result as
`non_finite_result`, grounded against this repository's own real
pricers: a normal `black_scholes_price` call is clean, while
`simulate_gbm_paths` with the same extreme drift `test_gbm.py` already
confirms raises a clear error produces a genuine `solver_failure`
carrying that real message. `monitor_pricing_deviation` compares two
real prices for the same market/option -- a real 50,000-path Monte
Carlo estimate agrees with the real closed-form price within 2% (no
event), and a deliberately wrong reference price fires a genuine
event. `owner` is required with no default on every event. Not
covered: no real paging integration.

Plus **model drift, risk-metric calibration and tail-breach monitoring
with an investigation playbook** (OPS-08, PR-126): `evidence.model_monitoring`
composes three existing primitives rather than reinventing them --
`var_exception_coverage_test` (RISK-08) for tail breach, the same
`RetrainingEscalation` framing `evidence.retraining_trigger` (MLO-13)
already built on RISK-09 for calibration, and
`paired_bootstrap_difference` (the same primitive `evidence.champion_challenger`
(MLO-14) uses) for drift. Each signal is confirmed against real data:
a real well-calibrated VaR/ES does not trigger, a deliberately
miscalibrated one does, and a real delta-hedge strategy's own loss
distribution, unchanged, does not trigger drift against itself while
a real configuration change does. `build_investigation_playbook` is
the one new structure: an ordered action per fired signal, each
naming a required owner. Not covered: no real dashboard UI or paging
integration.

Plus **CPU/RAM and artifact storage utilization tracking with capacity
forecasting and budget alerts** (OPS-09, PR-127): `evidence.resource_utilization`.
GPU utilization is honestly not covered (no GPU hardware here); CPU
and RAM are measured from this real process via the standard library's
`resource` module. Artifact storage reuses a new one-line public
`ArtifactStore.usage_bytes` wrapper around that store's own existing
`_usage_bytes`, confirmed to grow by exactly the combined real size of
two genuinely different real evidence bundles put into a real store.
`forecast_capacity` fits a linear trend, confirmed against an exact
hand-computed series (10 units/day; budget 100 reached 8 days past
the last sample), with a numerical-tolerance fix so a genuinely flat
series (float noise from `numpy.polyfit`) correctly reports no
forecasted exhaustion. Not covered: no live alert-routing/paging.

Plus **actionable alert routing with a severity taxonomy** (OPS-10,
PR-128): `evidence.alert_routing` unifies the different
"ok"/"warning"/"critical" severities `queue_metrics`/
`resource_utilization`/`model_monitoring` already produce into one
canonical P0/P1/P2 taxonomy. `route_alert` ENFORCES the acceptance
criterion: it raises `UnroutedSeverityError` for an unconfigured P0 or
P1, but returns `None` (not an error) for an unconfigured P2, since
the criterion names only P0/P1. Confirmed end-to-end against three
real existing signal sources -- a genuinely overloaded real
`JobStore` queue, a real 95% utilization reading, and a real triggered
calibration signal -- each resolving to a real configured owner. Not
covered: no live dispatch (email/Slack/pager).

Plus **a severity matrix for incorrect pricing, risk and
data-integrity incidents** (DRI-01, PR-129): `evidence.severity_matrix`
reuses `alert_routing`'s own P0/P1/P2 taxonomy. `approved_by` is a
required, caller-supplied field with no default, the same reasoning
`model_registry`'s own field already uses. `SeverityMatrix.lookup`
raises `UnknownIncidentCategoryError` for any unconfigured category --
grounded against REAL incident categories (`jobs.store.ERROR_CODES`,
and a real `solver_failure` event actually produced by
`numerical_event_monitor.monitor_call`), with `"cpu_timeout"`
deliberately left out of the test matrix to confirm the raise fires
on an actual real coverage gap, not a typo. Not covered: `approved_by`
is caller-asserted, not a real sign-off.

Plus **a numerical-integrity incident runbook: isolate, invalidate,
re-evaluate** (DRI-02, PR-130): `evidence.numerical_integrity_runbook.run_numerical_integrity_runbook`
actually EXECUTES the three named steps against a real
`NumericalEvent` and the original failing callable, returning the
real timestamped timeline that execution produced. "Re-evaluate" is
grounded against two real, genuinely different outcomes: a flaky
callable that recovers (`re_evaluation_succeeded=True`), and this
repository's own real persistently-failing extreme-drift GBM guard
that still genuinely fails (`False`) -- not an assumed outcome. The
timeline is confirmed strictly chronologically ordered via a
deterministic injected clock. Not covered: only the numerical-
integrity category, not the other "top failure categories" OPS-11
names collectively.

Plus **compromised-credential and secret-rotation tabletop drill**
(DRI-03, PR-131): `evidence.credential_rotation_drill` runs a REAL
drill against `service.auth.CredentialStore`: `rotate_credential`
rewrites the credential file using the exact schema `CredentialStore`
itself validates, and `run_credential_rotation_drill` actually calls
`authenticate` with both headers. Confirmed end-to-end: the old token
works before rotation, is genuinely rejected after, and the new token
genuinely works -- with a discriminating case proving the drill isn't
rigged (run unrotated, it correctly reports the old token as still
working) and a separate test confirming rotation doesn't disturb an
unrelated principal. "Cleaned pipelines" is grounded in
`CredentialStore`'s own real re-read-on-every-call behavior, not a
separate claim. Not covered: no real external vault; manually
invoked, not scheduled.

Plus **corrupt-data and point-in-time leak response: trace, revoke,
recompute** (DRI-04, PR-132): `evidence.pit_leak_response` uses only
`PointInTimeStore`'s own sanctioned `as_of` query. Grounded against a
real two-vintage series: a run claiming it used a revision BEFORE it
was published is confirmed a genuine leak; a run using the correctly-
eligible value is confirmed clean. `trace_affected_runs` identifies
exactly the leaky run among a mixed real set. `recompute`, fed the
correct value from the finding, is confirmed to produce a genuinely
different, correct result from the leaked run's own computation --
not merely re-executed with the same bad input. Not covered: corrupt
(rather than mistimed) data is not separately demonstrated.

Plus **audit-log and model-approval-history availability throughout
failover** (DRI-11, PR-133): `evidence.failover_audit_continuity`
exercises a REAL simulated failover through the same
`create_snapshot`/`restore_snapshot` round trip REL-11 already uses.
`read_job_events`, reading a store's sqlite file read-only, confirms
a restored store's event bodies are byte-for-byte identical to the
originals -- stronger than REL-11's own "hash chain still verifies."
`serialize_registry_entry`/`restore_registry_entry` give
`ModelRegistryEntry`'s approval history (which has no persistence
layer of its own) a real round trip, replayed through `transition()`
itself so a tampered reordering is confirmed to raise
`IllegalTransitionError` rather than silently round-tripping. Not
covered: only a local snapshot/restore, not multi-region failover.

Plus **runbooks for top failure categories with simulated on-call
drills** (OPS-11, PR-134): `evidence.runbook_catalog` deliberately
covers TWO distinct categories -- held back from DRI-02 (one category
only) until this PR specifically to satisfy "top failure categories"
plural. `run_numerical_integrity_drill` wraps the existing DRI-02
runbook; `run_credential_compromise_drill` composes DRI-03's
`rotate_credential` and `run_credential_rotation_drill` into one
drill with its own real timestamped timeline. `passed` is confirmed a
real outcome in both directions: a recovering call passes, a
persistently-failing one doesn't; a correctly-verified rotation
passes, one checked against a never-provisioned token doesn't. Not
covered: only two categories catalogued so far.

Plus **confirmation that no observability vendor exports restricted
financial data, closing OPS at 100%** (OPS-12, PR-135):
`evidence.observability_vendor_review` runs two real checks.
`scan_for_observability_vendor_integration` extends `security_scan`'s
vendor-detection pattern with real APM vendor names (Datadog, New
Relic, Splunk, Sentry, Grafana Cloud, Honeycomb, LogRocket); a real
sweep of this repository's own tracked `src/` tree confirms zero
matches -- no telemetry integration exists to export data to.
`extract_event_schema_field_names` `ast`-parses `jobs.store.py`'s own
real `_event(...)` call sites for the REAL field vocabulary the only
audit-log sink writes, and `check_for_sensitive_field_names` confirms
none of those real fields is financial-value-shaped, with a
discriminating test confirming the checker genuinely flags a planted
sensitive name. **OPS reaches 100% (12/12)**, the project's 9th
complete category. Not covered: confirms no vendor TODAY, not a
continuously-enforced CI gate.

Plus **error budget actions with service ownership** (REL-12,
PR-136): `evidence.error_budget` composes REL-01's SLO/`slo_is_met`
over a WINDOW of real `LoadReport`s. An exact window (8 real passing
reports + 2 real breaching ones) gives an exact 0.2 breach rate, not
an estimate. "Triggers release freeze" is confirmed through the
EXISTING `evaluate_release_gate` (CIQ-05) DAT-13's `license_scan`
already composes through, not a new mechanism; "...or corrective
review" reuses that gate's own "unless approved" half: approving the
finding IS the corrective-review action. `owner` is required with no
default. Not covered: window is caller-supplied, not a live stream.

Plus **log/metric storage cardinality budget verification, closing
REL at 100%** (REL-08, PR-137): `evidence.cardinality_budget`
extracts distinct label-value combinations across real `Job` records.
A bounded label choice (`status`, `owner`) gives the SAME exact 30
combinations whether 50 or 5,000 real jobs are simulated -- "remains
bounded during high run volume," checked directly. The discriminating
negative case confirms the check is real: labeling by `job_id` itself
grows linearly to exactly 5,000 at that volume and genuinely blows a
fixed budget. **REL reaches 100% (12/12)**, the project's 10th
complete category. Not covered: verifies the label CHOICE, not a
live metrics backend's actual stored cardinality.

Plus **versioned analytical tables with reproducible-script and
data-hash linkage, closing AUD at 100%** (AUD-10, PR-138):
`evidence.versioned_table`. This repository has no plotting
infrastructure, so only "tables" is claimed, honestly -- not
"figures." `build_versioned_table` reuses `compute_result_hash`, the
same hashing convention this project's other manifests already use.
Grounded against a REAL script (`evidence.requirements`, the actual
script that produces `blueprint_register.json`) and REAL data (its
own per-category coverage counts): `verify_versioned_table` confirms
the recorded hashes match, with two discriminating cases confirming
the check is genuine -- tampering with the script's content is
detected, and editing the table's recorded rows after hashing is
detected too. **AUD reaches 100% (12/12)**, the project's 11th
complete category. Not covered: no figures, only tables.

Plus **RECESSIONNET: a real quantum-vs-classical recession classifier,
closing the ECONOSIM-X addendum's FP-06 and FP-20** (PR-139). This PR
does not add an original-374-item blueprint ID -- its coverage is
tracked in `CHECKLIST_STATUS.md`'s "ECONOSIM-X final-project addendum"
section only, the same convention PR-055/PR-056 used for FP-02/FP-03/
FP-04.

Built from a user-supplied "PROMETHEUS-X -- Quantum Deep Learning
Integration Blueprint" proposing an optional `QUANTUM-LAB` subsystem
with VQC challengers for this repository's own already-specified (but
until now unbuilt) RECESSIONNET subsystem. Rather than building a
disconnected quantum island, this PR builds RECESSIONNET itself (FP-06:
"produces calibrated probabilities," NOT VERIFIED before this PR) and
adds the quantum model as one of four competing architectures, exactly
matching the addendum's own E02 evaluation matrix ("Logistic/XGBoost
vs independent vs shared head").

- `prometheus.quantum` (new sibling package, not a blueprint category):
  `QuantumDeviceSpec`/`make_device`/`QuantumLayer` wrap a PennyLane
  `default.qubit` angle-embedding + `StronglyEntanglingLayers` circuit
  as a differentiable `torch.nn.Module`, confirmed via a real forward/
  backward pass with finite, nonzero gradients; an INDEPENDENT central-
  finite-difference check against autograd's own reported gradient
  (not just "no NaN"); determinism under a fixed seed; and a
  state_dict round trip that reproduces inference exactly. Requires the
  new `quantum` optional dependency group (`pennylane==0.45.1`,
  `pennylane-lightning==0.45.0`, pinned only after confirming they
  resolve cleanly against this repository's existing
  torch==2.15+cpu/numpy==2.5 pins with the full 2,281-test classical
  suite rerun unaffected). `quantum.models` adds
  `LogisticRegressionClassifier`, `ClassicalMatchedClassifier` (the
  SAME classical encoder feeding a classical substitute layer instead
  of the quantum one -- the blueprint's own required "identical
  encoder, classical head" arm) and `HybridQuantumClassifier`.
- `prometheus.recessionnet.labels`: the REAL NBER US business-cycle
  chronology (16 recessions, 1926 onward, confirmed live against
  nber.org on 2026-11-09) plus REAL announcement dates for the six
  recessions since 1980 (also confirmed live, against the NBER Dating
  Committee's own announcements page). `recession_label_as_of` is the
  point-in-time-safe counterpart to the plain retrospective label, and
  its flagship test
  (`test_as_of_does_not_leak_the_great_recession_before_it_was_announced`)
  demonstrates the leak directly: January 2008 genuinely was a
  recession month, but `recession_label_as_of` correctly reports 0
  (unknown) for an as-of date of 2008-06-01, since the NBER did not
  announce that peak until 2008-12-01 -- the same `FutureDataError`-
  style discipline `econosim.pit` already enforces for macro
  observations, applied here to a label for the first time.
- `prometheus.recessionnet.dataset`: builds point-in-time-safe trailing-
  window features from the REAL Kenneth French monthly factor series
  (DAT-05) and retrospective NBER labels, split by a strict
  chronological boundary (train < 2000, test >= 2000 -- both sides
  confirmed to contain real recessions, not an accidental single-class
  split).
- `prometheus.recessionnet.evaluation`: Brier score, ROC-AUC (exact
  Mann-Whitney U, vectorized, no new runtime dependency), a fitted
  calibration slope/intercept, and a reliability diagram -- E02's
  "AUROC, PR-AUC, Brier, reliability diagram" minus PR-AUC, explicitly
  not attempted this PR. `run_recessionnet_benchmark` trains all four
  architectures and compares the quantum model against whichever
  classical model actually won on the test set via a PAIRED bootstrap
  CI (`experiments.bootstrap.paired_bootstrap_difference`, reused, not
  reinvented), directly implementing the blueprint's own hypothesis
  framing (H0: E[L_Q - L_C] >= 0 vs H1: E[L_Q - L_C] < 0).
- **The real, honest result**: on this repository's actual 2000+
  chronological holdout, the hybrid quantum classifier's test Brier
  score (~0.156) is robustly WORSE than logistic regression's (~0.076)
  across every seed checked (0-4), with the paired bootstrap CI
  excluding zero on the "quantum is worse" side every time. Reported
  as a clear negative result for this architecture/data/budget
  combination -- not a quantum advantage, and not hidden or re-run
  until a flattering seed appeared. This matches the blueprint's own
  stated research ethos ("a negative or inconclusive result is
  valid") and RQ2 is answered: no.
- `experiments.manifest.RunManifest`'s `code_hash`/`data_hash`/
  `model_id` fields (added PR-057, never exercised by a real model
  since none existed) are now populated by this real run, closing
  FP-20 for the first time.
- Not covered: Q-MACRO, Q-STOCHASTICA, Q-VOLTERRA, Q-TITAN and Q-POLICY
  (the blueprint's other five proposed engines) are not attempted;
  PR-AUC and gradient-boosted-tree baselines are not implemented;
  multi-seed aggregation is demonstrated ad hoc (five seeds checked by
  hand above) but not wired into `run_recessionnet_benchmark` itself;
  only one (window, horizon) pair is benchmarked, not the blueprint's
  3/6/12-month horizon sweep.

Plus **a gradient-dead-zone fix to the hybrid quantum classifier's
angle embedding** (PR-141). PR-139's `HybridQuantumClassifier` scaled
its `tanh` encoder's output by pi before feeding it to
`quantum.layers.QuantumLayer`'s angle embedding. Under a single-qubit
RX(theta) rotation from |0>, the measured <Z> = cos(theta), so
d<Z>/d(theta) = -sin(theta): zero at theta = 0 and at theta = +/-pi,
and MAXIMIZED at theta = +/-pi/2. A trained `tanh` layer tends to
saturate toward its own +/-1 extremes, which under the original pi
scaling pushed most inputs toward the dead +/-pi zone rather than the
sensitive +/-pi/2 zone -- diagnosed directly from PR-139's own
calibration-slope diagnostic (~0.10, a nearly-flat predictor), not
guessed. Rescaled to pi/2.

Real result after the fix, re-run against the same real data: at the
CLI's 300-epoch default, test-set AUC improved from ~0.61 to ~0.70 and
calibration slope from ~0.10 to ~0.22, but the quantum model still
loses clearly to logistic regression (AUC ~0.86, Brier ~0.076 vs
~0.147), with the paired bootstrap CI again excluding zero on the
"quantum is worse" side. At a shorter 150-epoch budget, the same fixed
architecture is now statistically indistinguishable from its best
classical challenger (CI includes zero) rather than significantly
worse -- a genuine training-stability difference between epoch
budgets, both outcomes now locked in as their own regression tests
(`test_run_recessionnet_demo_matches_the_real_observed_result` for
150 epochs, `test_run_recessionnet_demo_matches_a_longer_run_result`
for 300) rather than one being silently left stale. The qualitative
finding is unchanged -- no quantum advantage on this task -- but it is
now a genuine comparison, not one confounded by a dead-gradient
encoding bug.

Plus **early-stopping, validation-selected model comparison for
RECESSIONNET** (PR-142), which changed that qualitative finding again
-- this time by fixing the evaluation methodology, not the model.
A diagnostic script (`diagnose_quantum_training.py`, not committed --
a one-off trace) tracked BOTH training loss and held-out test Brier/
AUC every 10 epochs out to 500, for the hybrid quantum classifier and
logistic regression, on the real RECESSIONNET data. The result: the
quantum model's (493 parameters) test Brier score bottomed out around
epoch 20-60 (~0.073, AUC ~0.865 -- competitive with or slightly better
than logistic regression's eventual plateau) and then degraded
steadily all the way to epoch 500 (~0.188, AUC ~0.67) while its OWN
training loss fell smoothly and monotonically toward zero the entire
time. That is textbook overfitting from a higher-capacity model with
no capacity control -- not a barren plateau or vanishing-gradient
pathology (training loss never stalled or oscillated) -- and it fully
explains why PR-141's fixed 300-epoch run looked clearly worse than
its own 150-epoch run: by 300 epochs, quantum (and, to a lesser
extent, the equally-sized classical MLP) had already overfit, while
25-parameter logistic regression never does in this range.

Picking a fixed, arbitrary epoch count once one candidate overfits and
another does not is not a fair comparison. The honest fix is standard
ML practice: select each model's stopping point by a VALIDATION set,
never the test set. `training.train_classifier_with_early_stopping`
trains with a `patience`-based stop, checkpointing whichever epoch
had the best validation Brier score, and restores that checkpoint
(not whatever the final epoch happened to be) before returning.
`evaluation.run_recessionnet_benchmark_with_early_stopping` wires this
into a three-way chronological split -- train-proper (pre-1988),
validation (1988-1999, which includes the real 1990-91 recession),
test (2000+, untouched until model selection is already final) --
built by calling the EXISTING `dataset.chronological_split` twice
(composition, not a new split primitive).

Real result, re-run against the same real data: at seed=0, quantum's
test Brier (~0.087) now sits close to its best classical challenger's,
`classical_matched_mlp` (~0.083) -- not the robust loss PR-139/141's
fixed-budget evaluation showed. Across the same 5 seeds checked by
hand for PR-139/141, 4 of 5 are now statistically inconclusive (the
paired bootstrap CI for quantum-minus-classical squared error includes
zero) and only 1 of 5 favors classical by a small, significant margin;
none favor quantum significantly either. **The honest final finding
for RECESSIONNET**: once evaluated fairly, this task shows neither a
significant quantum advantage nor a significant quantum disadvantage
against logistic regression or a parameter-matched classical MLP --
a materially different, more defensible conclusion than the earlier
"quantum is robustly worse," reached entirely by correcting the
evaluation methodology, not by re-running until a result looked
better. Not covered: this early-stopping path is not yet wired into
`orchestration.recessionnet_run`'s CLI, which still uses the plain
fixed-epoch benchmark; multi-seed aggregation remains ad hoc (five
seeds checked by hand, not wired into the benchmark function itself).

Plus **Q-MACRO: a hybrid quantum regressor vs. AR(3)/MLP/persistence
for h-months-ahead Mkt-RF regression** (PR-143), the user-supplied
quantum blueprint's second P0 engine and ECONOSIM-X/PROMETHEUS-X
addendum FP-05's own minimal "matched regression benchmark"
deliverable (FP-05's FULL scope -- a shared Transformer encoder across
GDP, rates and unemployment -- is NOT attempted; no real GDP/CPI/
unemployment series exist anywhere in this repository).

This repository has no real macro series beyond the Kenneth French
factors (DAT-05), so Q-MACRO's regression target here is real
market data: h-months-ahead Mkt-RF (market excess return), the
classic equity-premium-predictability regression studied extensively
in empirical asset pricing (Welch & Goyal 2008; Campbell & Thompson
2008) -- "rates" is the one FP-05 keyword this honestly touches.

- `prometheus.data_ingestion.monthly_matrix` (new): `recessionnet.
  dataset`'s private multi-series matrix builder, promoted to a
  shared, public module once `macrocore.regression_dataset` needed
  the identical logic -- a real refactor (the old private copy and
  its test import were both removed, not left as a compatibility
  shim).
- `macrocore.regression_dataset` (new): structurally mirrors
  `recessionnet.dataset.RecessionDataset` (same windowed-feature
  convention, same fixed data-independent feature scaling) plus
  `most_recent_target_values` -- the target series' own realized
  value at the decision month, needed for a persistence baseline and
  MASE's naive-error denominator, which RECESSIONNET's binary label
  had no equivalent of.
- `recessionnet.training`'s two training functions gained an optional
  `loss_fn` (default `BCEWithLogitsLoss`, every existing caller
  unaffected) and, for early stopping, an optional `output_transform`
  (default `torch.sigmoid`) -- nothing in either loop was actually
  classification-specific once those two were pulled out as
  parameters, so Q-MACRO reuses both AS-IS with `nn.MSELoss()` and an
  identity transform, rather than a second, half-related loop.
- `quantum.models.LinearRegressionModel` / `ClassicalMatchedRegressor`
  / `HybridQuantumRegressor`: zero-behavior-change subclasses of the
  RECESSIONNET classifier architectures (no `forward` pass among them
  was ever actually classification-specific -- no sigmoid is applied
  inside any of them), renamed only so a regression benchmark does
  not mislabel its own models.
- `macrocore.quantum_benchmark.run_qmacro_benchmark`: five candidates
  -- naive persistence, AR(3) (`macrocore.baselines.fit_autoregression`,
  already evidenced for FP-04) genuinely REFIT at every real test
  decision month using only history available as of that month (the
  one candidate with a true rolling-origin protocol here -- refitting
  a neural network from scratch at every origin would be
  prohibitively expensive, a real, disclosed asymmetry), linear
  regression, a parameter-matched classical MLP and the hybrid
  quantum regressor, the last three selected by validation-set early
  stopping from the start -- PR-142's methodology correction applied
  on day one, not repeated as a mistake first.
- **The real result**: AR(3), the classical MLP and the hybrid
  quantum regressor all land within a tight band (MAE ~0.034, MASE
  ~0.62), all clearly beating naive persistence (MASE ~0.89) -- real,
  modest out-of-sample equity-premium predictability, consistent with
  the empirical asset-pricing literature's own general finding -- and
  the paired bootstrap CI for quantum-vs-best-classical includes zero
  at every one of 5 seeds checked by hand. **No significant
  difference among the sophisticated candidates on this task** --
  independently reproducing RECESSIONNET's own corrected "neither
  better nor worse" finding on a genuinely different task (regression,
  not classification) and a different target series.
- `orchestration.qmacro_run`: a CLI demo mirroring
  `orchestration.recessionnet_run`'s structure and transport-injection
  pattern exactly, reusing its `load_real_ff3_observations` directly
  rather than duplicating the real fetch logic.
- Not covered: Q-STOCHASTICA, Q-VOLTERRA, Q-TITAN, Q-POLICY (the
  blueprint's remaining three engines); PR-AUC/CRPS probabilistic
  scoring; multi-seed aggregation remains ad hoc.

Plus **offline-fallback data and switching RECESSIONNET's CLI to
early stopping** (PR-144), prompted directly by the user flagging that
this is for an actual final-project demo and it has to run live.
Two real reliability gaps, both closed:

1. Both orchestration CLIs made a live network call every invocation
   with no fallback -- a venue's bad wifi or a slow Dartmouth server
   could kill a live demo outright. `french_factors.save_ff3_snapshot`/
   `load_cached_ff3_snapshot` add a committed, real snapshot
   (`data_cache/ff3_monthly_snapshot.csv`, the same real data already
   used throughout, re-saved from an actual fetch) that
   `load_real_ff3_observations_or_cached` falls back to on any
   `HttpRequestError`/`FrenchFactorsResponseError`/`OSError`. Verified
   end to end under a SIMULATED outage (a transport returning HTTP
   503): the CLI still exits 0 with a complete report, tagged
   `"data_source": "cached_snapshot_fallback"` rather than silently
   hiding which path was actually used.
2. `orchestration.recessionnet_run` had never been updated to use
   PR-142's early-stopping methodology -- a gap PR-142's own ledger
   entry explicitly disclosed. It still used the superseded fixed-
   epoch `run_recessionnet_benchmark`. Switched to
   `run_recessionnet_benchmark_with_early_stopping`, matching
   `qmacro_run`'s CLI (which already used it from the start). Real
   effect: the CLI's own wall-clock time roughly halved (~17s to
   ~7-13s across several rehearsal runs) and its result changed from
   the superseded "classical wins" finding to the already-validated
   "inconclusive" one -- confirmed live, multiple times, not asserted
   from a single lucky run.

Plus **RECESSIONNET on real Kaggle-sourced US GDP/claims/Fed-funds/M2/
NASDAQ data** (PR-145), directly answering the user's "ambil data dari
Kaggle" request with a genuinely real, independent second grounding
for the same task -- not a toy or synthetic substitute.

The user provided a working Kaggle API token; `kaggle datasets list
-s "recession"` surfaced `mikoajfish99/us-recession-and-financial-
indicators` (ODbL-1.0 licensed, 49 votes, 5,225 downloads): 20 real
FRED-sourced CSVs (GDP, Continued Claims/CCSA, Federal Funds Effective
Rate/DFF, M2/WM2NS) plus a bundled NASDAQ daily price history. This is
genuinely closer to the blueprint's own original "GDP, rates,
unemployment" framing than DAT-05's market-factor proxy, and solves a
limitation disclosed since DAT-02..04 were first scoped (no FRED API
key in this environment).

A one-off prep script (not committed; its exact logic is recorded
here) resampled each raw series to monthly, computed year-over-year
growth (GDP, claims, M2, NASDAQ; the Fed funds rate is used as a
level, already a percent), and applied a FIXED, documented
publication-lag assumption per series before re-keying each value to
the month it would actually become known (GDP +30 days, claims/M2 +7
days, Fed funds/NASDAQ +0 days) -- an honest approximation, not
fetched real vintage data, clearly labeled as such. Two independent
real-world sanity checks confirmed the pipeline before trusting it:
NASDAQ year-over-year return in October 2008 came out to -39.8% (the
real financial-crisis trough) and continued claims year-over-year
growth in April 2020 came out to +339.1% (the real COVID unemployment
spike) -- both computed from the data, not asserted.

`data_ingestion.kaggle_macro` loads the committed derived snapshot
(`data_cache/kaggle_us_macro_monthly.csv` plus a `.meta.json` sidecar
recording the exact provenance, resampling method and lag
assumptions) into `MacroObservation`s already in the same "percent
units" convention `french_factors.py` uses, so every existing
RECESSIONNET/`prometheus.quantum` primitive
(`build_recession_dataset`, `run_recessionnet_benchmark_with_early_
stopping`, the quantum/classical model classes) is reused completely
unchanged -- zero new benchmark code. The new
`orchestration.recessionnet_kaggle_run` CLI makes NO network call of
any kind (the data is already committed), making it the single most
demo-reliable entry point in this repository: it cannot fail on wifi,
on Kaggle's API, or on a slow upstream server.

Real result (seed=0, validation split 2001-01-01, test split
2008-01-01, which this choice places the GFC and COVID both inside
the test set): on this real dataset and split, `base_rate` is the
strongest classical candidate (Brier ~0.069; logistic regression
over-fits here, Brier ~0.127, despite having the best raw AUC,
~0.81 -- a real discrimination-vs-calibration tradeoff, not a bug);
the hybrid quantum classifier (Brier ~0.074) shows no statistically
significant difference against `base_rate`. The same qualitative
finding as DAT-05's grounding and Q-MACRO: no significant quantum
advantage, no significant quantum disadvantage -- now independently
reproduced on a genuinely different, real, GDP/unemployment/rate-based
dataset, not re-run until a different story appeared.

Fixed one regression this PR's own new source caused: `data_ingestion.
source_inventory`'s real-tree integration test asserted the then-
exact tuple of discovered sources; `kaggle_macro.py`'s own
`KAGGLE_SOURCE_URL`/`KAGGLE_SOURCE_LICENSE` constants are a genuinely
new real source this ast-based scanner is SUPPOSED to find, so the
test's expectation was updated to include it, not suppressed.

Plus **real US Treasury par yield curve ingestion with recorded
day-count and holiday conventions** (PR-146), the FIRST new 374-item
ID closed since PR-139 started this quantum/real-data phase -- the
user pasted a 332-entry candidate-dataset catalog and asked to keep
pushing; rather than implementing from that catalog wholesale, this PR
picks the one entry (`MON-003`/`DER-007`/`BEN-013`'s Treasury yield
curve, also DAT-04's own long-standing, specifically-scoped, unclaimed
checklist item) that is both genuinely reachable and closes a real,
previously-open gap instead of adding a third grounding for a task
PR-139/142/143/145 had already answered three times.

`home.treasury.gov` itself timed out repeatedly from this environment's
network -- confirmed by a direct `urllib` probe run before any
production code was written, not assumed. FRED's own public, no-API-
key `fredgraph.csv` export of the identical Constant Maturity Treasury
series (the same data the Federal Reserve republishes in its H.15
release) was reachable instead and used: still the Federal Reserve/
Treasury's own official release, one hop further from the primary
publisher, not a secondary reseller the way the Kaggle mirror is.
`data_ingestion.treasury_yield_curve.fetch_treasury_yield_curve` fetches
all 11 standard tenors (1mo-30yr) over a caller-given range, one real
GET per tenor, into the existing `MacroObservation` schema, with a
disclosed fixed one-day publication lag (FRED's CSV export carries no
per-observation publish timestamp of its own).

DAT-04's own acceptance wording -- "rate tenors, day count and holiday
policies recorded" -- is met literally: `treasury_market_conventions()`
returns a typed, tested `YieldCurveConventions` value (the standard CMT
day-count split: actual/360-to-bond-equivalent for tenors <= 1 year,
actual/actual semiannual bond-equivalent for 2yr-30yr notes/bonds --
the well-established fixed-income-market convention, since
`home.treasury.gov`'s own methodology page could not be re-fetched live
for the reason above). Holiday policy is DERIVED per fetch directly
from the real data (a weekday with no published value in any requested
tenor, via the existing `core.calendar.BusinessDayCalendar`) rather
than a hand-typed date list -- confirmed against three real,
independently known closures: 2006-07-04 (Independence Day), 2006-09-04
(Labor Day), and, as a genuine discriminating case, 2020-04-10 (Good
Friday, a bond-market/SIFMA holiday that is NOT a federal government
holiday -- a borrowed federal-holiday list would have gotten this one
wrong, and the derivation does not).

The three real captured response windows embedded in the test suite
double as independent real-world sanity checks, computed from the
fetched data rather than hand-asserted: the 2-year/10-year curve was
genuinely inverted on 2006-08-25 (10Y 4.79% - 2Y 4.86% = -0.07,
preceding the 2008 recession by the well-known interval), and the
3-month bill yield hit exactly 0.00% on 2020-03-25/26 (the COVID-19
emergency rate cut to the zero lower bound) -- a fourth independent
real-world event check in this phase, after the 2008 AUC/Brier
grounding, the NASDAQ Oct-2008 crash and the Apr-2020 claims spike.

With DAT-04 evidenced, DAT reaches 12/14; DAT-02 (FRED-MD/QD ingestion)
and DAT-03 (ALFRED vintage-aware retrieval) remain unimplemented and
are not claimed -- this connector ingests one specific Fed/Treasury
rate series family, not the standardized FRED-MD/QD panel or ALFRED's
per-release vintage archive. Blueprint coverage moves from 210/374 to
**211/374 (56.4%)**.

Plus **stress testing** (`prometheus.titan.stress_testing`), the first
evidence anywhere in this repository for RISK-10/OPT-11:

- `stress_scenario_loss_from_factor_shock` / `stress_scenario_loss_from_asset_shock`
  — a named shock, applied either through a factor model's betas
  (PR-027) or directly to asset returns, scored against portfolio weights
  in the same loss-positive-when-money-is-lost convention
  `titan.risk_metrics` already uses. Cross-checked against each other:
  composing a factor shock into its implied asset-level shock
  (`betas @ factor_shocks`) and applying it through the asset-shock path
  matches the factor-shock path exactly.
- `stress_scenario_factor_attribution` — splits a factor-shock scenario's
  total loss by factor; sums *exactly* to the total (the underlying dot
  product is linear, unlike variance's Euler allocation elsewhere).
- `historical_scenario_losses` — replays every row of a historical or
  simulated returns matrix as its own scenario against today's weights,
  with no built-in opinion about which period counts as a "crisis."
- `run_stress_tests` — ranks a batch of named scenarios by loss and flags
  whether the worst one exceeds an externally supplied VaR threshold, the
  classic "stress test breaches VaR" check. A full pipeline test composes
  this with PR-027's factor exposures, PR-024's shrunk covariance and
  PR-023's optimizer in one scenario — four TITAN modules together.

Plus **interbank network contagion** (`prometheus.titan.contagion`), the
first evidence anywhere in this repository for RISK-11:

- `eisenberg_noe_clearing` — the classic Eisenberg & Noe (2001) fixed-point
  clearing payment vector for a network of banks with interbank
  liabilities and limited liability: each bank pays the lesser of what it
  owes and what it actually has (external assets plus whatever its own
  debtors pay it). Validated against a fully hand-derived three-bank
  cascading-default example (exact expected payments, shortfalls and
  creditor losses, not just a plausible result) and, independently, by
  recomputing the fixed-point equation from scratch for 10 random 5-bank
  networks and confirming the reported payments satisfy it.
- A real distinction simpler contagion models miss, captured explicitly:
  a bank owed money by a defaulting counterparty but with no debt of its
  own can never show a "debtor shortfall" — `creditor_loss` is tracked
  as its own quantity precisely to catch this, confirmed in the
  three-bank example where the best-capitalized bank never defaults but
  still absorbs a full creditor loss.
- A known degeneracy is tested directly, not hidden: a pure liability
  ring with zero external assets anywhere converges to the trivial
  full-payment vector — the economically-empty "Ponzi cycle" case
  Eisenberg & Noe's own paper acknowledges, reproduced here rather than
  silently avoided.
- `network_concentration` — a Herfindahl-Hirschman concentration index of
  each bank's debtor/creditor interbank exposures (RISK-12, partial).

Plus the **econosim-to-TITAN contagion adapter**
(`prometheus.econosim.network_risk`), the first connection anywhere in
this repository between ECONOSIM-X's simulated banking system and TITAN's
systemic-risk analytics:

- `build_contagion_network` reads live `Bank`/`CentralBankLedger` ledger
  state and produces exactly the liabilities matrix and external-assets
  vector `eisenberg_noe_clearing` needs — with the central bank itself as
  one more node in the network (its reserve liabilities to banks, and the
  discount-window loans banks owe it, are genuine interbank-style
  obligations), not a bolted-on special case.
- Demonstrated with a genuine failure mode, not just a healthy baseline:
  a central bank that issues discount-window reserves with no securities
  backing them, which a bank then drains away via interbank settlement,
  is correctly shown defaulting on its own reserve liability — built from
  real ledger operations, confirmed exactly, not a synthetic matrix.
- A double-counting trap was deliberately avoided: a bank's central-bank
  settlement balance is excluded from its external assets, since it is
  already represented as the central bank's reserve-liability edge to
  that bank.
- `run_contagion_analysis` connects directly to PR-028/029's real
  `StepHooks`-driven monetary scenario: run the scenario, then clear the
  resulting live network end to end.

Plus **direct bilateral interbank lending**
(`prometheus.econosim.interbank_market.InterbankMarket`), closing the one
remaining gap the adapter above flagged — every bank<->bank edge was
exactly zero because no such instrument existed:

- `lend` / `repay` — a genuine loan directly between any two `Bank`
  agents, with per-(lender, borrower)-pair linked accounts opened lazily
  on first use, not one netted aggregate balance per bank. This matters,
  not just stylistically: a single aggregate balance could not tell a
  contagion analysis WHO a bank owes if it borrowed from several
  different banks — confirmed directly by lending from two different
  banks to the same borrower and repaying only one in full.
- A lender's own capital/`max_leverage` cap is checked against its total
  interbank exposure across every counterparty combined, independently
  of its (separate) customer/government lending capacity — a documented,
  conservative simplification, not two pools silently sharing capital.
  Confirmed with a bank that borrowed heavily from a third party (boosting
  its reserves without boosting its own capital) and was still capped by
  its own capital alone when relending.
- `network_risk.build_contagion_network` reads these genuine bilateral
  exposures directly into the liabilities matrix via an optional
  parameter.
- A real-world-relevant limitation of any partial-sample stress test is
  demonstrated from real ledger mechanics, not just asserted: a bank that
  borrows and then relends everything to a THIRD bank excluded from the
  analyzed set appears to default on its original debt, even though a
  fuller analysis including that third bank would show a covering asset
  — because the adapter can only see what the supplied bank list reveals.
- A deeper finding, documented rather than hidden: a pure interbank loan
  is by construction a symmetric asset/liability pair, so a simple
  lending chain can never by itself create a shortfall in one static
  clearing snapshot — genuine default risk always traces back to an
  asymmetric event (like the restricted-sample case above), not symmetric
  lending alone.

Plus the **orchestration CLI/evidence-export wrapper**
(`prometheus.orchestration.monetary_operations_run`) the section above
flagged as not yet done — now closed:

- `run_monetary_operations` draws its policy-rate shocks from a dedicated
  named `SeedHierarchy` stream, so the entire run (rate path, every OMO/
  discount-window/interbank decision, every resulting ledger balance) is
  fully determined by one seed. Registered with `orchestration.replay`
  under a new `"monetary_operations"` convention key, with its own
  `model_convention` check and dispatch branch — the same integration
  points every other replay-registered scenario (`economy_run.py`,
  `monetary_run.py`, ...) already has.
- A real exported evidence bundle is independently re-read from disk,
  replayed end to end by re-running the complete recipe from its recorded
  configuration alone, and confirmed to reproduce the exact same result
  hash — not merely checked for internal self-consistency.
- A tampered `model_convention` field is confirmed rejected by
  `verified_payload` before any simulation work is attempted, newly
  covering a fail-fast check this module's four pre-existing sibling
  conventions did not have a test for either.

Run `cat CHECKLIST_STATUS.md` for exactly which blueprint checklist IDs
(`ECO-*`, `LED-*`, `VAL-*`, ...) that evidence actually satisfies, and which
of their explicit acceptance conditions are *not yet* met.

## What does not exist yet

Remaining work includes general multi-firm price discovery/settlement,
inventory valuation, historical-data ingestion, neural stochastic models,
multi-agent RL, dashboards, deployment security, model lifecycle controls
and independent governance/review. Multi-creditor insolvency now exists
(LED-07; PR-049) but only resolves claims the caller has already broken
out per creditor -- it cannot discover each creditor's individual
exposure from the ledger's pooled borrower-liability account on its own.
A research-job service API now exists locally too (PR-046/047) -- see
below -- but it is single-host and not independently reviewed.
Portfolio optimization (PR-023..025) and a first central-bank balance
sheet (PR-026) are implemented locally but standalone
-- neither is wired into `StepHooks`/`Economy` or any orchestration
runner. A basic GitHub
Actions lint/type/test workflow already exists; it is not a deployment or
model-governance system.
The blueprint's own final verdict — **NO-GO for production** — stands
unchanged; nothing here moves that needle, nor is it meant to yet.

## Getting started

```bash
python3 -m pip install --require-hashes --only-binary=:all: -r requirements/bootstrap.txt
uv sync --locked --all-extras --group build
uv run --locked --all-extras pytest
uv run --locked --all-extras ruff check src tests tools
uv run --locked --all-extras mypy --strict src tools/reproducible_build.py
```

## Repository layout

```
src/prometheus/
  core/           money, ledger, business-day calendar, RNG seed hierarchy
  econosim/       household/firm/bank/government agents, Economy wiring,
                  point-in-time macro data, deterministic shocks, macro
                  time engine, policy-rate rule + CentralBank,
                  macro-financial market link, labor/goods-market clearing,
                  step-hooks orchestration for the macro step loop,
                  bounded price discovery and exact atomic market settlement
  stochastica/    GBM, correlated multi-asset GBM, Heston path simulators,
                  piecewise-drift GBM for macro-conditioned paths
  volterra/       Black-Scholes pricing, Greeks, Monte Carlo + control variate
  titan/          VaR, Expected Shortfall, drawdown, VaR-exception coverage
  hedging/        BS delta / no-trade-band baselines, self-financing
                  simulator, online accounts, CVaR-trained MLP policy (PyTorch)
  experiments/    paired bootstrap CI, reproducibility manifest, the
                  delta-vs-MLP hedge benchmark
  evidence/       model card, gate decision form, evidence bundle export
  orchestration/  demo, monthly financial/price-economy runs, benchmark/study and replay CLIs
evidence/         generated (not hand-written) artifacts, e.g. gate_report_r0.json
tests/
  unit/           one behavior per test, no randomness
  property/       Hypothesis-based invariant tests
```

This mirrors (a small slice of) the reference repository layout in section
18 of the master specification; subsystem directories named there
(`stochastica/`, `volterra/`, `titan/`, `api/`, ...) will be added as the
corresponding PRs land, not speculatively ahead of them.

## Status: Appendix C's starter roadmap is complete; the 374-item checklist is not

The blueprint is explicit that the first priority is *"not building the
Transformer... making a constrained, correctly accounted toy economy and a
trustworthy valuation/risk baseline,"* and lists PR-001 through PR-010 as
that starting sequence (Appendix C). All ten now exist, tested, in this
repository, plus thirty-eight implementation slices beyond that starting list:

| PR | Status | Scope |
|----|--------|-------|
| PR-001 Repository foundations | done | package, lint/type config, test harness |
| PR-002 Stock-flow ledger | done | double-entry journals, household/firm/bank, invariant tests |
| PR-003 Macro time engine | done | business-day calendar, seed hierarchy, point-in-time macro data, deterministic shocks |
| PR-004 Stochastic reference | done | GBM, correlated multi-asset GBM, Heston (full-truncation Euler) + numerical benchmarks |
| PR-005 Pricing reference | done | Black-Scholes, analytical + finite-difference Greeks, put-call parity, Monte Carlo + control variate |
| PR-006 Risk reference | done | historical/parametric VaR, tie-safe Expected Shortfall, drawdown, VaR-exception coverage test |
| PR-007 Deep hedge v0 | done | BS delta + no-trade-band baselines, self-financing simulator, CVaR-trained MLP policy |
| PR-008 First research benchmark | done | paired bootstrap CI, reproducibility manifest, multi-seed delta-vs-MLP comparison |
| PR-009 Macro-financial link | done | policy-rate rule, piecewise-drift GBM, macro-conditioned market simulation |
| PR-010 Evidence export | done | model card, gate decision form, one-command disclaimer-carrying bundle |
| PR-011 (beyond Appendix C) End-to-end demonstration run | done | section 16's "Minimum v0.1 demonstration script": economy -> shock -> GBM/Heston -> pricing -> hedge comparison -> P&L/CVaR -> evidence export, with invariant/valuation-tolerance/data-timing checks that can actually fail |
| PR-012 (beyond Appendix C) Government and central-bank agents | done | `Government` (tax/transfer/bonds), `CentralBank` agent wrapper, a `Borrower` protocol so bank lending/repayment is genuinely polymorphic across household and government debt |
| PR-013 (beyond Appendix C) Labor/goods-market clearing | done | quantity-based pro-rata rationing on the short side, with a structurally-proven no-double-counting property, settled onto the ledger via realized (not desired) quantities |
| PR-014 (beyond Appendix C) Generalized step-hooks orchestration | done | `MacroTimeEngine.advance_step()` gains real extension points for section 02's steps 3-7, wired end to end against four real subsystems in one test (not mocks) |
| PR-015 (beyond Appendix C) Monthly reference scenario and financing correction | implemented locally | monthly hook-driven economy/market/hedge/risk run; explicit trade/interest timing shared by NumPy, PyTorch and online accounts; full trace/hash/JSON export and failure evidence |
| PR-016 (beyond Appendix C) Reproducible benchmark and evidence replay | implemented locally | complete train/evaluate recipes, training-data and policy hashes, per-seed financial metrics, strict JSON and atomic export, runtime provenance, verified replay of monthly and benchmark bundles |
| PR-017 (beyond Appendix C) Retraining and stress study | implemented locally | complete crossed training/test/scenario design, common-path hashes, fixed-premium/volatility stress assumptions, crossed and single-axis bootstrap diagnostics, nominal Bonferroni tail allocation, economic margins and full study replay |
| PR-018 (beyond Appendix C) Exact price-discovery economy and ledger hardening | implemented locally | budget-feasible wage/goods bisection, exact physical inventory, atomic market batches and deterministic rounding, legacy settlement preflight, currency/ID/snapshot safeguards, full economy replay |
| PR-019 (beyond Appendix C) Published-data monetary feedback | implemented locally | reusable price economy, lagged inflation/output rule, explicit opening/closing-rate finance, payroll demand feedback, full coupled trace and replay |
| PR-020 (beyond Appendix C) Crossed macro-feedback hedge study | implemented locally | independent training rows/shared stochastic economy-market banks, publication/payroll/supply scenarios, variable-rate batch accounting, conditional-CVaR inference and complete replay |
| PR-021 (beyond Appendix C) Matched current-rate feature experiment | implemented locally | independently generated macro training pools, paired rate-aware/blind MLPs, differentiable variable-rate financing, optimization diagnostics, crossed two-contrast evaluation and replay |
| PR-022 (beyond Appendix C) Risk-neutral calibration | implemented locally | implied-volatility recovery from an observed option price via bracketed root-finding, with analytic no-arbitrage pre-checks and a per-strike volatility-smile fit; not yet consumed by any other subsystem in this repository |
| PR-023 (beyond Appendix C) Portfolio optimization | implemented locally | mean-variance (closed-form-verified) and scenario-CVaR (Rockafellar-Uryasev LP, grid-search-verified) portfolio optimization with box/budget/turnover constraints and explicit solver diagnostics; the first evidence anywhere in this repository for TITAN's OPT-* checklist category |
| PR-024 (beyond Appendix C) Covariance shrinkage | implemented locally | Ledoit-Wolf (2004) analytic shrinkage toward a scaled-identity target, cross-checked against scikit-learn's reference implementation (dev-only dependency) to `1e-9` across 6 sample-size regimes; demonstrated end to end to reduce true out-of-sample minimum-variance portfolio risk relative to the raw sample covariance |
| PR-025 (beyond Appendix C) Multi-period rebalancing simulator | implemented locally | connects PR-023's optimizer and PR-024's shrinkage estimator across simulated time: periodic trailing-window re-estimation, re-optimization against realized prior holdings with an optional turnover penalty, and proportional transaction costs; no-lookahead causality verified directly (perturbing future returns leaves earlier periods' weights bit-identical), not just documented |
| PR-026 (beyond Appendix C) Central-bank ledger-backed balance sheet | implemented locally | a genuine ledger-backed `CentralBankLedger` agent: open market operations, discount-window lending and interbank reserve settlement, each a balanced double-entry Transaction; the first transaction anywhere in this repository posting against two distinct agent instances sharing one `Sector` in a single call |
| PR-027 (beyond Appendix C) Factor exposure model | implemented locally | OLS factor loadings cross-checked against `numpy.linalg.lstsq` (a different algorithm) to `1e-9`, plus a portfolio variance decomposition into systematic/idiosyncratic components with an Euler marginal-contribution breakdown; a Monte Carlo recovery test confirms the estimated decomposition converges to the ground-truth one; the first evidence anywhere in this repository for RISK-07 |
| PR-028 (beyond Appendix C) Central bank wired into StepHooks | implemented locally | the first scenario to drive PR-026's `CentralBankLedger` (OMO, discount window, interbank settlement) through the real `MacroTimeEngine`/`StepHooks` event order rather than standalone calls; `Economy.add_central_bank_ledger` closes PR-026's own "not wired into `Economy`" admission; an exact reconciliation test confirms a bank's final reserve balance equals precisely the count of successfully executed transfers times the configured amount |
| PR-029 (beyond Appendix C) Monetary operations orchestration/replay | implemented locally | wraps PR-028's scenario in the same CLI/evidence-export/replay pattern every other `StepHooks` scenario uses; a real exported bundle is independently re-read, replayed end to end and confirmed to match its recorded hash; a tampered `model_convention` field is confirmed rejected before any simulation work runs |
| PR-030 (beyond Appendix C) Stress testing | implemented locally | named factor-based and asset-based stress scenarios scored against portfolio weights, ranked and compared against an externally supplied VaR threshold; an exact per-factor loss attribution; a full pipeline test composes factor-model exposures, shrunk covariance and the portfolio optimizer before stress-testing the result; the first evidence anywhere in this repository for RISK-10/OPT-11 |
| PR-031 (beyond Appendix C) Interbank network contagion | implemented locally | Eisenberg & Noe's (2001) fixed-point clearing payment vector for a network of banks with interbank liabilities and limited liability; a hand-derived three-bank cascading-default worked example matches exactly; 10 random networks independently re-verified as genuine fixed points; the first evidence anywhere in this repository for RISK-11 |
| PR-032 (beyond Appendix C) Econosim-to-TITAN contagion adapter | implemented locally | the first connection anywhere in this repository between ECONOSIM-X's simulated banking system and TITAN's systemic-risk analytics; builds PR-031's clearing inputs from live `Bank`/`CentralBankLedger` ledger state, with the central bank itself as a network node; demonstrates a real central bank defaulting on its reserve liabilities when undercapitalized, built from actual ledger operations, not a synthetic matrix |
| PR-033 (beyond Appendix C) Direct bilateral interbank lending | implemented locally | a genuine bank-to-bank lending instrument with per-pair linked accounts (not a netted aggregate), feeding real bank<->bank edges into PR-032's contagion network; demonstrates, from real ledger mechanics, how a partial-sample stress test can miss a bank's true resources when its counterparty falls outside the analyzed set |
| PR-034 (beyond Appendix C) Continuous systemic-risk monitoring in StepHooks | implemented locally | a direct interbank loan and a periodic live `run_contagion_analysis` check wired directly into PR-028's real `StepHooks` scenario; a genuine default is engineered inside a running process and confirmed detected by the scenario's own wired-in check; caught and fixed a real bug of its own making (an unguarded capacity-constrained operation that could have crashed a step) before evidencing the feature as done |
| PR-035 (beyond Appendix C) Position book with snapshot linkage | implemented locally | the first position book anywhere in this repository: positions are tied to the exact `MarketSnapshot` they were entered against, with two independently tested flavors of stale-snapshot rejection; a full pipeline test marks a position to 200 simulated days and feeds the resulting P&L series directly into PR-006's `historical_var`, composing VOLTERRA pricing with TITAN risk analytics for the first time; the first evidence anywhere in this repository for RISK-01/RISK-13 |
| PR-036 (beyond Appendix C) Risk circuit breaker | implemented locally | PR-034's periodic contagion check now ACTS on a detected default: a one-way breaker suspends new discount-window/interbank lending for the rest of the run while existing debt keeps amortizing normally; the freeze decision is causal by construction, consulted only at the start of the step after the one that detected it |
| PR-037 (beyond Appendix C) Forward contracts | implemented locally | a second instrument type, priced by cost of carry and cross-checked against an independently-derivable equivalent formula; the position book (PR-035) generalizes to mixed option/forward books in one call, with the instrument's TYPE itself checked on reprice, not only its identifying terms |
| PR-038 (beyond Appendix C) American options via binomial tree | implemented locally | the first non-closed-form pricing method in this repository: a Cox-Ross-Rubinstein tree, with the same tree (early exercise on/off) used to converge to Black-Scholes and to verify two classical early-exercise theorems (American call = European call without dividends; American put strictly pricier) as equalities/inequalities, not approximate checks |
| PR-039 (beyond Appendix C) American options in the position book | implemented locally | the position book now spans three instrument types sharing one API; an optional `n_steps` is required only when valuing an American option, purely additive to every existing caller; even with identical strike/type, an American and European option are confirmed to be different instrument TYPES that cannot be repriced as each other |
| PR-040 (beyond Appendix C) Greeks for American options | implemented locally | delta/gamma read directly from one binomial tree's own nodes (the standard CRR technique), not by rebuilding the tree at a bumped spot — a real pitfall caught and demonstrated directly: naive central-difference gamma on a rebuilt tree is off by more than 10x even with a "reasonable" bump, because the tree price is piecewise-linear, not smooth; all five Greeks confirmed converging to the closed-form Black-Scholes Greeks in the no-dividend degenerate case |
| PR-041 (beyond Appendix C) Unifying the central bank | implemented locally | `CentralBankLedger` can now optionally track the policy rate too, via the exact same `PolicyRateRule` the standalone wrapper uses — confirmed bit-for-bit identical across 12 steps including a shocked one; a purely additive change, neither existing class is retired or broken; surfaced and documented a genuine pre-existing limitation (a bank can register with only one `CentralBankLedger` per ledger) along the way |
| PR-042 (beyond Appendix C) Migrate monetary_operations to the unified central bank | implemented locally | the real `StepHooks` scenario from PR-028 is migrated off its original two-object split onto PR-041's unified `CentralBankLedger`; the full CLI/evidence-export/replay round trip and a seeded/shocked scenario's qualitative behavior were both re-verified unchanged after the migration, not merely assumed from the diff |
| PR-043 (beyond Appendix C) Interest accrual and loan write-off | implemented locally | `Bank.accrue_interest`/`write_off_loan`, additive to the committed `originate_loan`/`receive_repayment` pair; hand-verified compound accrual over three periods and an exact loss/forgiveness equity reallocation on write-off; validated against the specific borrower's own balance, not the bank's pooled aggregate — the first evidence anywhere in this repository for LED-05/LED-06 |
| PR-044 (beyond Appendix C) Empirical macro/market-mixture tail risk | implemented locally | retraining-specific mixture CVaR, paired training/macro/market nested bootstrap, retained terminal-loss provenance, strict numeric failure handling and full replay |
| PR-045 (beyond Appendix C) Artifact integrity and full-scope traceability | implemented locally | whole-artifact seals, metadata/model fingerprint binding, offline strict audit, explicit legacy mode and complete 374-item requirement register |
| PR-046 (beyond Appendix C) Bounded durable research jobs | implemented locally | common typed recipe/admission registry, transactional idempotent local queue, fenced Linux process workers, recovery/cancellation/timeouts, quota-controlled content-addressed artifacts and trace/audit projection |
| PR-047 (beyond Appendix C) Authenticated research-job API and typed SDK | implemented locally | versioned ASGI routes/OpenAPI, private hashed service credentials, owner-derived scopes, bounded HTTP admission, diagnostic/trace correlation, readiness and real-socket SDK/worker integration |
| PR-048 (beyond Appendix C) Locked builds and encrypted local recovery | implemented locally | hash-locked CPU/build/tool profiles, independently rebuilt wheel checks, dependency SBOM, consistent encrypted SQLite/object snapshots, authenticated no-clobber restore and copied-lease fencing |
| PR-049 (beyond Appendix C) Multi-creditor insolvency waterfall | implemented locally | the full LED-07 gap PR-043 left open: absolute-priority-rule allocation across creditor tiers, largest-remainder pro-rata apportionment within a short tier (exact, no minor-unit drift, verified against 500 random claim sets), applied through the existing `receive_repayment`/`write_off_loan` calls rather than a new posting pattern; fails closed before posting anything if the supplied claims do not exactly partition the borrower's recorded debt |
| PR-050 (beyond Appendix C) Factor-model covariance shrinkage target | implemented locally | generalizes PR-024's Ledoit-Wolf shrinkage from "toward scaled identity only" to "toward any fixed target," independently re-derived and confirmed to reproduce PR-024's own implementation exactly at that special case; a new `factor_model_implied_covariance` promotes a previously test-only formula into a reusable factor-structure target; demonstrated, not just asserted, to lower both estimation error and true out-of-sample minimum-variance portfolio risk versus the identity target when the true covariance really is factor-structured |
| PR-051 (beyond Appendix C) Heston characteristic-function option pricer | implemented locally | the first stochastic-volatility PRICER in VOLTERRA's ladder (every earlier pricer was GBM/deterministic-volatility), using the branch-stable "little trap" characteristic function (Albrecher, Mayer, Schoutens & Tistaert 2007) rather than the original 1993 formulation's documented branch-cut bug; cross-checked against two exact algebraic identities on the characteristic function itself, an independently re-derived put-call-parity check, the Black-Scholes degenerate limit, and Monte Carlo agreement with the pre-existing, independently-written `stochastica.heston` path simulator; the first evidence anywhere in this repository for PRI-04 |
| PR-052 (beyond Appendix C) Merton jump-diffusion model and closed-form pricer | implemented locally | a second non-GBM model (SDE-08) with an exact, non-Euler per-step jump allocation, plus its matching closed-form European option price; caught a real, easy-to-make derivation error before it reached production code (the Poisson sum must be weighted by the risk-neutral-adjusted intensity, not the physical one the simulator itself uses) by deriving the formula independently and cross-checking both candidates against high-path-count Monte Carlo; the first evidence anywhere in this repository for SDE-08 |
| PR-053 (beyond Appendix C) Single-barrier options with discretization correction | implemented locally | a reflection-principle barrier option pricer derived from scratch (not transcribed from a reference formula table), plus the Broadie-Glasserman-Kou (1997) continuity correction for discretely- rather than continuously-monitored barriers; verified against a from-scratch Brownian-bridge continuity-corrected Monte Carlo (an initial naive discrete-grid Monte Carlo showed a small but real discretization bias of its own, caught and fixed on the test side before being mistaken for a production bug), in-out parity, and degenerate limits; the first evidence anywhere in this repository for PRI-08 |
| PR-054 (beyond Appendix C) Asian options with a Kemna-Vorst control variate | implemented locally | an exact closed form for geometric-average Asian options (a geometric average of GBM log-prices is itself Gaussian), used as a Kemna & Vorst (1990) control variate for the arithmetic-average variant, which has no closed form; cut Monte Carlo standard error by roughly 20-30x versus plain simulation at the tested settings; the covariance identity behind the closed form was independently re-derived by brute-force double summation rather than assumed, and an AM-GM model-free sanity floor (arithmetic price >= geometric price on every path) was tested directly; the first evidence anywhere in this repository for PRI-09 |
| PR-055 (ECONOSIM-X/PROMETHEUS-X addendum, FP-02/FP-03) Point-in-time schema and no-future-data fixture | implemented locally | extends the pre-existing `econosim.pit` module (not a new parallel one, confirmed by research before writing code) with the full point-in-time provenance schema (licenses, raw hashes, vintage dates) and a `FutureDataError`-raising fixture that fails closed on an entire feature-vector request rather than returning partial data; closes a real latent leakage gap by adding an internal-ingestion-lag gate (`asof_eligible_at`) alongside the source's own `published_at`, proven backward-compatible by rerunning all five pre-existing dependent tests unchanged; the first PR tracked against the new FP-01..FP-24 addendum checklist |
| PR-056 (ECONOSIM-X/PROMETHEUS-X addendum, FP-04) Classical forecasting baselines and rolling-origin backtest | implemented locally | `prometheus.macrocore`: deterministic OLS-fit Persistence/AR(p)/VAR(p) baselines with closed-form Gaussian multi-step forecast intervals, backtested end-to-end through `econosim.pit`'s point-in-time store (not a bare array) on a clearly-labeled synthetic macro panel; the AR(p)/VAR(p) forecast-variance formulas and the closed-form Gaussian CRPS score were each verified against independent Monte Carlo before being trusted in production code, then re-verified via a second from-scratch computation in the test suite itself; the first evidence anywhere in this repository for FP-04, and the required baseline MACROCORE's eventual Transformer encoder must beat |
| PR-057 (addendum-checklist accuracy audit) Heston weak-convergence study plus 3 small gap closures | implemented locally | a skeptical, literal re-audit of six "PARTIAL (pre-existing)" addendum rows found two were over-credited (FP-12 falsely implied Greeks for all 5 VOLTERRA pricers when only 2 have them; FP-16 falsely implied TITAN reports carry horizon/units/cost when none do) and corrected both rather than leaving them overstated; two others were upgraded to fully verified on their existing evidence (FP-09, FP-14); `stochastica.convergence.heston_weak_convergence_study` adds the first evidence anywhere in this repository for SDE-05/VAL-03 (a genuine match this time, unlike an earlier misattribution), with its own convergence-order estimator independently verified against two synthetic cases of exactly known order; a near-miss during that verification (a naive first draft drove system memory to 26GB/31GB used before being caught and rewritten batched) directly shaped the production function's memory-safe design; small test-only additions close the remaining FP-11/FP-20 gaps honestly (a jump-diffusion positivity test; optional `code_hash`/`data_hash`/`model_id` fields on `RunManifest`) |
| PR-058 (closes the FP-12 gap PR-057's audit found) Greeks for Heston, Merton, barrier and geometric Asian | implemented locally | 4 new finite-difference Greeks modules, each cross-checked against Black-Scholes' own analytical Greeks in a degenerate (or, for Asian at n_fixings=1, EXACT) limit; caught two genuine, non-obvious findings before trusting the result: Heston's vega (d/dv0) is NOT Black-Scholes vega in different units even after the chain-rule unit conversion -- it is further damped by mean reversion (kappa>0) pulling variance back toward theta over the option's life, confirmed by checking the unconverted and kappa->0 cases separately; barrier gamma needed a ~50x larger finite-difference bump than Black-Scholes' default because `barrier_option_price`'s quadrature noise floor gets amplified by 1/bump^2, confirmed by measuring a 7.8% error at the small bump versus 4-significant-figure agreement at the larger one; arithmetic-average Asian Greeks are explicitly NOT implemented (the Monte Carlo pricer has no common-random-numbers machinery, so bump-and-reprice would have unknown precision) -- `asian_greeks.py` raises rather than silently returning an unreliable number |
| PR-059 (builds directly on PR-058) Portfolio-level Greeks aggregation | implemented locally | `titan.portfolio_greeks`: aggregates quantity-scaled per-unit Greeks across any mix of pricers (demonstrated with a real 3-line portfolio combining Black-Scholes, Heston and Merton Greeks in one aggregate total, which the module never special-cases); `verify_reconciliation` independently re-derives the total from its lines, and a dedicated test confirms it actually catches a deliberately tampered total rather than just passing on the happy path; connects to the existing `titan.positions.PositionBook` for quantities without modifying that module, since its `Instrument` union doesn't cover Heston/Merton/barrier/Asian contracts; the first evidence anywhere in this repository for PRI-10 |
| PR-060 (first real external data source) World Bank Open Data connector | implemented locally | `data_ingestion.worldbank` + a pluggable `transport` abstraction: the first external macroeconomic data source in this repository actually exercised against a real, live API (needs no API key, unlike FRED/ALFRED, for which no key is configured in this environment); a full round trip (fetch -> parse -> `MacroObservation` -> point-in-time eligibility query) was run by hand against the live API before any production code was written, and the 4 real response pages from that run are embedded verbatim in the committed (hermetic, no-live-network) test suite; closes FP-02 for real (a real license, real raw hash, real published_at, not just the schema PR-055 built); strengthens DAT-07 and narrowly closes one specific clause of DAT-08 (skips rather than fabricates missing values); explicitly does NOT claim DAT-01/02/06/12/13/14 despite adjacency, applying the lesson from the VAL-01/03/14 misattempt two PRs ago |
| PR-061 (closes two items left open since PR-057) Extreme-input solver robustness (SDE-12, VAL-13) | implemented locally | an empirical probe plus a non-seeded Hypothesis property-test file (`tests/property/test_extreme_input_robustness.py`) across every VOLTERRA pricer and STOCHASTICA simulator found 7 distinct, real, previously-undiscovered defects (the 7th found only during this PR's own final re-verification pass, after an earlier `stochastica.gbm` docstring already claimed finiteness unconditionally): 2 stacked barrier-option bugs (a wrong-answer integration-centering bug, and a dormant quadrature-kink bug it exposed, confirmed against an independent Simpson's-rule ground truth), a 4th independent Merton overflow path surviving 3 prior fixes, a genuine Heston removable 0/0 singularity (`kappa == rho*xi`) plus a separate long-maturity numerical instability (converted to a clear rejection since the true characteristic function always satisfies \|phi(u)\|<=1, so the overflow is a pure artifact, not an unrepresentable answer), a silent `inf*0.0==nan` in Black-Scholes itself, and a silent `inf` from GBM's own path simulators at a large positive drift (the OPPOSITE direction from the pre-existing, genuinely unfixable underflow-to-0.0 boundary); VAL-13 additionally required actual NaN/Inf injection (not just extreme-but-finite inputs), which found that every pricing dataclass's `if x <= 0: raise`-style validation silently admits NaN (every NaN comparison is False) -- closed by `prometheus.numerics.require_finite`, the first check in all 8 pricing-input dataclasses |
| PR-062 (closes the last item from PR-057's open note) Parameter sensitivity/identifiability diagnostics (SDE-11) | implemented locally | `volterra.identifiability`: elasticity (d(ln price)/d(ln param)) for Heston's 5 and Merton's 4 model parameters, via the same bump-and-reprice pattern as the existing Greeks modules; cross-checked against the pre-existing `heston_greeks` vega to 9+ significant figures; two genuine, data-driven findings confirmed by computation, not assumed from literature: Heston's kappa and rho are consistently the two least price-identifiable parameters across short/medium/long maturity (matching, and here directly confirming, well-known calibration folklore), and Merton's jump_mean is analogously the least identifiable of its four parameters by 9x-34x; "impossible values rejected" (SDE-11's other acceptance clause) was already satisfied by pre-existing dataclass validation, hardened by PR-061's `require_finite` |
| PR-063 (correctly closes two items from the VAL-01/03/14 misattempt) Golden reference-value suite and MC confidence-interval coverage (VAL-01, VAL-02) | implemented locally | `test_golden_reference_values.py`: the classic Black-Scholes textbook call/put values (each independently re-derived via a direct N(d1)/N(d2) computation, not calling this project's own `_d1_d2` helper), put-call parity as an exact algebraic identity, GBM's driftless martingale property, and GBM's zero-volatility exact deterministic limit, run on every push/PR by the existing GitHub Actions CI; `test_confidence_interval_achieves_its_nominal_coverage_rate`: 300 independent, fully deterministic repeats of `monte_carlo_price_vanilla` confirm the reported 95% confidence interval actually contains the true closed-form price close to 95% of the time (94.7% observed), not just that one run lands within a few standard errors -- a genuinely different, stronger claim about whether the standard error is correctly CALIBRATED |
| PR-064 (new ID) Property-based metamorphic test suite (VAL-11) | implemented locally | `tests/property/test_metamorphic_suite.py`: scaling (portfolio Greeks aggregation is linear in quantity), parity (Call-Put=S-K*exp(-rT) swept across a wide parameter range for Black-Scholes, Heston AND Merton, not just hand-picked cases), relabeling (reordering portfolio lines or stress-test asset weights doesn't change the total) and zero-shock (an all-zero stress scenario produces exactly zero loss) -- 8 Hypothesis tests, one per named relationship; writing the Merton parity test found and fixed a 6th real crash (jump_intensity=0.0, a perfectly ordinary parameter, not an edge case, made `math.log(0.0)` raise inside the per-term loop -- no existing test had ever exercised the closed-form pricer, as opposed to the simulator, at zero jump intensity) |
| PR-065 (new ID) Action-feasibility invariant audit (VAL-08) | implemented locally | an audit of every mutating method in `econosim.agents` (not new production code) confirmed budget/capital (`InsufficientFundsError`) and leverage (`CreditLimitExceededError`) feasibility checks already exist, as named structured exceptions, before every balance-debiting or credit-extending action; strengthened with a new Hypothesis property sweep (`tests/property/test_action_feasibility_invariants.py`) over randomly generated capital/leverage/spend amounts confirming both the rejection and its converse (an in-budget action is never over-rejected); one deliberate exception recorded explicitly rather than glossed over: `accrue_interest` doesn't re-check the leverage cap, since passive interest accrual isn't a discretionary credit-extension action |
| PR-066 (new ID, genuinely new model) Regime-switching market baseline (SDE-06) | implemented locally | `stochastica.regime_switching`: a discrete-time Markov-chain regime-switching price process (each regime with its own drift AND volatility, generalizing the existing drift-only piecewise GBM) alongside GBM/Heston/Merton; `RegimeSwitchingParams` enforces a genuine row-stochastic transition matrix; `stationary_distribution`/`is_stationary_distribution` provide the general eigenvector-based calculation and an independent fixed-point test, cross-checked against a derived 2-state closed form, a 2,000,000-step empirical simulation, and the simulator's own long-run regime occupancy; found and fixed a minor `exp(log(s0))` non-bit-exactness before trusting the simulator, matching `stochastica.gbm`'s own convention |
| PR-067 (new ID, genuinely new model) Volatility clustering benchmark (SDE-07) | implemented locally | `stochastica.garch`: GARCH(1,1), the classical benchmark for volatility CLUSTERING specifically -- a phenomenon none of GBM/Heston/Merton exhibit by construction; `GarchParams` enforces Bollerslev's stationarity condition `alpha+beta<1` directly; `volatility_clustering_diagnostics` reports squared/absolute-return autocorrelation plus conditional/realized variance as one structured report; found and fixed a real aggregation bug before trusting it -- a naive first draft flattened multi-path batches into one concatenated series before computing autocorrelation, spuriously pairing each path's last observation with the next path's first at every boundary; confirmed the behavioral signature itself (squared-return ACF ~0.17-0.21 at lags 1-5) against a contrasting i.i.d. negative control (ACF ~0, same unconditional variance) |
| PR-068 (new ID) Out-of-sample optimization comparison (OPT-08) | implemented locally | `titan.out_of_sample.compare_in_sample_and_out_of_sample`: fits minimum-variance weights using ONLY a train block, then scores those SAME frozen weights on both the train and a held-out test block; confirmed empirically before writing any production code (not assumed from theory): across 300 trials from a known covariance, mean in-sample variance (0.00281) < the true optimal variance (0.00325) < mean out-of-sample variance (0.00364) -- in-sample optimization is systematically optimistic, out-of-sample is systematically pessimistic, and the ordering is pinned as a regression guard on trial averages |
| PR-069 (new ID) Default/loss-allocation reconciliation audit (ECO-10) | implemented locally | an audit of the pre-existing `econosim.insolvency` module (not new production code) confirmed `resolve_insolvency`/`allocate_recovery` already implement defaults and orderly (absolute-priority-respecting) loss allocation; added one new, explicit toy-case test (3 creditors across all three priority tiers, partial recovery) stating the "claims and equity loss reconciliation" identity directly -- total written off across every creditor equals exactly the total equity lost by those creditors -- rather than leaving it implicit in scattered per-bank assertions elsewhere |
| PR-070 (new ID, genuinely new functionality) Bid/ask spread and liquidity cost model (LED-09) | implemented locally | `econosim.liquidity.LiquidityAssumptions`/`ask_price`/`bid_price`/`round_trip_cost`: every existing econosim trade executes at a single price with no spread at all, not by deliberate frictionless design but because no spread concept existed; this adds one as a pure, composable cost model (not wired into the existing ledger-posting code, deliberately, to avoid modifying it); "no zero-cost trades unless explicit frictionless baseline" is enforced directly in `__post_init__` (spread_bps==0 requires frictionless=True explicitly, and vice versa); demonstrated against the real, unmodified ledger (a household buying at the ask ends up with strictly less cash than the same trade at the frictionless mid), not just asserted on the quoting math in isolation |
| PR-071 (new ID, companion to PR-070) Trade execution/settlement event ordering (LED-10) | implemented locally | `econosim.trade_lifecycle.TradeLedger`: every existing econosim trade is atomic (execution and settlement in the same instant), so there has never been a gap between "agreed" and "settled" for accounting to anticipate; a standalone `Trade`/`TradeLedger` pair adds that gap explicitly -- executions must be recorded in non-decreasing step order, and `net_position_as_of` counts only SETTLED trades; a direct, step-by-step test confirms a trade executed at step 5 but settling at step 10 contributes nothing to either party's position at steps 5 through 9, not just a single spot-check |
| PR-072 (new ID, third companion to PR-070) Inventory nonnegativity enforcement (LED-03) | implemented locally | `econosim.inventory.InventoryAccount`/`InsufficientInventoryError`: `price_economy.py`'s own existing nonnegative-inventory guard is a bare ValueError, deeply nested, and effectively unreachable through normal price discovery (confirmed, not assumed); this adds the same invariant as a standalone, directly testable primitive with a structured error (available/requested/floor attributes, matching `InsufficientFundsError`'s convention); "unless specified financing exists" is a genuine, per-call opt-in (`financed=True`), confirmed to NOT be implicitly authorized just by configuring a nonzero financing_limit on the account |
| PR-073 (new ID, fourth companion to PR-070) Equity rollforward reconciliation (LED-04) | implemented locally | `econosim.equity_rollforward.reconcile_equity_rollforward`: independently recomputes an account's closing equity (opening + credits - debits across its posting history) from the ledger's own journal, through a code path separate from `Account._apply`'s running balance, and confirms the two agree; exercised across all four agent sectors (Household/Firm/Bank/Government) in one shared toy economy; a tampered-balance test confirms the check actually discriminates, and a mid-simulation test confirms it works as a genuine rollforward from a non-zero opening balance |
| PR-074 (new ID) Expected Shortfall backtesting/calibration diagnostics (RISK-09) | implemented locally | `titan.risk_metrics.quantile_score` (pinball loss, strictly consistent VaR scoring), `expected_shortfall_exceedance_residual_test` (McNeil-Frey 2000 ES backtest) and `es_unconditional_calibration_test` (Acerbi-Szekely 2014-style statistic, handles zero exceedances, bootstrap p-value); each confirmed by repeated-trial false-positive-rate and detection-power simulation against a known Gaussian reference; both forecast backtests accept a constant threshold or a time-varying per-observation forecast array |
| PR-075 (new ID, audit) Interbank payments and reserve settlement (ECO-11) | implemented locally | `econosim.interbank_market.InterbankMarket.lend`/`repay` (direct bilateral interbank payments) and `econosim.central_bank_ledger.CentralBankLedger.settle_interbank_transfer` (central-bank-mediated reserve settlement) were already implemented and separately tested but never tagged against ECO-11; one new test file states the claim explicitly in a combined scenario, plus a discriminating test confirming the two reserve instruments are genuinely unreconciled (a pre-existing, documented limitation, now empirically verified rather than merely asserted) |
| PR-076 (new ID) Moving block bootstrap for serial dependence (EXP-09) | implemented locally | `experiments.block_bootstrap.moving_block_bootstrap` (Kunsch 1989); verified against an exactly-known AR(1) ground truth -- a 40-trial CI-width-to-true-SE ratio comparison and a 150-trial 95%-nominal coverage-rate check both confirm a large, genuine improvement over the naive single-observation bootstrap, which badly under-covers on serially-dependent data |
| PR-077 (new ID) Liquidity and position-capacity constraints (OPT-06) | implemented locally | `titan.portfolio.PortfolioConstraints.max_weight_per_asset`, a per-asset cap tightening the existing uniform box bound, threaded through all three optimizers; purely additive (defaults to `None`, reproducing every existing caller unchanged); a discriminating test confirms the cap actually binds against an optimum that would otherwise violate it, and that an unreachable target-return-under-a-cap still reports `success=False` honestly (OPT-09) rather than a silently-clipped false optimum |
| PR-078 (new ID) Leverage and position-size constraint projection (HDG-07) | implemented locally | `hedging.position_constraints.project_onto_feasible_region`/`PositionLimits`, an independent action-projection step distinct from VAL-08's ledger-level checks and HDG-04's fixed tanh bound; a 300-example Hypothesis property sweep confirms the projected holding always satisfies both the position-size cap and the leverage-implied notional cap, and that an already-feasible holding is never altered; "concentration" explicitly not claimed (not independently meaningful in this repository's single-underlying hedging setup) |
| PR-079 (new ID) GDP/inflation/credit definitions, cross-validated (ECO-15) | implemented locally | `econosim.macro_aggregates.compute_macro_aggregates`; cross-validates GDP's income and expenditure approaches against an independent ledger-derived firm-profit figure on a real Economy scenario, confirms taxes/transfers are correctly excluded from GDP even when scaled up substantially, and confirms a deliberately dirtied period (mid-period capitalization) is correctly flagged rather than silently absorbed into profit |
| PR-080 (new ID) Automated leakage linter (DAT-09) | implemented locally | `econosim.leakage_linter.lint_future_timestamp_usage` (general) and `lint_pit_store_usage` (PointInTimeStore-integrated, through the store's own public `as_of` predicate, not a privacy-violating direct read of its internal records); the complementary DETECTIVE half of `econosim.pit`'s existing preventive access-time gate; a test confirms it correctly accounts for ingestion-lag (`asof_eligible_at`), not just raw publication date |
| PR-081 (new ID) Immutable pricing/risk report responses (API-05) | implemented locally | `service.reports.PricingReportResponse`/`RiskReportResponse` (frozen dataclasses, immutability confirmed by test to raise `FrozenInstanceError`) plus `build_pricing_report`/`build_risk_report`, computing `market_snapshot_id` deterministically from a `MarketSnapshot` via the existing `compute_result_hash` utility (reused, not reimplemented); confirmed both deterministic for identical snapshots and discriminating for different ones |
| PR-082 (new ID, audit) Cross-bank transfer settlement-balance preservation (LED-08) | implemented locally | pre-existing `Bank.reserves_account`, `InterbankMarket` (ECO-11) and `CentralBankLedger.settle_interbank_transfer`, read against LED-08's own narrow, literal acceptance criterion ("cross-bank transfer preserves total settlement balances"), not the broader requirement text; a new three-bank test confirms the system-wide `settlement_balance_of` total is preserved across multiple transfers, more discriminating than summing over only the two parties that swapped funds |
| PR-083 (new ID, GBM only) Historical GBM calibration with dated parameter versions (SDE-10) | implemented locally | `stochastica.historical_calibration.calibrate_gbm_mle` (closed-form MLE, cross-checked against a tightly-converged general-purpose numerical optimizer) and `CalibrationHistory` (point-in-time versioned lookup, reusing `econosim.pit`'s own as-of convention); GARCH/regime-switching calibration deliberately not attempted after an earlier GARCH-MLE optimizer-fragility finding this session |
| PR-084 (new ID) Numerical accuracy budget per API output (VAL-12) | implemented locally | `service.reports.PricingReportResponse`/`RiskReportResponse` gain a required per-field tolerance (`price_tolerance`; `value_at_risk_tolerance`, `expected_shortfall_tolerance`), rejecting a non-positive one; `check_pricing_tolerance`/`check_risk_tolerance` detect and report violations against an independent reference value; while re-verifying the full suite, found and fixed a 7th SDE-12-adjacent crash -- `barrier_options`'s discount-factor exponent was never checked against its own overflow guard, raising an uncaught `OverflowError` instead of a clean `ValueError` at `rate=-5.0, maturity=142.0` |
| PR-085 (new ID) Immutable train/validation/test regime splits (EXP-04) | implemented locally | `experiments.holdout_manifest.DataSplit`/`HoldoutManifest`/`build_holdout_manifest`: a content-addressed manifest id (reusing `compute_result_hash`) that is order-independent but discriminates on any cutoff change; rejects duplicate split ids and overlapping date ranges while still permitting a deliberate gap between regimes; `split_for_date`/`regime_for_date` for querying which regime a date belongs to |
| PR-086 (new ID) Future-data negative control, isolated from the scoreboard (EXP-05) | implemented locally | `experiments.leakage_negative_control.run_future_data_negative_control`/`LeakageNegativeControlResult`/`assert_scoreboard_is_leakage_clean`; exercised against a real `PointInTimeStore` leak scenario (large positive gap) and its converse (near-zero gap when data is already legitimately eligible); the isolation guard is `isinstance`-based, not a spoofable string tag |
| PR-087 (new ID) Computational cost and memory benchmarking across methods (EXP-11) | implemented locally | `experiments.cost_benchmark.HardwareInfo`/`MethodCostProfile`/`benchmark_method_cost`/`benchmark_methods_cost`: hardware/GPU-driver/dtype/walltime fields all present and logged, honestly `gpu_available=False`/`gpu_driver=None` on this CPU-only environment; GPU-present and torch-absent branches exercised via monkeypatching; memory measured via stdlib `tracemalloc`, confirmed to discriminate between a small and a 20M-element allocation |
| PR-088 (new ID, audit plus fix) Explicit P/Q measure on every report (AUD-04) | implemented locally | `service.reports.PricingReportResponse`/`RiskReportResponse` gain a required `measure: Literal["P","Q"]` field, independent of `MarketSnapshot`'s own field (which is structurally pinned to `"Q"` by SDE-09 and so could never, by itself, tag a P-measure risk report); no default (`TypeError` if omitted); a discriminating test confirms a risk report's measure can genuinely be overridden to `"Q"` |
| PR-089 (new ID) Result inventory retaining failed experiment evidence (AUD-12) | implemented locally | `experiments.result_inventory.ExperimentAttempt`/`ResultInventory`/`build_result_inventory`; demonstrated against this repository's own real GARCH(1,1)-optimizer-abandonment history (3 distinct exclusions with their real documented reasons) alongside the adopted GBM closed-form MLE (1 included attempt carrying its actual `calibrate_gbm_mle` metric, not a fabricated number) |
| PR-090 (new ID) Agent and hedge decision audit log (AUD-05) | implemented locally | `experiments.decision_audit_log.DecisionLogEntry`/`CausalityViolation`/`audit_replay`; domain-agnostic float timestamps; detective, not preventive, design matching `leakage_linter`; demonstrated against a real `OnlineHedgeAccount` rebalancing simulation and a real `Household.consume` call, each with a clean case and a caught causality violation |
| PR-091 (new ID) Risk reports recomputed from raw facts (AUD-09) | implemented locally | `service.report_recomputation.MetricFormula`/`VALUE_AT_RISK_FORMULA`/`EXPECTED_SHORTFALL_FORMULA`/`recompute_risk_report_from_raw_losses`; reuses `titan.risk_metrics`'s own documented formulas and `service.reports.check_risk_tolerance`; confirmed against a real raw loss array with honest-reproduction, tampered-VaR, tampered-ES and non-default-alpha cases |
| PR-092 (new ID) Training provenance manifest sufficient for replay (AUD-03) | implemented locally | `experiments.training_provenance.TrainingProvenanceManifest`/`capture_training_provenance`; content-addressed over config+seed+environment (reusing `runtime_provenance`); confirmed by a real bit-identical replay of `hedging.deep_hedge.train_deep_hedge` from the manifest alone, plus a discriminating different-seed converse |
| PR-093 (new ID) Deploy manifest any deployment can be recreated from (CIQ-11) | implemented locally | `service.deploy_manifest.DeployManifest`/`capture_deploy_manifest`/`recreate_service_policy`; content-addressed over the real `ServicePolicy`, feature flags (honestly empty) and environment; confirmed by reconstructing a deliberately non-default `ServicePolicy` from its manifest and checking full field-for-field equality |
| PR-094 (new ID, secret scanning only) Secret scanning and a severity-gated release decision (CIQ-05) | implemented locally | `evidence.security_scan.ScanFinding`/`secret_scan`/`evaluate_release_gate`/`ReleaseGateDecision`; scanner-agnostic gate with content-addressed per-finding approval; confirmed by a real zero-findings self-scan of this repository's own `src/` tree and a discriminating approval-scoping test; vulnerability/dependency scanning deliberately not attempted (no live CVE database reachable in this environment) |
| PR-095 (new ID) Per-series data quality monitoring (DAT-11) | implemented locally | `econosim.data_quality.DataQualitySummary`/`summarize_data_quality`; operates on caller-supplied observations rather than reading `PointInTimeStore`'s internals; conflicting-duplicate vs. harmless-re-ingestion discrimination, revision counting, and `asof_eligible_at`-honoring freshness, confirmed by 9 tests |
| PR-096 (new ID) Dataset fingerprinting for normalized data and feature transformations (DAT-12) | implemented locally | `experiments.dataset_fingerprint.DatasetFingerprint`/`compute_dataset_fingerprint`/`verify_dataset_fingerprint`; demonstrated against real GBM-price-to-log-return reproduction, a different-transformation discrimination, and a 1e-9-perturbation detection case |
| PR-097 (new ID, audit) Capacity/quota rejection with transparent reasons (REL-10) | implemented locally | pre-existing `ServicePolicy`/`Admission` (`"rate_limited"`) and `QueuePolicy.max_pending_per_owner` (`"quota_exceeded"`), read against REL-10's own acceptance criterion; one new deliberate test confirms the two rejection codes are genuinely distinct, not merely individually present |
| PR-098 (two new IDs) Model registry states, transition policy and a promotion gate (MLO-08, MLO-10) | implemented locally | `evidence.model_registry.ModelRegistryEntry`/`StateTransition`/`is_allowed_transition`/`promote_to_approved`; the gate reuses `training_provenance.TrainingProvenanceManifest` (AUD-03) rather than reinventing provenance capture; 25 tests covering the full forward path, emergency retirement, illegal transitions, and each of 3 separate promotion-denial reasons |
| PR-099 (new ID) Content-hashed, immutable model packages (MLO-07) | implemented locally | `evidence.model_package.ModelPackage`/`build_model_package`/`verify_package_integrity`/`PackageIntegrityError`; grounded in a real `torch.save`d `HedgePolicyMLP` artifact; deterministic/discriminating content hashing and single-byte tamper detection, confirmed by 11 tests |
| PR-100 (new ID) Controlled model rollback with stale-cache purge (MLO-12) | implemented locally | `evidence.model_serving.ModelServingSlot`/`deploy`/`cached_predict`/`rollback_to`; a content-hash-keyed inference cache purged selectively on rollback; 6 tests confirm exact restoration, stale-entry purge and valid-entry preservation (via a compute-call counter) separately |
| PR-101 (new ID) Early stopping that structurally forbids the test regime (MLO-06) | implemented locally | `experiments.early_stopping.EarlyStopper`/`EarlyStoppingDecision`/`NonValidationRegimeError`; reuses `holdout_manifest.Regime` (EXP-04); 11 tests including a real `HoldoutManifest`-driven simulated training loop and a genuine test-regime-date rejection |
| PR-102 (new ID) Champion/challenger comparison with matched data (MLO-14) | implemented locally | `evidence.champion_challenger.ChampionChallengerReport`/`build_champion_challenger_report`/`ChampionNeverApprovedError`; reuses `model_registry`'s audit trail (MLO-08) and `paired_bootstrap_difference`; grounded in a real delta-hedge-vs-no-trade-band comparison on identical simulated paths, confirmed by 6 tests |
| PR-103 (new ID, audit) Restored artifacts are readable and hash-consistent (REL-11) | implemented locally | pre-existing `recovery.snapshot`/`jobs.artifacts.ArtifactStore`, read against REL-11's own acceptance criterion; one new deliberate test confirms readability and an independently recomputed canonical-JSON content-hash match after a real backup/restore round trip |
| PR-104 (new ID) Identity, approval, previous state and hash on every registry transition (AUD-06) | implemented locally | `evidence.model_registry.StateTransition` gains required `approved_by` and a promotion-required `content_hash` via a new required `ModelPackage` parameter on `promote_to_approved`; a full-lifecycle test confirms all four AUD-06 fields appear exactly where each applies |
| PR-105 (new ID) Real, code-derived service inventory and dependency map (OPS-01) | implemented locally | `evidence.ops_inventory.ServiceComponent`/`discover_component_names`/`discover_dependencies`/`build_service_inventory`; parses real `.py` imports via `ast`, run against this repository's own source tree, surfacing a genuine stochastica/volterra package-level cycle |
| PR-106 (new ID) Simulation jobs benchmarked at small/medium/large scales (REL-03) | implemented locally | `experiments.scale_benchmark.ScaleBudget`/`check_scale_budgets`/`walltimes_are_monotonically_increasing`; reuses `cost_benchmark` (EXP-11); grounded in a real small/medium/large GBM benchmark; found and fixed a real `zip(strict=True)` crash bug while writing its own test |
| PR-107 (new ID) Dataset cards distinguishing synthetic from empirical data (DAT-14) | implemented locally | `evidence.dataset_card.DatasetCard`/`build_dataset_card`; grounded in a real GBM simulation and the same real captured World Bank fixture `test_worldbank_connector.py` uses, carrying its actual license string |
| PR-108 (new ID) Raw/normalized/features/artifacts storage layers (DAT-06) | implemented locally | `econosim.storage_layers.StorageLayer`/`ImmutableWriteError`/`LayerPermissionError`; per-key immutability plus a strict read-permission pipeline, confirmed by a skip-a-layer rejection test |
| PR-109 (new ID) Schema contracts with quarantine, unit normalization and currency mapping (DAT-10) | implemented locally | `econosim.schema_contracts.SchemaContract`/`QuarantinedRecord`/`validate_against_contract`/`normalize_unit`/`map_currency_code`; exact unit-scale conversion only, no fabricated FX rates; 14 tests including the distinct unit-vs-currency mismatch discrimination |
| PR-110 (new ID) Retraining triggers with pre-registered thresholds (MLO-13) | implemented locally | `evidence.retraining_trigger.RetrainingThreshold`/`RetrainingEscalation`/`evaluate_retraining_trigger`; reuses RISK-09's `es_unconditional_calibration_test` with real well-calibrated (p=0.33) and miscalibrated (p≈3.6e-10) p-values, plus a backdating rejection |
| PR-111 (new ID) Tamper-evident hash-chained log for access-control changes and privileged actions (AUD-07) | implemented locally | `evidence.tamper_evident_log.TamperEvidentLog`/`LogEntry`/`TamperEvidenceError`; reuses `jobs.store`'s own hash-chaining technique, generalized; a direct tamper and a forged-hash tamper are both caught, confirmed by 8 tests |
| PR-112 (new ID) Real p95 load report for the metadata API (REL-02) | implemented locally | `experiments.latency_benchmark.LoadReport`/`build_load_report`/`meets_p95_target`; a real 120-request, concurrency-8 load test against `ResearchService`'s own ASGI `GET /v1/jobs` endpoint, confirmed stable across repeated runs |
| PR-113 (new ID) Long-horizon numerical-stability and memory-leak soak test (REL-09) | implemented locally | `experiments.soak_test.SoakTestResult`/`run_soak_test`; a real 60-iteration GBM soak run plus a deliberate-leak and a single-bad-iteration discrimination case, confirmed by 7 tests, stable across repeated reruns |
| PR-114 (new ID) Internal service SLO/SLI definitions (REL-01) | implemented locally | `evidence.slo_definitions.ServiceLevelObjective`/`slo_is_met`; closes the loop with REL-02, confirming a genuine `LoadReport` meets its own named SLO, plus a wrong-endpoint rejection; confirmed by 8 tests |
| PR-115 (new ID) Reproducible inference against approved reference outputs (MLO-11) | implemented locally | `evidence.reproducible_inference.InputContract`/`ReferenceCase`/`verify_reproducible_inference`; grounded in a real, deterministically-seeded `HedgePolicyMLP`, including a tampered-approved-output discrimination case; confirmed by 8 tests |
| PR-116 (new ID) Unambiguous dataset provenance composed from four existing primitives (MLO-03) | implemented locally | `evidence.dataset_provenance.DatasetProvenance`/`build_dataset_provenance`/`ProvenanceMismatchError`; composes `ModelPackage`, `DatasetFingerprint`, `InputContract` and `HoldoutManifest`; model-mismatch and no-train-split rejections confirmed by 5 tests |
| PR-117 (two new IDs) Checkpoint/resume and a per-epoch learning-curve/gradient log (MLO-04, MLO-05) | implemented locally | `hedging.deep_hedge.TrainingCheckpoint`/`EpochRecord`/`resume_from`, additive to the existing `train_deep_hedge`; a real split-training-run test confirms bit-for-bit exact final-weight reproduction after resume, plus a mismatched-seed rejection and a real gradient-norm log; also closed a pre-existing "put"-branch coverage gap |
| PR-118 (new ID) Kenneth French factor ingestion with version tracking (DAT-05) | implemented locally | `data_ingestion.french_factors.fetch_french_factors`; a real captured Kenneth French Data Library response (4,812 monthly + 396 annual observations, vintage "202609") embedded hermetically and fed through `PointInTimeStore`; confirmed by 9 tests |
| PR-119 (new ID) External data source inventory and license catalog (DAT-01) | implemented locally | `data_ingestion.source_inventory.build_source_catalog`; ast-derived against the real `data_ingestion` package, confirmed to find both real connectors with their actual URL/license strings, plus an incomplete-declaration rejection; confirmed by 9 tests |
| PR-120 (new ID) Sandbox validator for untrusted uploaded dataset archives (SEC-08) | implemented locally | `data_ingestion.dataset_sandbox.validate_zip_archive`/`SandboxLimits`; zip-slip and decompression-bomb rejection grounded in real archives on both sides of the default 100x threshold, plus a 600-case Hypothesis fuzz test; confirmed by 20 tests |
| PR-121 (new ID) Restricted-data-license scan composing through the existing release gate (DAT-13) | implemented locally | `evidence.security_scan.license_scan`, composing through the existing scanner-agnostic `evaluate_release_gate`; a real zero-finding sweep of this repository's own tracked source tree, CI-enforced via the existing unconditional `pytest -q` step; confirmed by 7 new tests |
| PR-122 (new ID) Job queue depth, runtime and cancellation metrics with warning/critical thresholds (OPS-04) | implemented locally | `evidence.queue_metrics.compute_queue_metrics`/`classify_queue_health`; grounded in a real `JobStore` submit/claim/cancel/finish lifecycle with a deterministic clock, reproducing exact queue depth, running count, cancellation count and runtime percentiles; confirmed by 15 tests |
| PR-123 (new ID) Inference throughput, latency and failure rate per endpoint and model (OPS-05) | implemented locally | `evidence.inference_metrics.run_inference_benchmark`; exact 0%/50%/100% failure-rate discrimination, plus two real backends (a trained `HedgePolicyMLP` forward pass and a real HTTP call against `ResearchService`); confirmed by 11 tests |
| PR-124 (new ID) Data staleness and failed-ingest-count alerting (OPS-06) | implemented locally | `evidence.data_health.measure_staleness`, plus the existing `run_inference_benchmark` reused for ingest-failure counting; a real stale/not-stale alert exercise and a real 0.3 failure rate against a genuinely flaky connector; confirmed by 11 tests |
| PR-125 (new ID) High-severity numerical event monitoring with assigned ownership (OPS-07) | implemented locally | `evidence.numerical_event_monitor.monitor_call`/`monitor_pricing_deviation`; a real extreme-drift GBM solver failure, and a real Monte-Carlo-vs-closed-form pricing-deviation discrimination, each carrying a required `owner`; confirmed by 14 tests |
| PR-126 (new ID) Model drift, risk-metric calibration and tail-breach monitoring with an investigation playbook (OPS-08) | implemented locally | `evidence.model_monitoring`, composing RISK-08/RISK-09/MLO-13/MLO-14's existing primitives; each signal confirmed to fire and not-fire against real data, plus an owner-required investigation playbook; confirmed by 14 tests |
| PR-127 (new ID) CPU/RAM and artifact storage utilization tracking with capacity forecasting and budget alerts (OPS-09) | implemented locally | `evidence.resource_utilization.sample_resource_usage`/`forecast_capacity`/`classify_utilization`; real CPU/RAM readings, real artifact-store byte tracking via a new `ArtifactStore.usage_bytes`, and an exact linear capacity forecast; confirmed by 15 tests |
| PR-128 (new ID) Actionable alert routing with a severity taxonomy (OPS-10) | implemented locally | `evidence.alert_routing.route_alert`/`RoutingTable`/`canonical_severity`; a genuine `UnroutedSeverityError` for an unconfigured P0/P1, and three real existing signal sources each routed end-to-end to a configured owner; confirmed by 13 tests |
| PR-129 (new ID) Severity matrix for incorrect pricing, risk and data-integrity incidents (DRI-01) | implemented locally | `evidence.severity_matrix.SeverityMatrix`/`SeverityMatrixEntry`; a genuine `UnknownIncidentCategoryError` for a real, deliberately-unconfigured `ERROR_CODES` member, plus real lookups for real job and numerical-event categories; confirmed by 9 tests |
| PR-130 (new ID) Numerical-integrity incident runbook: isolate, invalidate, re-evaluate (DRI-02) | implemented locally | `evidence.numerical_integrity_runbook.run_numerical_integrity_runbook`; a real flaky callable that recovers on re-evaluation, and a real persistently-failing GBM guard that still fails, each producing a real chronologically-ordered timeline; confirmed by 5 tests |
| PR-131 (new ID) Compromised-credential and secret-rotation tabletop drill (DRI-03) | implemented locally | `evidence.credential_rotation_drill.rotate_credential`/`run_credential_rotation_drill`; a real end-to-end rotation against `service.auth.CredentialStore` confirming old-token rejection and new-token acceptance, plus an unrotated-credential discrimination case; confirmed by 5 tests |
| PR-132 (new ID) Corrupt-data and point-in-time leak response: trace, revoke, recompute (DRI-04) | implemented locally | `evidence.pit_leak_response.detect_leak`/`trace_affected_runs`/`recompute`; a real leaked run identified against a real two-vintage series, and a real recomputation confirmed to produce a different, correct result; confirmed by 9 tests |
| PR-133 (new ID) Audit-log and model-approval-history availability throughout failover (DRI-11) | implemented locally | `evidence.failover_audit_continuity.read_job_events`/`serialize_registry_entry`/`restore_registry_entry`; a real snapshot/restore round trip confirming byte-for-byte event completeness, and a real model-approval history round trip rejecting a tampered reordering; confirmed by 3 tests |
| PR-134 (new ID) Runbooks for top failure categories with simulated on-call drills (OPS-11) | implemented locally | `evidence.runbook_catalog.run_numerical_integrity_drill`/`run_credential_compromise_drill`; two distinct real failure categories each producing a real chronologically-ordered timeline with a genuine pass/fail outcome; confirmed by 6 tests |
| PR-135 (new ID) Confirmation that no observability vendor exports restricted financial data, closing OPS at 100% (OPS-12) | implemented locally | `evidence.observability_vendor_review.scan_for_observability_vendor_integration`/`extract_event_schema_field_names`/`check_for_sensitive_field_names`; a real zero-finding vendor sweep and a real ast-derived confirmation of the audit-log schema; confirmed by 6 tests |
| PR-136 (new ID) Error budget actions with service ownership (REL-12) | implemented locally | `evidence.error_budget.evaluate_error_budget`/`record_error_budget_action`; an exact real breach-rate count against a real SLO/LoadReport window, composed through the existing `evaluate_release_gate` to genuinely block and unblock release; confirmed by 9 tests |
| PR-137 (new ID) Log/metric storage cardinality budget verification, closing REL at 100% (REL-08) | implemented locally | `evidence.cardinality_budget.compute_label_combinations`/`verify_cardinality_budget`; an exact, identical 30-combination count at 50 and 5,000 real simulated jobs, versus a genuinely unbounded `job_id`-labeled count that blows the budget; confirmed by 6 tests |
| PR-138 (new ID) Versioned analytical tables with reproducible-script and data-hash linkage, closing AUD at 100% (AUD-10) | implemented locally | `evidence.versioned_table.build_versioned_table`/`verify_versioned_table`; a real table linked to the real `evidence.requirements` script, with genuine script-tamper and data-tamper detection; confirmed by 8 tests |
| PR-139 (addendum only, no new 374-item ID) RECESSIONNET with a hybrid quantum classifier challenger, closing FP-06 and FP-20 | implemented locally | `recessionnet.{labels,dataset,training,evaluation}` plus new `prometheus.quantum` package; real NBER recession chronology and announcement dates, real Kenneth French factor features, a point-in-time leakage test on the label itself, and a real (honestly negative) quantum-vs-classical benchmark; confirmed by 74 tests |
| PR-140 (addendum tooling, no new 374-item ID) A runnable RECESSIONNET demo CLI | implemented locally | `orchestration.recessionnet_run`, matching this repo's own `economy_run.py`/`benchmark_run.py` CLI convention: live-fetches the real French factor series, runs the full PR-139 benchmark, and prints/exports a JSON summary with a run manifest; `main`'s `transport` is injectable so the CLI itself is hermetically tested (no network call during `pytest`); confirmed by 13 tests, 99% coverage (only the standard `if __name__` guard uncovered, same as every other orchestration script here) |
| PR-141 (addendum fix, no new 374-item ID) Fixed a gradient-dead-zone bug in the hybrid quantum classifier's angle embedding | implemented locally | `quantum.models.HybridQuantumClassifier` scaled its encoder output by pi before angle embedding; under a single-qubit RX gate, d&lt;Z&gt;/d(theta) = -sin(theta), zero at theta=0 and +/-pi, peak at +/-pi/2 -- a saturating `tanh` encoder was pushing most inputs toward the zero-gradient +/-pi extreme. Diagnosed directly from PR-139's own calibration-slope diagnostic (~0.10, i.e. barely discriminating) rather than guessed; fixed by rescaling to pi/2. Real result after the fix: test-set AUC improved from ~0.61 to ~0.70 and calibration slope from ~0.10 to ~0.22, but the quantum model still loses clearly to logistic regression (AUC ~0.86) at a 300-epoch budget, and is statistically indistinguishable from it (not better) at a shorter 150-epoch budget -- both outcomes now locked in as regression tests rather than one being silently left stale; confirmed by 1 new test plus 2 existing tests updated to the corrected real numbers |
| PR-142 (addendum methodology fix, no new 374-item ID) Early-stopping, validation-selected model comparison for RECESSIONNET | implemented locally | A diagnostic training-curve trace found the hybrid quantum and classical-MLP models (493 parameters) overfitting past epoch ~20-60 at PR-139's fixed epoch budget while logistic regression (25 parameters) did not -- a fixed-epoch comparison was unfair once capacity differs this much. `training.train_classifier_with_early_stopping` and `evaluation.run_recessionnet_benchmark_with_early_stopping` select each model's stopping epoch by a validation split carved out of the training era (1988-1999), never the test set; real seed=0 result: quantum Brier (~0.087) now sits close to its best classical challenger's (~0.083), and 4 of 5 seeds checked by hand are statistically inconclusive rather than a robust quantum loss; confirmed by 14 new tests, 99-100% coverage |
| PR-143 (addendum, FP-05 partial) Q-MACRO: hybrid quantum regressor vs. AR(3)/MLP/persistence for h-months-ahead Mkt-RF | implemented locally | New `macrocore.regression_dataset`/`macrocore.quantum_benchmark` plus `quantum.models.{LinearRegressionModel,ClassicalMatchedRegressor,HybridQuantumRegressor}` (zero-behavior-change subclasses reusing the RECESSIONNET architectures for a regression target); AR(3) genuinely refit at every real test month, three learned models selected by early stopping from the start (PR-142's methodology, not repeated as a mistake); real result: AR(3)/MLP/quantum all land within a tight band (MAE ~0.034, MASE ~0.62), all clearly ahead of naive persistence (MASE ~0.89), no significant difference among them across 5 seeds checked; confirmed by 36 new tests, 99-100% coverage |
| PR-144 (demo reliability, no new ID) Offline-fallback data + switched RECESSIONNET's CLI to early stopping | implemented locally | `french_factors.save_ff3_snapshot`/`load_cached_ff3_snapshot` plus a committed real snapshot at `data_cache/ff3_monthly_snapshot.csv`; `orchestration.recessionnet_run`/`qmacro_run` try a live fetch first and fall back to this snapshot on any network/response failure (confirmed end to end under a simulated outage, exit 0, `data_source: "cached_snapshot_fallback"`), tagging which path was used in the output rather than hiding it; `recessionnet_run` also switched from the superseded fixed-epoch benchmark to `run_recessionnet_benchmark_with_early_stopping` (PR-142's methodology, matching Q-MACRO's CLI from the start), cutting its own wall-clock time roughly in half (~17s to ~7-13s); confirmed by 7 new/updated tests, 99% coverage, and multiple live rehearsal runs |
| PR-145 (addendum, second real-data grounding, no new ID) RECESSIONNET on real Kaggle-sourced US GDP/claims/Fed-funds/M2/NASDAQ data | implemented locally | `data_ingestion.kaggle_macro` plus a committed derived snapshot (`data_cache/kaggle_us_macro_monthly.csv`, real FRED-sourced series via Kaggle dataset `mikoajfish99/us-recession-and-financial-indicators`, ODbL-1.0); new `orchestration.recessionnet_kaggle_run` CLI makes NO network call at all (data fully committed); reuses every RECESSIONNET/`prometheus.quantum` primitive unchanged; real result: base rate is the strongest classical candidate on this dataset/split, quantum shows no significant difference against it; confirmed by 7 new tests, 97-100% coverage |
| PR-146 (DAT-04, first evidence) Real US Treasury par yield curve ingestion with recorded day-count and holiday conventions | implemented locally | `data_ingestion.treasury_yield_curve` fetches all 11 CMT tenors (1mo-30yr) via FRED's no-key `fredgraph.csv` export (`home.treasury.gov` itself timed out from this environment, confirmed by a direct pre-implementation probe); `treasury_market_conventions()` records the standard day-count split, and market holidays are DERIVED from real published-value gaps (not a hand-typed list), confirmed against three real closures including a Good-Friday/non-federal-holiday discriminating case; real sanity checks: the 2006 2y/10y curve inversion (-0.07, ahead of the 2008 recession) and the 2020 COVID 3-month-bill rate cut to exactly 0.00%; confirmed by 12 new tests, 100% coverage; blueprint coverage 210/374 -> 211/374 |
| PR-147 (DOC-01/02/03/04/05/07/08/09/10/11/12) Nine new published documents plus CONTRIBUTING/SECURITY/CODE_OF_CONDUCT, closing DOC at 12/12 | implemented locally | `docs/{DATA_DICTIONARY,PROBLEM_STATEMENT,MATHEMATICAL_APPENDIX,SUBSYSTEM_INTERFACES,EXPERIMENT_GUIDE,RESULTS_AND_LIMITATIONS,SECURITY_AND_DATA_HANDLING,OPERATIONS_RUNBOOK}.md` plus root `CONTRIBUTING.md`/`SECURITY.md`/`CODE_OF_CONDUCT.md`; every claim cites a real pre-existing module, test, or PR (no new code); DOC-10 (API spec + example client) was found already fully satisfied by pre-existing `docs/api/openapi-v1.json` + `service.client` + `tests/unit/test_service_client.py` and simply credited for the first time; DOC-07/DOC-08 marked `(partial)` in `CHECKLIST_STATUS.md` for specific, disclosed reasons (a documented reproducibility/invalidation mechanism, not a new rollback demonstration); no new tests (documentation only); blueprint coverage 211/374 -> 222/374 |
| PR-148 (SEC-10, first evidence) Network egress allowlist for data ingestion, with real denial and alert routing | implemented locally | `data_ingestion.egress_allowlist.AllowlistedTransport` wraps any `HttpTransport`, checking the request host against a configured allowlist before delegating; denial routes a real P1 alert through the pre-existing `evidence.alert_routing.route_alert` (fails loudly via `UnroutedSeverityError` if no owner/escalation was ever configured) and records a structured `EgressDenial`; default allowlist built from the real connector `*_URL` constants (`fred.stlouisfed.org`, `api.worldbank.org`, `mba.tuck.dartmouth.edu`), not retyped by hand; confirmed by 6 new tests, 100% coverage; disclosed scope: no connector call site was switched to use this wrapper yet, and "model serving" originates no outbound call today; blueprint coverage 222/374 -> 223/374 |
| PR-149 (GOV-12/GOV-09/SEC-01/SEC-15, first evidence) Risk acceptance register, machine-verified license inventory, threat model, security patch-cadence | implemented locally | `evidence.risk_register.{RiskException,RiskRegister}` (demonstrated against two real, already-disclosed repository exceptions from PR-146/PR-148); `evidence.license_inventory` parses this repo's real `pyproject.toml` and queries real installed-package metadata (`docs/LICENSE_INVENTORY.md`, no GPL/AGPL direct dependency confirmed by test); `docs/THREAT_MODEL.md` (real assets/trust-boundaries/misuse-cases mapped to real controls, independent review honestly marked not done); `SECURITY.md` gained a response-owner/patch-cadence section; confirmed by 10 new tests, 100% coverage; blueprint coverage 223/374 -> 227/374 |
| PR-150 (NSD-01..13, first evidence) Neural stochastic differential equation subsystem, closing NSD at 13/13 | implemented locally | New `prometheus.neural_sde` package: a drift/diffusion network trained on the real, already-committed Kaggle macro snapshot (PR-145), with Cholesky-PSD diffusion, gradcheck-verified differentiable integration, point-in-time-safe dataset construction, CRPS/log-score/moment diagnostics, a multi-seed/multi-solver sensitivity study, real-2020-COVID-window OOD evaluation (no re-tuning, enforced structurally), NaN/gradient integrity-checked training, and a model card; two honest disclosed deviations (NSD-04's price-positivity reinterpreted as boundedness for this package's YoY-rate state variables; NSD-07's Heston substituted with GARCH(1,1) for the same reason); real result: neural SDE log-score degrades +5.58 under the real COVID shock vs. a GBM baseline's +29.97 -- regime-conditioning genuinely helps; independently reproduced end to end via `python -m prometheus.orchestration.neural_sde_run` before this entry was written; 62 new tests, 97% coverage; blueprint coverage 227/374 -> 240/374 |
| PR-151 (SEC-10, strengthened) Egress allowlist wired into both real connector call sites, closing PR-148's disclosed gap | implemented locally | `data_ingestion.egress_allowlist` gained `DEFAULT_INGESTION_ROUTING_TABLE`/`default_ingestion_transport()`; `orchestration.recessionnet_run`/`qmacro_run` now default to it instead of a bare `UrllibTransport()`; confirmed by monkeypatching the exact factory function per script (never a real network call) and asserting it was actually invoked and used to fetch data; closes the real, historical risk-acceptance exception registered in `evidence.risk_register`'s own worked example before its sunset date; 4 new tests, 100% coverage; blueprint coverage unchanged at 240/374 (SEC-10 was already counted; this strengthens, not adds, an ID) |
| PR-152 (PRV-01/02/03/05/07, first evidence) PII scan, data processing inventory, and extended license/entitlement register | implemented locally | `evidence.security_scan` gained `pii_scan` (SSN/email/phone/credit-card patterns), a real self-check finding zero PII in this repo's committed datasets, and a real caught-and-fixed false positive (a genuine `neural_sde` YoY value misflagged before the decimal-point exclusion was added); `docs/DATA_PROCESSING_INVENTORY.md` classifies every ingested series (all public aggregate); `docs/LICENSE_INVENTORY.md` extended with permitted-use/retention/redistribution terms per source and a model-weights/benchmark licensing section; 9 new tests, 100% coverage; blueprint coverage 240/374 -> 245/374 |
| PR-153 (PDE-01..12, first evidence) PDE/numerical-methods subsystem, closing PDE at 12/12 | implemented locally | New `prometheus.pde_solvers` package: a Crank-Nicolson finite-difference grid, a PINN (interior-residual + terminal/boundary/no-arbitrage losses), and a deep BSDE solver (causal per-step Z-subnetworks) for the Black-Scholes PDE and a correlated multi-asset basket generalization, cross-checked against `volterra.black_scholes`'s closed-form pricer and independent 200k-path Monte Carlo; two items (PDE-01, PDE-10) honestly marked partial -- the human-independent-review half of each is not claimed; real result: the classical grid wins outright where reachable (0.013s vs. PINN's 9.3s vs. deep BSDE's 11.4s in 1D, and most accurate), but its node count scales as M^d (200/40,000/8,000,000 at d=1/2/3) while deep BSDE's walltime stays ~flat across dimensions -- the actual justification for deep BSDE, demonstrated not asserted; a real measured fix during development cut a 58% no-arbitrage violation rate to ~17-20% via an added penalty term; 41 new tests, 97% coverage; blueprint coverage 245/374 -> 257/374 |
| PR-154 (MAR-01..14, first evidence) Multi-agent reinforcement learning subsystem, closing MAR at 14/14 | implemented locally | New `prometheus.marl` package: PPO-trained household/firm policies and rule-based bank/central-bank policies, all driven through the real `econosim.agents`/`core.ledger` infrastructure (its existing `InsufficientFundsError`/`CreditLimitExceededError` is the real feasibility backstop; a new projection guarantees a raw RL action can never even reach the ledger with an infeasible request); MAR-02 marked partial (peer review not claimed); a real reward-design bug (degenerate "spend everything" optimum) was caught by a direct numeric sweep and fixed with a bequest-value term before training was trusted, after which PPO discovered a genuinely better time-varying strategy beating every fixed-fraction baseline; real findings: co-learning is ~4-5x less stable than single-agent training, a real OOD wage shock degrades utility by ~8.7 (tight across seeds), and two real negative results (the reward bug, a PPO learning-rate collapse) are logged with reproducing tests; 65 new tests, 97% coverage; blueprint coverage 257/374 -> 271/374 |
| PR-155 (MGR-01/05/08/09/12/13, DRI-05/06/09/10/12, CMP-01/02/03) Model decommissioning/safe-shutdown, incident management, model inventory, compliance mapping | implemented locally | `evidence.model_serving` gained `deploy_if_not_retired` (MGR-12) and a fail-closed `mark_unhealthy`/`cached_predict` health gate (DRI-12); new `evidence.model_inventory` (MGR-01, every real trained-model family, self-checked against real importable modules); MGR-05/08/09 credited from pre-existing `model_card`/`champion_challenger`/`retraining_trigger`; MGR-13 and DRI-09 confirmed not-applicable (no pretrained weights; no multi-region deployment); new `evidence.incident_management` (DRI-05/06/10, the DRI-10 postmortem demonstrated against the real PR-141 incident); new `docs/compliance/{NIST_AI_RMF,NIST_SSDF,NIST_CSF}_MAPPING.md` (CMP-01/02/03, explicitly self-assessments, not certifications); 14 new tests, 100% coverage; blueprint coverage 271/374 -> 285/374 |
| PR-156 (CIQ-02, first evidence) GitHub branch protection enabled on main | configuration change | Confirmed via `gh api` that `main` had zero branch protection (HTTP 404) before any change; enabled required-status-check protection (`strict: true`, all 4 CI matrix contexts) with `enforce_admins: false` so the existing direct-push workflow keeps working; re-verified live via the same API call afterward; no corresponding test (a repository setting, not a code change); blueprint coverage 285/374 -> 286/374 |
| PR-157 (CIQ-07/12, LCH-01) Signed release provenance, breaking-change notices, release-scope crediting | implemented locally | New `evidence.release_provenance`: a real Ed25519 signature over a release provenance statement, verified with only the public key (independent of signing); a tampered statement and a wrong-key signature are both confirmed, by test, to fail verification; `service.deploy_manifest` gained `BreakingChangeNotice` (CIQ-12, required affected clients/change-log URL/maintenance window/owner approval); LCH-01 credited from the pre-existing `evidence/gate_report_r0.json`'s real `scope_prohibited` field, which already literally reads "Live trading, order routing, or any connection to a brokerage" -- marked partial since the current NO-GO gate has no approver signature to claim; 10 new tests, 100% coverage; blueprint coverage 286/374 -> 289/374 |
| PR-158 (VAL-10, CIQ-09/10, HDG-14, SEC-07/09, LCH-02/08, GOV-02/05/06/07/08/10/11/13/14) Statistical equivalence, shadow deployment, automatic rollback, RL hedging agent, governance/compliance crediting, closing HDG and VAL at 14/14 | implemented locally | `evidence.stochastic_equivalence` (no GPU here, disclosed; demonstrated via two independently-seeded real GBM runs confirmed statistically equivalent, plus a real negative control that is confirmed NOT equivalent); `evidence.deployment_paths` (a real shadow deployment that never serves the challenger's output; a real fault-injected automatic rollback within a measured recovery target); `hedging.rl_agent` (a REINFORCE hedging agent, refuses to train without a real finite static baseline, risk-bounded by construction, real disclosed finding: underperforms the static baseline at this training budget, consistent with this session's recurring "simple beats quickly-trained learned" pattern); SEC-09/LCH-08 credited from pre-existing `release_provenance`/`security_scan`; SEC-07/LCH-02 partial (real SBOM/dependency-lock, N/A pieces named); 9 new `docs/governance/` documents closing or partially closing GOV-02/05/06/07/08/10/11/13/14; 19 new tests, 98-100% coverage; blueprint coverage 289/374 -> 306/374 |
| PR-159 (UIX-01..12, first evidence) Research dashboard subsystem, closing UIX at 11/12 (1 partial) | implemented locally | New `prometheus.dashboard` package: a real, separate, authenticated ASGI service reusing `service.auth` unchanged, rendering server-rendered HTML views driven by real subsystem output (`econosim`/ledger, `stochastica.gbm`, `volterra.black_scholes`, `hedging.baseline`, `titan.risk_metrics`) with no new frontend dependency; UIX-10's authorization is a real end-to-end ASGI round trip (Bob's own valid token genuinely refused, HTTP 403, on Alice's real portfolio); UIX-07's comparison view renders the real PR-142/143 "NOT SIGNIFICANT" verdicts alongside PR-150's real win, not a wins-only tile; UIX-09/UIX-12 disclose real scope limits (a test-constructed audit entry since nothing is really promoted under this project's NO-GO status; no new PDF-rendering dependency); UIX-11 split honestly into 5 real automated accessibility checks vs. 5 items in a new test plan explicitly marked as needing a real browser/human; two real bugs (an accessibility-regex quoting bug, a false-failure test assertion) caught and fixed during development; 38 new tests, 98% coverage; blueprint coverage 306/374 -> 318/374 |
| PR-160 (PRV-09/11/12, SEC-12, LCH-04/05/07/10) Data-sharing access grants, a real versioned-rollback demonstration, and further crediting | implemented locally | `dashboard.auth.PortfolioShareRegistry` extended with a real `ShareGrant` record (requester/owner/expiry/justification, all required) and a real audit-only `is_expired_as_of` check explicitly NOT wired into live authorization; a new end-to-end test demonstrates LCH-10 (canary rollback + audit chain) by composing `ShadowDeployment`, `ModelRegistryEntry`, and `deploy_if_not_retired` with zero new primitives; PRV-09/11, SEC-12, LCH-04/05/07 credited (several partial, exact missing human-sign-off half named in each) from pre-existing `dashboard.provenance`, `security_scan`, `DATA_PROCESSING_INVENTORY.md`, `runbook_catalog`/`incident_management`, and `cost_benchmark`/`soak_test`/`scale_benchmark`/`AutoRollbackMonitor`; 4 new tests, 100% coverage; blueprint coverage 318/374 -> 326/374 |
| PR-161 (strengthens UIX-01/03/05/06/09/12) Dashboard live-wiring, a real ASGI lifespan bug caught by actually running the server, and research/portfolio documentation | implemented locally | Prompted by a direct request to verify real-world usability, not just test coverage. Found and fixed two real gaps invisible to `pytest` alone: 5 already-unit-tested dashboard views were never wired into the live ASGI route table (now reachable at real routes, plus a new `/dashboard/export` and index page); and a real ASGI lifespan-protocol bug crashed real server startup (`python -m prometheus.dashboard serve`, a new CLI entry point added this PR) because no existing test constructed a `"lifespan"` scope -- fixed by reusing `service.application.ResearchService`'s own working handler, verified by actually starting the server and hitting all 10 real routes with real HTTP requests (genuine 403/401 included), with a new regression test driving the real lifespan protocol directly. New `docs/RESEARCH_CONTRIBUTIONS.md` (5 research questions, 3 "not supported," 1 "partially supported," 1 "supported") and `docs/PORTFOLIO_DEMO.md` (a real 10-minute evaluation sequence). No new blueprint IDs claimed -- strengthens existing UIX evidence from unit-tested to live-reachable. 14 new tests, 93-100% coverage |
| PR-162 (no new blueprint ID) AI-assisted adversarial audit of the NSD/PDE/MAR/HDG deep-learning subsystems; one real bug found and fixed | implemented locally | Independent re-verification re-derived every headline NSD/PDE/MAR number from scratch (re-running real code, not trusting existing tests) and found those three subsystems clean, matching to full precision or within expected noise. A real, previously-undiagnosed bug WAS found in `hedging.rl_agent` (HDG-14): `dist.rsample()` instead of `dist.sample()` for the REINFORCE log-probability is mathematically fatal for a location-scale policy -- the reparameterized sample's dependence on `mu` exactly cancels `log_prob`'s direct dependence on it, so the policy's mean-head gradient was IDENTICALLY zero (confirmed independently twice: `grad.norm()` exactly 0.0 before, nonzero after), silently preventing the policy from ever learning state-dependent behavior while training ran without any error. Fixed with a one-line change plus a new permanent regression test driving the exact mechanism. Re-verified post-fix: the already-published conclusion ("REINFORCE does not beat the static baseline") is unchanged -- now correct for the genuine reason (real CVaR 9.17 vs. 40.58 at the same config) rather than a broken gradient. AI-assisted self-audit, explicitly not independent human review. 1 new test, 100% coverage on the changed file |
| PR-163 (PRV-04/08, SEC-11, LCH-06, MGR-04) Data retention schedule, a consolidated model validation report, and further crediting | implemented locally | `evidence.data_retention`: a real schedule naming this repo's actual data categories, including deliberate INDEFINITE retention for reproducibility artifacts (not an unset field) and a real automated `is_past_retention` check for bounded categories; PRV-08 confirmed not-applicable (no real vendor relationship exists); SEC-11 credited from pre-existing `service.application.Admission` rate/quota enforcement and its real burst-rejection-and-recovery test (REL-10); LCH-06 credited, partial, from the real DRI-08 drill plus `RecoveryLimits.operation_seconds`'s enforced (tested) 60-second RTO budget; new `evidence.model_validation_report` compiles one real validation record per active `model_inventory` entry, each citing the exact real backtest/calibration evidence already in this repository rather than re-deriving it; 12 new tests, 100% coverage; blueprint coverage 326/374 -> 331/374 |
| PR-164 (SEC-13, LCH-11) Final crediting pass | implemented locally | SEC-13 credited from pre-existing `evidence.failover_audit_continuity.restore_registry_entry`, which re-applies every restored model-registry transition through the real `ModelRegistryEntry.transition` call -- re-enforcing the real promotion policy during restore, not just replaying bytes -- and its real `test_a_tampered_history_order_fails_to_restore_rather_than_silently_round_tripping` test (DRI-11), literally this item's own acceptance claim; LCH-11 credited, partial, from the real, consistent `SIMULATION_DISCLAIMER` wording already shipped across README/dashboard/governance docs (human approval not claimed). No new code; blueprint coverage 331/374 -> 333/374 (89.0%) |
| PR-165 (SEC-02, MGR-11, MGR-06, MGR-10, SEC-06, CMP-11) Branch-rule tightening, model-usage authorization, model-dependency risk, a real validation issue tracker, and further crediting | implemented locally | SEC-02 partial: `main`'s live GitHub branch protection now requires one approving PR review (stale reviews dismissed) in addition to existing status checks, confirmed via `gh api`; commit signing and admin-enforcement remain disabled (named gap). New `evidence.model_inventory.authorize_model_usage`/`UnauthorizedModelUsageError` (MGR-11): every inventory entry now carries a real `authorized_applications` set, wired into a live, rejectable `/dashboard/model-usage` HTTP route (real 403 on an unsupported application or unknown model). New `evidence.model_dependency_risk` (MGR-06): traces the real dependency between the grid PDE solver's Delta and the shared self-financing hedge simulator (HDG-13), running the substitution through the real simulator twice to show how PDE-08's own local Delta error propagates into a shift in the downstream, aggregate portfolio Expected Shortfall -- confirmed directionally consistent (a coarser grid produces both a larger local error and a larger aggregate shift) on identical simulated paths. New `evidence.validation_issue_tracker` (MGR-10): records the two real defects found and fixed earlier this session (the REINFORCE `rsample()` bug, PR-162; the dashboard ASGI lifespan crash, PR-161) as real findings with severity/owner/expiry/disposition, each citing its real regression test, wired into a live `/dashboard/validation-issues` view. SEC-06 credited from pre-existing `security_scan.secret_scan` plus the real credential-rotation drill test; CMP-11 credited, partial, from pre-existing `evidence.data_retention` (schedule signature not claimed). 19 new tests, 100% coverage on new code; blueprint coverage 333/374 -> 339/374 (90.6%) |
| PR-166 (CIQ-08, GOV-03, EXP-14) Two-person approval enforcement, a RACI register, and a replication digest -- closing CIQ, EXP and GOV at 100% | implemented locally | CIQ-08 partial: `evidence.model_registry.promote_to_approved` now rejects a self-approved promotion (`approved_by == actor`) with a new `SinglePersonApprovalError`, checked before provenance/validation -- the identity-distinctness enforcement this module's own docstring previously disclosed as deliberately not claimed; real second-human authentication still not claimed. New `evidence.raci_register` (GOV-03, partial): a real `RACIEntry` per required domain (technical/scientific/security/risk) naming the real project-maintainer role as accountable owner, `verify_raci_register` checked against the exact four named domains; every entry's deputy is explicitly `None` (single-maintainer, no second identity to name). New `evidence.replication_digest` (EXP-14, partial): formalizes PR-162's adversarial audit pass as structured, checkable data -- one real `ReplicationRecord` per re-verified subsystem (NSD, PDE, MAR) with the original claim, the independent rerun's result, and a liveness check that every cited module still imports; every record honestly labeled `internal_ai_assisted`, not external. 12 new tests, 100% coverage on new code; blueprint coverage 339/374 -> 342/374 (91.4%) |
| PR-167 (LCH-03, SEC-03, MGR-02, CMP-05, CMP-09) A real P0-findings check, an honest access review, a theoretical-assumptions record, and a BCBS 239 mapping | implemented locally | LCH-03 partial: new `evidence.validation_issue_tracker.open_p0_findings` reuses `alert_routing.canonical_severity`'s own P0/P1/P2 taxonomy and confirms the one P0-severity finding on record (the REINFORCE gradient bug) is remediated, not open. SEC-03 partial: new `evidence.access_review` records a real, dated GitHub collaborator snapshot (exactly one admin, the repository owner), trivially satisfying least-privilege for a single-maintainer repository; MFA/audit-log enforcement named as unavailable via any API for a personal-account repo, not claimed. MGR-02 partial: new `evidence.theoretical_assumptions` compiles the real theoretical assumption already documented in three subsystems (Black-Scholes, PDE solvers, hedging REINFORCE), reusing EXP-14's same audit evidence for "independent reviewer evaluates mathematical logic" (honestly `internal_ai_assisted`). CMP-05: new `docs/compliance/BCBS_239_MAPPING.md`, following the same self-assessment framing as `NIST_CSF_MAPPING.md`, mapping accuracy/completeness/timeliness onto 11 pre-existing, individually re-confirmed passing tests (ledger reconciliation, schema-contract quarantining, point-in-time leak detection). CMP-09 (not-applicable confirmed): the real `evidence/gate_report_r0.json` NO-GO decision plus EXT's own 0-repository-note status confirm no market access is planned, so its conditional trigger never fires. 13 new tests, 100% coverage on new code; blueprint coverage 342/374 -> 347/374 (92.8%) |
| PR-168 (LCH-09, MGR-03) Real controlled UAT, and a real recessionnet labeling bug found and fixed by an independent data assessment -- closing LCH at 100% | implemented locally | LCH-09 partial: new `evidence.user_acceptance` records 9 real cases executed against a REAL, live `python -m prometheus.dashboard serve` process (genuine uvicorn, real HTTP requests over the network), playing an analyst persona (economy/pricing/experiments/portfolio-risk) and a reviewer persona (audit-trail/validation-issues/model-usage-authorization/cross-tenant-access) with two distinct real credentials; all 9 passed; a regression test re-exercises the same 9 scenarios via the in-process ASGI harness on every CI run. MGR-03: new `evidence.independent_data_assessment` independently re-derives (via separately-written code, never calling the production functions) train/test eligibility and recession labels from the same real Kenneth French factor history and real NBER chronology, then cross-checks against the real pipeline. **This independent assessment found and fixed a real, previously-undiagnosed bug**: `recessionnet.labels.RecessionPeriod.contains_contraction_month` compared NBER table dates (stored as first-of-month) directly against the dataset pipeline's end-of-month query dates, silently including every recession's PEAK month (should be excluded) and excluding every TROUGH month (should be included) -- mislabeling 31 real target months, invisible to existing unit tests because they all happened to query at first-of-month too. Fixed by comparing at (year, month) granularity; all 94 recessionnet-related tests still pass; a new regression test drives the real 1929 Great Depression boundary months at both day conventions. 12 new tests, 100% coverage on new code, plus one real bug fixed in previously-shipped code; blueprint coverage 347/374 -> 349/374 (93.3%) |
| PR-169 (no new blueprint ID) 11 committed reference bundles had gone silently stale; all fixed, with a permanent regression test | implemented locally | Prompted by a direct request to make sure the demo interface genuinely works. Actually running the exact one-command smoke test README.md/CONTRIBUTING.md/PORTFOLIO_DEMO.md all advertise (`python -m prometheus.orchestration.replay evidence/api_reference.json --require-integrity ...`) failed outright: `RunManifest` had gained `model_id`/`code_hash`/`data_hash` fields since the file was last regenerated, and the schema check requires an exact field-set match. Checking every other committed, plain-named reference bundle found the identical staleness in all 10 of the others -- invisible to this project's own 2,819 other tests, since none of them replay the actual committed files. Fix: all 11 regenerated via the real `execute_recipe`/`export_evidence_bundle` pipeline from each file's own recorded config; 6 came back byte-identical (pure schema-currency fixes), 5 recomputed to a different (but independently confirmed deterministic, and full-suite-consistent) hash -- legitimate drift from real, already-disclosed `econosim`/monetary changes across ~150 PRs since 2026-11-02/03, the same "stale reference, refresh it" precedent already documented for PR-015/016, simply never repeated since. Paired `*_replay.json` files regenerated the same way. New parametrized regression test (`test_replay.py`, 11 cases) runs on every CI pass so this cannot silently recur. Strengthens AUD/DOC's existing reproducibility evidence; claims no new blueprint ID |
| PR-170 (no new blueprint ID) Scientific-rigor documentation pass | implemented locally | `docs/RESULTS_AND_LIMITATIONS.md`'s "known limitations" section had gone factually wrong on three of its four bullets (still claiming no neural-SDE/PDE solver, no multi-agent RL, no product dashboard existed, all dating to PR-146, when NSD/PDE/MAR/UIX have since been fully built). Replaced with accurate current scope and added Findings 5-10: the neural-SDE OOD-robustness result, the PDE solver crossover, the MAR reward-design catch, and -- as genuine negative findings -- the REINFORCE gradient bug, the recessionnet boundary-month labeling bug, and PR-169's own stale-reference-bundle finding. `docs/RESEARCH_CONTRIBUTIONS.md`'s stale "326/374" corrected to 349/374, plus a new paragraph naming the recurring "test shares its production code's own blind spot" pattern explicitly across all four bugs found this session. No new blueprint ID; documentation-only |
| PR-171 (CMP-10, CMP-12) A marketing-claims scan, and a vendor risk catalogue | implemented locally | CMP-12 partial: new `evidence.security_scan.claims_scan` composes with the existing `secret_scan`/`license_scan`/`pii_scan` pattern, matching a denylist naming exactly what this item's acceptance text names (guaranteed-return/risk-free-profit claims, SEC/FINRA/CFTC/FCA/SIPC/FDIC approval claims, FDIC-insurance claims) against a real sweep of this repository's own README/docs tree, confirmed zero matches; human review of marketing copy not claimed. CMP-10: new `docs/compliance/VENDOR_RISK_CATALOGUE.md` extends PRV-08's already-confirmed "no paid data vendor" finding to this repository's actual infrastructure dependencies (GitHub hosting, the PyPI/Python package ecosystem), with concentration risk and exit plans named explicitly and due diligence citing the already-real `LICENSE_INVENTORY.md`/`security_scan`; no new code. 9 new tests, 100% coverage on new code; blueprint coverage 349/374 -> 351/374 (93.9%) |
| PR-172 (FP-01, FP-17, FP-18, FP-21) FP-01..FP-24 final-project addendum audit -- stale since PR-143 | implemented locally | Prompted directly by a request to reconcile this exact checklist for a course final-project submission. Found the addendum's own FP section had gone stale for ~28 PRs, including one row (FP-21) that was flatly wrong ("no dashboard exists" when the real UIX dashboard has shipped since PR-159). FP-01: new `docs/FINAL_PROJECT_HYPOTHESES.md` freezes a title and five falsifiable hypotheses (H1-H5) against the existing RQ1-RQ5 findings, honestly disclosed as a RETROSPECTIVE freeze, not prospective pre-registration. FP-17: corrected -- RECESSIONNET/Q-MACRO have enforced disjoint chronological train/validation/test splits since PR-139/143, confirmed by pre-existing tests. FP-18: corrected, and genuinely strengthened rather than just relabeled -- "confidence intervals" was already tested, but "multiple seeds" had only ever been a one-off manual check; new `orchestration.recessionnet_run.multi_seed_recessionnet_summary` (reuses `run_recessionnet_demo` unchanged) plus a real multi-seed regression test now makes this a committed, re-runnable artifact (5/5 seeds currently inconclusive, slightly stronger than the historical "4 of 5" after PR-168's labeling-bug fix). FP-21: corrected, and also genuinely strengthened -- `dashboard.provenance.real_data_badge` turned out to have NO test coverage anywhere despite being used in real production code; new `test_dashboard_provenance.py` plus a new production-wiring assertion close that gap for real. Also flags the addendum's own Tier-A/Tier-B framing clearly: INFLATIONCAST (mandatory) does not exist at all; POLICYLAB-RL is a policy-RATE PPO agent, explicitly NOT the same subsystem as `marl`'s household/firm PPO work, a distinction now stated to prevent future confusion. 8 new tests, 100% coverage on new code; no change to the 374-item blueprint count (the FP addendum is tracked separately) |

**What this does and does not mean.** "Done" means: implemented, covered
by automated tests, with ruff/mypy --strict checks,
and cross-checked against closed-form or exact references wherever one
exists rather than an arbitrary tolerance. It does not mean the blueprint's
374-item checklist is anywhere near complete — `CHECKLIST_STATUS.md` lists
189 distinct blueprint checklist IDs with some test evidence, including partial
implementations and IDs reused across slices. Table-row counts double-count
those reused IDs; they are not a completion percentage. The separate risk-register
entry R-03 is excluded; PR-021 adds partial HDG-10 evidence to PR-020's corrected count of 69.
PR-022 adds the first evidence for PRI-05 (risk-neutral calibration), previously unevidenced.
PR-049 adds the first evidence anywhere in this repository for LED-07 (multi-creditor
insolvency), previously unevidenced. PR-051 adds the first evidence for PRI-04 (Heston
Fourier pricer) and partial evidence for VAL-14, both previously unevidenced. PR-052 adds
the first evidence for SDE-08 (Merton jump-diffusion), previously unevidenced. PR-053 adds
the first evidence for PRI-08 (barrier options), previously unevidenced. PR-054 adds the
first evidence for PRI-09 (Asian options), previously unevidenced. PR-055 strengthens the
already-evidenced DAT-07 (partial) rather than adding a new ID to this 374-item count; its
new coverage is tracked separately under the FP-01..FP-24 addendum checklist in
`CHECKLIST_STATUS.md`, which is not part of this count. PR-056 likewise adds no
original-blueprint ID (its FP-04 coverage is addendum-only) -- see `CHECKLIST_STATUS.md`'s
PR-056 section for an honest account of an initial, incorrect VAL-01/VAL-03/VAL-14 tagging
attempt that was caught and corrected before being committed anywhere permanent. PR-057 adds
the first evidence for SDE-05 and VAL-03 (a genuine match this time -- a Heston weak-
convergence study really is a stochastic-integrator convergence check), bringing the count
from 124 to 126, confirmed by regenerating the register and checking the jump was exactly 2
before trusting it. PR-057 also corrects two FP-NN addendum rows (FP-12, FP-16) that an audit
found to be over-credited -- see `CHECKLIST_STATUS.md`'s PR-057 section for the full account.
PR-058 adds no new ID to this 374-item count (it strengthens the already-evidenced PRI-07
and VAL-05 by extending Greeks coverage to four more pricers) but closes the FP-12 addendum
gap PR-057's audit found. PR-059 adds the first evidence anywhere in this repository for
PRI-10 (portfolio-level Greeks aggregation), previously unevidenced, bringing the count
from 126 to 127. PR-060 strengthens the already-evidenced DAT-07 and adds the first
evidence anywhere in this repository for DAT-08 (narrowly -- the "no forward-fill without
justification" clause only), bringing the count from 127 to 128; DAT-01/02/06/12/13/14 are
deliberately NOT claimed despite being adjacent to this PR's own subject matter.
PR-061 adds the first evidence anywhere in this repository for SDE-12 and VAL-13, both
explicitly left open since PR-057, bringing the count from 128 to 130, confirmed by
regenerating the register and checking the jump was exactly 2 before trusting it. PR-062
adds the first evidence for SDE-11, the last item from that same PR-057 note, bringing the
count from 130 to 131, confirmed the same way. PR-063 correctly closes VAL-01 and VAL-02,
both left open since the VAL-01/03/14 misattempt several PRs ago (VAL-03 was separately
closed correctly by PR-057), bringing the count from 131 to 133, confirmed the same way.
PR-064 adds the first evidence for VAL-11, bringing the count from 133 to 134, confirmed the
same way; writing it also found and fixed a 6th real crash (Merton's jump_intensity=0.0).
PR-065 adds the first evidence for VAL-08, bringing the count from 134 to 135, confirmed the
same way -- an audit of every mutating method in econosim.agents, not new production code.
PR-066 adds the first evidence for SDE-06, bringing the count from 135 to 136, confirmed the
same way -- a genuinely new STOCHASTICA model (regime-switching), not just tests/docs.
PR-067 adds the first evidence for SDE-07, bringing the count from 136 to 137, confirmed the
same way -- another new STOCHASTICA model (GARCH(1,1) volatility clustering).
PR-068 adds the first evidence for OPT-08, bringing the count from 137 to 138, confirmed the
same way -- an explicit train/test split comparison built on the existing TITAN optimizer.
PR-069 adds the first evidence for ECO-10, bringing the count from 138 to 139, confirmed the
same way -- an audit of the pre-existing econosim.insolvency module, plus one new test.
PR-070 adds the first evidence for LED-09, bringing the count from 139 to 140, confirmed the
same way -- genuinely new functionality (a bid/ask spread and liquidity cost model), not an audit.
PR-071 adds the first evidence for LED-10, bringing the count from 140 to 141, confirmed the
same way -- a companion module tracking trade execution/settlement event ordering.
PR-072 adds the first evidence for LED-03, bringing the count from 141 to 142, confirmed the
same way -- a third companion module, enforcing inventory nonnegativity with structured errors.
PR-073 adds the first evidence for LED-04, bringing the count from 142 to 143, confirmed the
same way -- a fourth companion module, independently reconciling equity rollforwards.
PR-074 adds the first evidence for RISK-09, bringing the count from 143 to 144, confirmed the
same way -- ES-specific backtesting/calibration diagnostics beyond the pre-existing VaR coverage test.
PR-075 adds the first evidence for ECO-11, bringing the count from 144 to 145, confirmed the
same way -- an audit of pre-existing InterbankMarket/CentralBankLedger code, plus one new test file.
PR-076 adds the first evidence for EXP-09, bringing the count from 145 to 146, confirmed the
same way -- a new moving block bootstrap module, verified against an exactly-known AR(1) ground truth.
PR-077 adds the first evidence for OPT-06, bringing the count from 146 to 147, confirmed the
same way -- a new per-asset liquidity-cap field threaded through all three portfolio optimizers.
PR-078 adds the first evidence for HDG-07, bringing the count from 147 to 148, confirmed the
same way -- a new leverage/position-size projection module, verified by a Hypothesis property sweep.
PR-079 adds the first evidence for ECO-15, bringing the count from 148 to 149, confirmed the
same way -- a new GDP/inflation/credit module, cross-validated against a real Economy scenario.
PR-080 adds the first evidence for DAT-09, bringing the count from 149 to 150, confirmed the
same way -- a new automated leakage linter, the detective complement to econosim.pit's existing gate.
PR-081 adds the first evidence for API-05, bringing the count from 150 to 151, confirmed the
same way -- new immutable pricing/risk report response types referencing market snapshots.
PR-082 adds the first evidence for LED-08, bringing the count from 151 to 152, confirmed the
same way -- an audit against the narrow acceptance criterion, plus one new three-bank test.
PR-083 adds the first evidence for SDE-10, bringing the count from 152 to 153, confirmed the
same way -- a new closed-form GBM calibration module with dated, point-in-time-queryable versions.
PR-084 adds the first evidence for VAL-12, bringing the count from 153 to 154, confirmed the
same way -- required per-field API tolerances plus violation checks, and a 7th SDE-12-adjacent
barrier-pricer overflow fix found while re-verifying the full suite.
PR-085 adds the first evidence for EXP-04, bringing the count from 154 to 155, confirmed the
same way -- a content-addressed, order-independent holdout manifest that locks regime cutoffs.
PR-086 adds the first evidence for EXP-05, bringing the count from 155 to 156, confirmed the
same way -- a future-data leakage diagnostic with an isinstance-based scoreboard-isolation guard.
PR-087 adds the first evidence for EXP-11, bringing the count from 156 to 157, confirmed the
same way -- hardware/GPU-driver/dtype/walltime fields, honestly empty on this CPU-only machine.
PR-088 adds the first evidence for AUD-04, bringing the count from 157 to 158, confirmed the
same way -- a required measure field on every report, independent of MarketSnapshot's own.
PR-089 adds the first evidence for AUD-12, bringing the count from 158 to 159, confirmed the
same way -- a result inventory demonstrated against this repository's own real GARCH-abandonment history.
PR-090 adds the first evidence for AUD-05, bringing the count from 159 to 160, confirmed the
same way -- a domain-agnostic decision audit log demonstrated against real hedge and agent calls.
PR-091 adds the first evidence for AUD-09, bringing the count from 160 to 161, confirmed the
same way -- risk reports recomputed from raw losses via titan.risk_metrics's own documented formulas.
PR-092 adds the first evidence for AUD-03, bringing the count from 161 to 162, confirmed the
same way -- a training provenance manifest replayed bit-identically against a real deep_hedge run.
PR-093 adds the first evidence for CIQ-11, bringing the count from 162 to 163, confirmed the
same way -- a deploy manifest that recreates a real, non-default ServicePolicy field for field.
PR-094 adds the first evidence for CIQ-05, bringing the count from 163 to 164, confirmed the
same way -- secret scanning plus a scanner-agnostic severity-gated release decision.
PR-095 adds the first evidence for DAT-11, bringing the count from 164 to 165, confirmed the
same way -- per-series freshness/completeness/duplicate/revision monitoring.
PR-096 adds the first evidence for DAT-12, bringing the count from 165 to 166, confirmed the
same way -- dataset fingerprinting demonstrated against a real GBM-price-to-log-return reproduction.
PR-097 adds the first evidence for REL-10, bringing the count from 166 to 167, confirmed the
same way -- an audit of pre-existing quota rejection codes, made explicit by one new test.
PR-098 adds the first evidence for MLO-08 and MLO-10, bringing the count from 167 to 169,
confirmed the same way -- a model registry state machine plus a promotion gate reusing AUD-03.
PR-099 adds the first evidence for MLO-07, bringing the count from 169 to 170, confirmed the
same way -- content-hashed model packages grounded in a real torch.save'd HedgePolicyMLP artifact.
PR-100 adds the first evidence for MLO-12, bringing the count from 170 to 171, confirmed the
same way -- controlled rollback with a selective, content-hash-keyed stale-cache purge.
PR-101 adds the first evidence for MLO-06, bringing the count from 171 to 172, confirmed the
same way -- early stopping that structurally forbids the test regime, reusing EXP-04.
PR-102 adds the first evidence for MLO-14, bringing the count from 172 to 173, confirmed the
same way -- a champion/challenger report grounded in a real delta-hedge-vs-no-trade-band comparison.
PR-103 adds the first evidence for REL-11, bringing the count from 173 to 174, confirmed the
same way -- an audit of pre-existing backup/restore code, made explicit by one new test.
PR-104 adds the first evidence for AUD-06, bringing the count from 174 to 175, confirmed the
same way -- required approval and promotion-hash fields added to every registry transition.
PR-105 adds the first evidence for OPS-01, bringing the count from 175 to 176, confirmed the
same way -- a dependency map parsed from this repository's own real imports via ast.
PR-106 adds the first evidence for REL-03, bringing the count from 176 to 177, confirmed the
same way -- real small/medium/large GBM benchmark curves plus a published budget check.
PR-107 adds the first evidence for DAT-14, bringing the count from 177 to 178, confirmed the
same way -- dataset cards grounded in a real GBM simulation and a real World Bank fixture.
PR-108 adds the first evidence for DAT-06, bringing the count from 178 to 179, confirmed the
same way -- per-key immutable storage layers with a strict read-permission pipeline.
PR-109 adds the first evidence for DAT-10, bringing the count from 179 to 180, confirmed the
same way -- quarantine-based schema contracts plus exact unit normalization and currency mapping.
PR-110 adds the first evidence for MLO-13, bringing the count from 180 to 181, confirmed the
same way -- pre-registered retraining thresholds demonstrated against real RISK-09 p-values.
PR-111 adds the first evidence for AUD-07, bringing the count from 181 to 182, confirmed the
same way -- a tamper-evident hash-chained log reusing jobs.store's own chaining technique.
PR-112 adds the first evidence for REL-02, bringing the count from 182 to 183, confirmed the
same way -- a real concurrent load test against ResearchService's own ASGI metadata endpoint.
PR-113 adds the first evidence for REL-09, bringing the count from 183 to 184, confirmed the
same way -- a real 60-iteration GBM soak test with deliberate-leak and bad-iteration discrimination.
PR-114 adds the first evidence for REL-01, bringing the count from 184 to 185, confirmed the
same way -- an SLO definition that closes the loop with REL-02's own real load report.
PR-115 adds the first evidence for MLO-11, bringing the count from 185 to 186, confirmed the
same way -- reproducible inference grounded in a real, deterministically-seeded HedgePolicyMLP.
PR-116 adds the first evidence for MLO-03, bringing the count from 186 to 187, confirmed the
same way -- dataset provenance composed from four existing primitives rather than reinvented.
PR-117 adds the first evidence for MLO-04 and MLO-05, bringing the count from 187 to 189,
confirmed the same way -- checkpoint/resume reproduces training bit-for-bit, plus a real gradient log.
PR-118 adds the first evidence for DAT-05, bringing the count from 189 to 190, confirmed the
same way -- a real captured Kenneth French factor response, parsed and fed through PointInTimeStore.
PR-119 adds the first evidence for DAT-01, bringing the count from 190 to 191, confirmed the
same way -- an ast-derived source catalog finding both real connectors' actual URL/license strings.
PR-120 adds the first evidence for SEC-08, bringing the count from 191 to 192, confirmed the
same way -- zip-slip and decompression-bomb rejection grounded in real archives, plus a Hypothesis fuzz test.
PR-121 adds the first evidence for DAT-13, bringing the count from 192 to 193, confirmed the
same way -- a real zero-finding license scan of this repository's own tracked source tree.
PR-122 adds the first evidence for OPS-04, bringing the count from 193 to 194, confirmed the
same way -- a real JobStore lifecycle with a deterministic clock reproducing exact queue metrics.
PR-123 adds the first evidence for OPS-05, bringing the count from 194 to 195, confirmed the
same way -- exact failure-rate discrimination across two real, genuinely different backends.
PR-124 adds the first evidence for OPS-06, bringing the count from 195 to 196, confirmed the
same way -- a real alert exercise against the real captured Kenneth French archive.
PR-125 adds the first evidence for OPS-07, bringing the count from 196 to 197, confirmed the
same way -- a real extreme-drift GBM solver failure and a real Monte-Carlo-vs-closed-form check.
PR-126 adds the first evidence for OPS-08, bringing the count from 197 to 198, confirmed the
same way -- three composed real signals, each confirmed to fire and not-fire against real data.
PR-127 adds the first evidence for OPS-09, bringing the count from 198 to 199, confirmed the
same way -- real CPU/RAM/artifact-storage tracking and an exact linear capacity forecast.
PR-128 adds the first evidence for OPS-10, bringing the count from 199 to 200, confirmed the
same way -- three real existing signal sources each routed end-to-end to a configured owner.
PR-129 adds the first evidence for DRI-01, bringing the count from 200 to 201, confirmed the
same way -- a genuine gap-detection raise for a real, deliberately-unconfigured error code.
PR-130 adds the first evidence for DRI-02, bringing the count from 201 to 202, confirmed the
same way -- a real flaky callable recovering and a real persistently-failing guard still failing.
PR-131 adds the first evidence for DRI-03, bringing the count from 202 to 203, confirmed the
same way -- a real end-to-end credential rotation against CredentialStore, old rejected, new accepted.
PR-132 adds the first evidence for DRI-04, bringing the count from 203 to 204, confirmed the
same way -- a real leaked run detected and a real recomputation producing a different, correct result.
PR-133 adds the first evidence for DRI-11, bringing the count from 204 to 205, confirmed the
same way -- a real snapshot/restore round trip and a real model-approval history round trip.
PR-134 adds the first evidence for OPS-11, bringing the count from 205 to 206, confirmed the
same way -- two distinct real failure categories each with a real timeline and genuine pass/fail.
PR-135 adds the first evidence for OPS-12, bringing the count from 206 to 207, confirmed the
same way -- a real zero-finding vendor sweep and a real ast-derived audit-log schema check,
closing the OPS category at 100% (12/12), the project's 9th complete category.
PR-136 adds the first evidence for REL-12, bringing the count from 207 to 208, confirmed the
same way -- an exact real breach-rate count genuinely blocking and unblocking the existing gate.
PR-137 adds the first evidence for REL-08, bringing the count from 208 to 209, confirmed the
same way -- an identical bounded combination count at two real volumes, versus a real unbounded one,
closing the REL category at 100% (12/12), the project's 10th complete category.
PR-138 adds the first evidence for AUD-10, bringing the count from 209 to 210, confirmed the
same way -- a real table linked to a real script, with genuine script- and data-tamper detection,
closing the AUD category at 100% (12/12), the project's 11th complete category.
PR-139 adds no new 374-item ID (the count stays at 210) -- it builds RECESSIONNET and closes
FP-06 and FP-20 of the separate ECONOSIM-X final-project addendum, plus a new sibling
`prometheus.quantum` package answering a user-supplied quantum-ML blueprint; see
`CHECKLIST_STATUS.md`'s addendum section and this file's own PR-139 entry above for the real,
honest (negative) benchmark result.
PR-140 adds no new 374-item ID -- a runnable `orchestration.recessionnet_run` CLI demo of
PR-139's benchmark, hermetically tested via an injectable transport.
PR-141 adds no new 374-item ID -- fixes a real angle-embedding gradient-dead-zone bug in
PR-139's hybrid quantum classifier (diagnosed from its own calibration-slope diagnostic),
improving its test AUC from ~0.61 to ~0.70 but not changing the qualitative finding: it still
loses to logistic regression at a 300-epoch budget and is statistically tied with it (not
ahead) at 150 epochs.
PR-142 adds no new 374-item ID -- diagnosed and fixed a SECOND, more consequential problem:
PR-139/141's fixed epoch budget let the quantum/classical-MLP models overfit while logistic
regression did not, which was not a fair comparison. Validation-selected early stopping
(never the test set) reverses the earlier "quantum is robustly worse" conclusion to "neither
model is significantly better than the other" on this task -- a correction to the evaluation
methodology, not the model, reached before being satisfied with the earlier result.
PR-143 strengthens the PARTIAL FP-05 addendum row (not a new 374-item ID): Q-MACRO's hybrid
quantum regressor vs. AR(3)/classical-MLP/persistence for h-months-ahead Mkt-RF, applying
PR-142's early-stopping methodology from the start. Independently reproduces RECESSIONNET's
own "neither better nor worse" finding on a genuinely different task (regression) and target.
PR-144 adds no new 374-item ID -- demo-reliability hardening: an offline-fallback data
snapshot for both orchestration CLIs (verified under a simulated network outage) and
switching recessionnet_run to the early-stopping methodology qmacro_run already used,
roughly halving its wall-clock time and correcting its result to the already-validated
"inconclusive" finding.
PR-145 adds no new 374-item ID (not DAT-02/03/04 -- those have narrower, specific
acceptance criteria this Kaggle mirror does not meet) -- a second, independent real-data
grounding for RECESSIONNET using real Kaggle-sourced US GDP/claims/Fed-funds/M2/NASDAQ
data, with a network-free demo CLI and the same "no significant quantum difference"
finding independently reproduced on a genuinely different real dataset.
PR-146 closes DAT-04 (first evidence) with a real US Treasury par yield curve
connector via FRED's no-key CSV export (home.treasury.gov itself was unreachable from
this environment); day-count conventions are recorded as a typed value and holiday
policy is derived from real data gaps, confirmed against three real closures including
a Good-Friday/non-federal-holiday discriminating case, plus two further real-world
sanity checks (the 2006 2y/10y inversion and the 2020 COVID zero-rate cut).
PR-147 adds no new code -- nine published documents plus CONTRIBUTING/SECURITY/
CODE_OF_CONDUCT, closing 11 of 12 DOC items (DOC-06 was already evidenced). Every
claim cites a real pre-existing module, test file, or prior PR; DOC-10 (API spec
+ example client) turned out to already be fully satisfied by `docs/api/openapi-v1.json`
+ `service.client` + `tests/unit/test_service_client.py` and was simply credited for
the first time. DOC-07/DOC-08 are marked `(partial)`: the experiment guide cites
CIQ-03's existing reproducibility guarantee rather than re-demonstrating it, and the
operations runbook explicitly discloses that the model registry supports invalidation
(retire) but not a one-step backward rollback transition -- LCH-10's stronger
versioned-rollback claim remains open, named rather than implied covered.
PR-148 closes SEC-10 (first evidence) with `data_ingestion.egress_allowlist
.AllowlistedTransport`, a real wrapper denying any host not on a configured
allowlist before delegating, routing a real P1 alert on denial through the
existing `evidence.alert_routing` primitive and recording a structured
denial record; scope disclosed plainly: no production connector call site
was switched to use it yet, and "model serving" makes no outbound call
today for this to gate.
PR-149 closes GOV-12/GOV-09/SEC-01/SEC-15 (first evidence, all four) with a risk
acceptance register demonstrated against two real disclosed repository exceptions,
a machine-generated license inventory queried from this repo's real installed
dependency metadata, a threat model mapping real misuse cases to real controls,
and an explicit security response-owner/patch-cadence statement; GOV-03 (named
owners/deputies) remains explicitly unimplemented since this is a genuinely
single-maintainer repository with no second identity to name.
PR-150 closes NSD-01..13 (first evidence, all 13, closing NSD at 13/13) with a new
`prometheus.neural_sde` package trained on the real Kaggle macro snapshot already
ingested by PR-145; two items (NSD-04, NSD-07) required an honest, disclosed
reinterpretation/substitution for this package's YoY-growth-rate state variables
rather than a literal price-level match. Real OOD result against the actual 2020
COVID window: the neural SDE's log-score degrades far less than a GBM baseline's
under the real shock, independently reproduced end to end before being recorded.
PR-151 closes PR-148's own disclosed gap: `orchestration.recessionnet_run`/`qmacro_run`
now default to `egress_allowlist.default_ingestion_transport()` instead of a bare
`UrllibTransport()`, confirmed by monkeypatch-verified tests per script rather than
trusting the import alone; resolves the matching historical risk-acceptance exception
in `evidence.risk_register`'s own worked example before its sunset date.
PR-152 closes PRV-01/02/03/05/07 (first evidence, all five) with a new
`pii_scan` composed into the existing scanner-agnostic release gate, a data
processing inventory classifying every real ingested series as public
aggregate (confirmed, not asserted, by the real PII scan), and an extended
license/entitlement register; caught and fixed a real false positive in its
own PII-pattern draft against this repository's own `neural_sde` data
before shipping.
PR-153 closes PDE-01..12 (first evidence, all 12, closing PDE at 12/12) with a new
`prometheus.pde_solvers` package: three independent Black-Scholes PDE solvers (grid,
PINN, deep BSDE), cross-checked against each other and the existing closed-form/Monte
Carlo pricers. Real result: the classical grid wins outright where reachable, but its
cost scales combinatorially with dimension while deep BSDE's stays flat -- the actual,
demonstrated justification for the neural method rather than an assumed one. A real
measured fix (an added no-arbitrage penalty term) cut a 58% stress-violation rate to
~17-20% during development.
PR-154 closes MAR-01..14 (first evidence, 13 of 14 full, MAR-02 partial, closing MAR
at 14/14) with a new `prometheus.marl` package: real PPO-trained household/firm
policies over the existing econosim ledger environment. A reward-design bug (a
degenerate "spend everything" optimum) was caught by a direct sweep and fixed before
training was trusted; the resulting policy then beats every fixed-fraction baseline.
Co-learning measurably destabilizes training (~4-5x higher variance than single-agent)
and a real OOD wage shock degrades utility by ~8.7 -- both real, measured findings.
PR-155 closes MGR-01/05/08/09/12/13, DRI-05/06/09/10/12 and CMP-01/02/03 (14 items):
a fail-closed unhealthy-service gate and retired-model deployment refusal on the
existing model-serving layer, a new model inventory, three items credited from
pre-existing modules never mapped to MGR before, two items confirmed genuinely not
applicable (no pretrained weights, no multi-region deployment) rather than left
silently open, a new incident-management module demonstrated against the real PR-141
incident, and three NIST mapping documents explicitly marked as self-assessments.
PR-156 closes CIQ-02: GitHub branch protection enabled on main (required CI status
checks, enforce_admins off so direct pushes keep working), confirmed unprotected
before and protected after via direct gh api calls -- a real repository-setting
change, not a code change.
PR-157 closes CIQ-07/12 and credits LCH-01: a real Ed25519 signature scheme for
release provenance (verified independently with only the public key; a tampered
statement and a wrong-key signature both confirmed to fail), a breaking-change
notice type requiring affected clients/change-log/maintenance-window/owner-approval,
and LCH-01 credited from the pre-existing gate report's real order-routing
exclusion -- never mapped to that item before.
PR-158 closes VAL-10/CIQ-09/CIQ-10/HDG-14 and GOV-06/10/13/14 (first evidence),
SEC-09/LCH-08 (first credited), and SEC-07/LCH-02/GOV-02/05/07/08/11 (partial),
closing HDG and VAL at 14/14. A real REINFORCE hedging agent is reported honestly
losing to the static baseline at its training budget, not tuned until it won. An
automatic rollback is demonstrated via real fault injection, not merely described.
Nine new governance documents close or partially close the GOV items that are
genuinely achievable without a second human or external authority.
PR-159 closes UIX-01..12 (first evidence, 11 full + 1 partial, closing UIX at
11/12) with a new `prometheus.dashboard` ASGI service rendering real subsystem
output through the existing `service.auth` identity -- no mock data layer, no
new frontend dependency. UIX-10's authorization refusal and UIX-07's inclusion
of real non-winning results are both genuine, verified end to end. UIX-11 names
exactly what still needs a real browser rather than claiming an audit that
didn't happen.
PR-160 closes PRV-09/11/12 and LCH-10 (first evidence) and credits/partially
credits SEC-12 and LCH-04/05/07 from pre-existing modules never mapped to those
items before. The LCH-10 demonstration composes three already-real primitives
(canary shadow comparison, registry audit chain, retired-model deployment
refusal) with zero new mechanism invented for the item. Every partial item
names its exact missing human-sign-off half rather than implying it happened.
PR-161 wires 5 already-tested dashboard views into real HTTP routes and fixes a
real ASGI lifespan bug found only by actually starting the server (python -m
prometheus.dashboard serve) -- every unit test still passed with the bug present,
since none exercised uvicorn's real startup handshake. Adds docs/RESEARCH_CONTRIBUTIONS.md
and docs/PORTFOLIO_DEMO.md. No new blueprint IDs; strengthens UIX evidence from
unit-tested to live-reachable.
PR-162 independently re-derives NSD/PDE/MAR's real headline numbers from scratch
(clean) and finds a real bug in HDG-14's REINFORCE agent (rsample() silently
zeroing the mean-head gradient) -- fixed with a regression test driving the
mechanism directly. The already-published "REINFORCE loses to the static
baseline" conclusion is unchanged, now for the genuine reason. AI-assisted
self-audit, not independent human review; no new blueprint ID.
PR-163 closes PRV-04/08 and credits SEC-11/LCH-06/MGR-04 (first evidence/credited,
LCH-06 partial): a real, deliberate (not unset) indefinite-retention policy for
reproducibility artifacts; SEC-11/LCH-06 pull together pre-existing rate-limit and
recovery-drill evidence never mapped to those items; MGR-04 aggregates, rather than
re-derives, the real backtest/calibration evidence already on record per model.
PR-164 credits SEC-13 and LCH-11 from pre-existing, already-tested evidence
(failover_audit_continuity's real tampered-history-fails-to-restore test;
consistent real SIMULATION_DISCLAIMER wording across README/dashboard/governance
docs) -- no new code, both items just never mapped to these specific IDs before.
PR-023 adds the first evidence anywhere in this repository for OPT-01, OPT-02, OPT-03, OPT-04
and OPT-09 — the entire TITAN portfolio-optimization checklist category had zero evidenced IDs before it.
PR-024 adds the first evidence for RISK-05 and strengthens OPT-05, connecting directly to
PR-023's optimizer: a shrunk covariance is shown to reduce true out-of-sample portfolio risk.
PR-025 adds the first evidence for OPT-07 and strengthens OPT-10, closing the loop between
PR-023's optimizer and PR-024's shrinkage estimator across simulated time.
PR-026 extends ECO-05 and ECO-09 with a genuine central-bank balance sheet (reserve
issuance, OMO, interbank settlement), previously explicitly listed as not done.
PR-027 adds the first evidence anywhere in this repository for RISK-07 (factor
exposure and risk decomposition).
PR-028 wires PR-026's central bank into the real `StepHooks` event order for the
first time and adds `Economy.add_central_bank_ledger`.
PR-029 wraps PR-028's scenario in a CLI/evidence-export runner registered with
`orchestration.replay`.
PR-030 adds the first evidence anywhere in this repository for RISK-10 and OPT-11,
and partial evidence for OPT-12 (stress testing).
PR-031 adds the first evidence anywhere in this repository for RISK-11 (interbank
network contagion) and strengthens the partial RISK-12 evidence.
PR-032 connects PR-031's contagion analysis to live `econosim` ledger state for
the first time.
PR-033 adds a genuine direct bank-to-bank lending instrument, closing PR-032's
own "no direct bank-to-bank lending" admission.
PR-034 wires that instrument plus a periodic live systemic-risk check into
PR-028's `StepHooks` scenario.
PR-035 adds the first position book anywhere in this repository, with the first
evidence for RISK-01/RISK-13.
PR-036 makes PR-034's contagion check act on a detected default via a one-way
circuit breaker, rather than only recording it.
PR-037 adds forward contracts as a second instrument type, generalizing
PR-035's position book beyond options.
PR-038 adds American options priced by a binomial tree, the first
non-closed-form pricing method in this repository.
PR-039 wires American options into the position book as a third instrument
type.
PR-040 adds Greeks for American options, catching and fixing a genuine
numerical pitfall (naive spot-bumped gamma on a binomial tree) along the way.
PR-041 optionally unifies the central bank's rate process and balance sheet
into one object, without retiring or breaking either existing class.
PR-042 migrates `econosim.monetary_operations` onto that unified constructor.
PR-043 adds interest accrual and single-creditor loan write-off to `Bank`,
the first evidence anywhere in this repository for LED-05/LED-06.
PR-049 adds the multi-creditor insolvency waterfall LED-07 actually asks
for, closing the gap PR-043 explicitly left open.
PR-050 generalizes PR-024's covariance shrinkage to an arbitrary fixed
target and connects it to PR-027's factor model, closing the "no
factor-model target" gap PR-024 explicitly left open.
The checklist states,
explicitly and by category, everything still outstanding: independent review
(MGR-*), deployment security and model lifecycle controls, deployed identity/API
acceptance, dashboards (UIX-*), general multi-firm price/settlement and
monetary inventory valuation. PR-026–043/049 added central-bank balance-sheet
operations and insolvency resolution; PR-046/047 add durable local jobs and an
authenticated research API; PR-050 strengthens the covariance/factor-model risk
estimators.
Those implementations
retain their documented limits. As of PR-014,
`MacroTimeEngine.advance_step()` *does* have real, working extension points
for section 02's steps 3-7 (`StepHooks`), proven end to end against four
real subsystems in one test. PR-015 adds a packaged multi-step reference
scenario through those hooks; `demo_run.py` remains a separate example. The
actual, current gate status (generated from code, not asserted) is
`NO-GO`, matching the blueprint's own section 19 — see
[`evidence/gate_report_r0.json`](./evidence/gate_report_r0.json).

Further slices can calibrate the synthetic transmission channels, encode
published macro histories, estimate unconditional macro/market tail risk, or implement the
security/model-governance controls needed to move past R0. Earlier
benchmark numbers precede PR-015's financing correction; PR-016 exports a
fresh corrected reference with its complete recipe and replay comparison.

## License

MIT — see [LICENSE](./LICENSE).
