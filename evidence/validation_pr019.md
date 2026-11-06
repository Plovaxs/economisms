# PR-019 local validation — 2026-11-02

Scope: reusable exact price economy, publication-aware price/output
signals, bounded monetary feedback, opening/closing-rate financial timing,
payroll demand feedback, and complete coupled-run replay. Local changes
remain pending commit and independent review.

| Check | Result |
|-------|--------|
| `.venv/bin/ruff check src tests` | Passed |
| `.venv/bin/mypy --strict src` | Passed; 56 source files |
| `.venv/bin/python -m pytest -q --cov=prometheus --cov-report=term-missing` | 620 passed in 17.99 seconds; 96% line coverage |
| Default twelve-step monetary reference and actual replay | Valid; exact result match; no runtime changes |
| Historical PR-018 economy reference replay | Exact historical result match; source digest change reported |
| Independent exported-JSON readback | All twelve steps passed cash/equity, physical inventory, publication timing, rate timing and hedge cash/cost/wealth reconciliation |

The final source-only change following the full test run was formatter
indentation of an adjacent string literal. Lint and strict types were
checked afterward; the default reference/replays below use that final
source. Python 3.14.7, NumPy 2.5.4, SciPy 1.18.1 and PyTorch 2.15.0+cpu
were observed, without a dependency-lock or remote-CI claim.

Reference/replay source digest:

```text
9a845eb85f24d1f17af84ed10bec05bd436f8bd05cb030d69a2366f6a96e3731
```

## Reproduction

```bash
.venv/bin/python -m prometheus.orchestration.monetary_run \
  --output evidence/monetary_reference.json
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/monetary_reference.json --output evidence/monetary_replay.json
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/economy_price_reference.json --output evidence/economy_price_replay_pr019.json
```

The monetary payload result hash is:

```text
69743a65c3ec661ed793d670d3880ccdf453325b5ff192199f58890f2d482b98
```

The MLP training/model-card content hashes agree:

```text
fd1981b0c2a0893d813f33133132402aad1bf7d2a6bacc1b5f43aee910fd9170
```

The original standalone economy retains result hash:

```text
cdfccc07e4f1a73f9c98951c7bf726a425d79a93efb1b919e1e7b0724b70a7cb
```

## Timing and declared feedback rule

At step t, already-published inputs determine a closing rate. The entire
financial interval t uses its opening rate, inherited from the previous
close, for physical GBM drift and hedge cash accrual. The closing rate
sets marks and rehedging, then applies to interval t+1. Current economic
production/trade observations are published at least one model month
later. Financial randomness, training and conditional-risk draws use
distinct named streams.

The configured rule is `target = neutral + phi_pi * (inflation - target_pi)
+ phi_y * output_gap`; inertia blends that target with the previous rate,
then bounds clip the result. Defaults are neutral .03, target inflation
.02, inflation response .5, output response .02, inertia .8, floor -.02
and ceiling .25. Missing two-price history holds the previous rate.
Inflation is a log change annualized by the released model-step interval,
over up to twelve model months. Physical output gap is production/180 - 1.

Desired payroll is the integer floor of `base_payroll * exp(-2 *
(opening_rate - neutral_rate))`, then capped by available firm cash.
This specified demand rule is not bank lending or a posted interest flow.

## Default reference

Training uses 1,500 paths, 60 epochs and batches of 256, with 2,000
conditional-risk paths per nonterminal step. One firm and two households
start with 400,000 minor USD total cash/equity. No later economic cash
injections occur. Productivity halves at step 4.

| Step | Traded goods price, minor USD | Latest published model step | Opening rate | Closing rate | Desired payroll, minor USD |
|------|------------------------------|-----------------------------|--------------|--------------|----------------------------|
| 1 | 108 | none | .030000 | .030000 | 18000 |
| 2 | 108 | 1 | .030000 | .030000 | 18000 |
| 3 | 108 | 2 | .030000 | .028141 | 18000 |
| 4 | 117 | 3 | .028141 | .026653 | 18067 |
| 5 | 194 | 4 | .026653 | .055415 | 18120 |
| 6 | 190 | 5 | .055415 | .222130 | 17107 |
| 7 | 171 | 6 | .222130 | .250000 | 12257 |
| 8 | 169 | 7 | .250000 | .250000 | 11592 |
| 12 | 168 | 11 | .250000 | .250000 | 11592 |

Rates above are annual decimal rates, rounded only for this table.
The step-4 price increase enters the step-5 decision and step-6 financing.
The toy rule reaches its configured ceiling; this is neither an empirical
forecast nor evidence of optimal policy. Full exact economic quantities
and unrounded floating-point rates remain in the JSON.

Delta terminal wealth is -7.836331316325442 and MLP terminal wealth is
-9.142341832868652. These are two realized outcomes on one path, with
transaction costs; they do not estimate a superiority probability or
sample CVaR. The model card reports only realized terminal loss.

## Cross-checks and limits

Independent JSON calculations reconciled initial premium/trade/cost,
every opening-rate cash accrual, subsequent trades, cumulative costs and
terminal payoff for both policies within 1e-9. Terminal conditional risk
equals the exact negative terminal wealth. Each economic step retained
400,000 minor USD cash/equity; cumulative production minus cumulative
sales equaled nonnegative inventory exactly as rational numbers. All
36 new observation records have future publication dates, and all 53
selected macro-input records were published by their decision dates.
Training/model hashes, payload hashes and observed runtimes match across
the reference, replay and final local source.

Tests additionally cover call/put accounts, one/two-month publication
lags, no-trade warmup, final-step shock non-anticipation, zero payroll
sensitivity, publication beyond the horizon, invalid price-search halts,
risk-RNG isolation and replay rejection of fabricated/missing fields.
Reusable economic-process guards reject duplicate shock actions, foreign
contexts, forged settlements and stale state snapshots before those
operations can be accepted as a completed step.

Economic cash and hedge accounts are separate. Behavioral schedules,
potential output and policy coefficients lack empirical identification.
Black-Scholes marks assume a flat closing rate through expiry, without
solving a joint stochastic-rate risk-neutral model. Conditional risk
freezes holdings/rates and omits future policy/economic feedback. MLP
training uses constant-initial-rate GBM. Latest published data can become
stale if trading stops. Market settlement is atomic per market; full-step
rollback/resumption is absent. General multi-firm equilibrium, bank/central
bank balance sheets and dynamic-policy conditional risk remain open.

R0 remains **NO-GO**. This slice adds evidence to existing checklist IDs;
the evidence covers existing IDs, including partial implementations,
with no independent checklist acceptance or review claimed. Count corrected
during PR-020: 69 distinct blueprint checklist IDs, plus a separate R-03
risk-register row previously included in the count of 70.
