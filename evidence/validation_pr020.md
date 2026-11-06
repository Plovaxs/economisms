# PR-020 local validation — 2026-11-02

Scope: crossed retraining/shared macro-market banks, feedback scenario
evaluation, changing-rate batch hedge accounting and complete replay.
Changes are local, uncommitted and not independently reviewed.

| Check | Result |
|-------|--------|
| `.venv/bin/ruff check src tests` | Passed |
| `.venv/bin/mypy --strict src` | Passed; 58 source files |
| `.venv/bin/python -m pytest -q --cov=prometheus --cov-report=term-missing` | 687 passed in 19.39 seconds; 96% line coverage |
| `git diff --check` | Passed |
| Default monetary study and actual replay | Valid; identical result hash; no runtime changes |
| Historical PR-019 online monetary replay | Exact original result match; source change reported |
| Historical PR-016 constant-rate benchmark replay | Exact original result match; source change reported |

Runtime: Python 3.14.7, NumPy 2.5.4, SciPy 1.18.1 and PyTorch 2.15.0+cpu.
No remote CI, dependency lock or independent reviewer is claimed. Reference,
replay and final local package source share this observed digest:

```text
a319bf8a04fe4b5e5dadf44c7abb1356dbf3b044e9263548298ea4f8203f1e6b
```

## Reproduction and artifact identity

```bash
.venv/bin/python -m prometheus.orchestration.monetary_study \
  --output evidence/monetary_study_reference.json
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/monetary_study_reference.json --output evidence/monetary_study_replay.json
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/monetary_reference.json --output evidence/monetary_replay_pr020.json
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/hedge_benchmark_reference.json --output evidence/hedge_benchmark_replay_pr020.json
```

Full new study result hash:

```text
b9192bf5a26c3068d722c9acc7ade4f28fcafa2e7cb42afada78b48f53a0e6de
```

The original online monetary result remains:

```text
69743a65c3ec661ed793d670d3880ccdf453325b5ff192199f58890f2d482b98
```

The original constant-rate benchmark remains:

```text
25647e421b4db686afe2c7c7362c003692e0986c94c10889d389fb833aa7fe8b
```

The latter two replay artifacts preserve the original files, report only
`source_sha256` runtime changes, and retain the same computational results.

## Default experiment

The full design crosses three training replicates `(policy_seed,
path_seed) = (0,1), (7,2), (13,3)` with bank seeds 100, 200, 300 and four
declared scenarios. There are 36 cells. Every model trains once on 1,500
constant-initial-rate GBM paths for 60 epochs with batch size 256. No
scenario-specific retraining or winning-seed selection occurs.

Each bank has one twelve-step stochastic economy and 512 market paths
conditional on that macro realization. The economy template uses .03
productivity-noise standard deviation. Bank-specific economy seeds derive
from the `macro-study-economy-seed` stream; market normals use
`macro-study-market-normals`. Training paths use the independent
`macro-study-training-paths` domain. Scenario names and axis declarations
are canonically sorted; reversing their input order gives the same result.
The root study seed controls crossed bootstrap draws.

Scenario parameters replace the economy template's productivity-shock
multiplier and specify publication lag/payroll sensitivity. Defaults are:

| Scenario | Productivity multiplier at step 4 | Publication lag, months | Payroll-rate sensitivity |
|----------|-----------------------------------|-------------------------|--------------------------|
| baseline | .5 | 1 | 2 |
| delayed_publication | .5 | 2 | 2 |
| no_payroll_channel | .5 | 1 | 0 |
| severe_supply_shock | .3 | 1 | 2 |

All default scenarios retain pricing/realized volatility .2 and cost rate
.005. Custom scenarios can multiply realized volatility and execution
costs while keeping the training distribution, premium and delta pricing
volatility fixed. The initial premium is 9.413403383853016, initial rate
.03, strike/spot 100, horizon one model year and CVaR alpha .9.

Every training row receives exactly the same market prices in a bank.
Across scenarios, matching banks share economy noise and market normals;
rates, prices and activity may change through the specified feedback.
Macro histories do not depend on asset prices or hedge wealth in this
model. `MonetaryProcess` is the same action/publication implementation
used by the original online runner, with exact field-level parity tests.

## Endpoint and result

The endpoint is the mean of cell-level, bank-conditional CVaR differences,
delta minus MLP. Positive favors MLP for this endpoint. Each cell's tail
sample consists of its bank's 512 conditional market outcomes; it does
not pool losses across macro banks or retrained models.

Pigeonhole percentile bootstrap resamples training rows and shared bank
columns independently, using the same draws across scenarios. It runs
1,000 resamples. A nominal .95 family confidence over four declared
scenarios allocates .9875 confidence to each scenario interval. Overall
direction requires every scenario interval to exceed the zero economic
margin in that direction. Finite-seed marginal coverage is not calibrated.

| Scenario | Mean conditional-CVaR difference | Nominal 98.75% crossed interval | Verdict |
|----------|----------------------------------|--------------------------------|---------|
| baseline | -1.115472 | [-2.510887, .385107] | inconclusive |
| delayed_publication | -1.153615 | [-2.435729, .248139] | inconclusive |
| no_payroll_channel | -1.115749 | [-2.510637, .384673] | inconclusive |
| severe_supply_shock | -1.025075 | [-2.385385, .465782] | inconclusive |

The overall result is **inconclusive**. The observed mean differences
favor delta, but every interval includes zero. This does not demonstrate
equality, robust superiority or optimal monetary policy. Three training
and three bank levels provide limited uncertainty evidence.

## Independent checks and failure handling

Exported-JSON calculations checked all 12 macro banks, 144 completed
economic steps and 36 hedge comparison cells. Every economic step retains
400,000 minor USD total cash/equity; exact cumulative production minus
sales equals nonnegative physical inventory. All 621 selected macro-input
records were published by their decision date. All 432 new observations
have strictly future publication dates. Opening/closing rates and adjusted
payroll independently match the declared timing and exponential rule.

Named standard-normal hashes reconstruct exactly and match across scenario
variants. Every cell's market-price hash matches its shared bank. Cell
differences, 3x3 matrices, mean endpoints and nominal confidence allocations
reconcile directly from JSON. All three training policy hashes match the
corresponding model cards. Full replay additionally retrains each model
and regenerates market prices, actions, losses, metrics and intervals.

Independent financial tests reconcile changing-rate cash, costs and final
wealth against hand calculations and `OnlineHedgeAccount` for calls/puts.
They cover both interval and path-specific funding matrices, negative
rates and exact constant-rate compatibility. Scalar Black-Scholes Greeks
cross-check scheduled delta decisions. Perturbing future or expiry rates
cannot alter earlier decisions or completed financial intervals. A zero
MLP fixture checks each cell against naked-option financing and a manually
weighted fractional empirical tail with three outcomes, rather than a
second call to the same CVaR implementation.

All declared macro banks are retained even when one fails. Any such
failure marks the full study invalid and suppresses training, model cards
and inference. Tests exercise both actual failed price searches and a
single failed bank among otherwise successful banks. Numerical financial
failures raise rather than silently omit cells. Strict recipe reading
rejects missing nested fields, duplicate JSON keys and non-finite JSON.
Generic evidence tests cover hash tampering, fabricated results after
rehashing, missing fields, runtime drift and CLI behavior for this sixth
computational payload type.

## Remaining limits

This is a synthetic, uncalibrated sensitivity study. It estimates average
conditional-risk differences, not unconditional macro/market CVaR. The
current MLP has no macro/rate features and trains at constant rates.
Delta knows only current rates with fixed pricing volatility; Black-Scholes
marks assume flat rates to expiry, without solving a stochastic-rate Q
model. The online runner's conditional-risk forecast still freezes current
holdings/rates. Economic and hedge balance sheets remain separate, with
no asset-wealth feedback, bank/central-bank balance-sheet model or full
learned-economy/learned-market factorial. Macro coefficients and responses
are specified rules, not empirical causal estimates.

R0 remains **NO-GO**. No approvals or independent checklist acceptance
were added. The checklist evidence covers 69 distinct blueprint IDs plus
a separate R-03 risk-register row; this corrects the earlier combined
count of 70 and is not a completion percentage.
