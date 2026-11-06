# PR-021 local validation — 2026-11-02

Scope: matched current-rate feature ablation, independent macro training
pools, differentiable changing-rate hedge accounting, optimization
diagnostics, crossed evaluation and replay. Changes remain local,
uncommitted and not independently reviewed.

| Check | Result |
|-------|--------|
| `.venv/bin/ruff check src tests` | Passed |
| `.venv/bin/mypy --strict src` | Passed; 60 source files |
| `.venv/bin/python -m pytest -q --cov=prometheus --cov-report=term-missing` | 737 passed in 21.62 seconds; 96% line coverage |
| `git diff --check` | Passed |
| Default rate study and actual replay | Valid; identical result hash; no runtime changes |
| Historical PR-020 monetary-study replay | Exact original result hash; source digest change reported |
| Independent JSON/data reconstruction | All training pool hashes, paired initialization/minibatch hashes, model-card hashes, macro accounting/timing and contrast matrices reconciled |

Runtime: Python 3.14.7, NumPy 2.5.4, SciPy 1.18.1 and PyTorch 2.15.0+cpu.
Reference, replay and final local package source share this observed digest:

```text
e37fc030af6d8b013b902211649f0e82916b68a827c79965ff495b56a16cd57b
```

## Reproduction and artifact identity

```bash
.venv/bin/python -m prometheus.orchestration.rate_study \
  --output evidence/rate_study_reference.json
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/rate_study_reference.json --output evidence/rate_study_replay.json
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/monetary_study_reference.json --output evidence/monetary_study_replay_pr021.json
```

New rate-study result hash:

```text
7b8b9f011062af41547716bc5fcb9944c248a6641e3770a3edfb3413c8f77960
```

Historical monetary-study result retained after bank-builder extraction:

```text
b9192bf5a26c3068d722c9acc7ade4f28fcafa2e7cb42afada78b48f53a0e6de
```

Original artifacts are preserved. The historical replay reports only a
source digest change. No dependency lock, remote CI, immutable external
storage or independent reviewer is claimed.

## Matched experiment

The rate-aware and rate-blind MLPs each have four inputs, two hidden layers
of 32 ReLU units and a tanh holding in [-1,1]. The first three inputs are
log-moneyness, remaining horizon fraction and prior holding. The fourth is
`(current_rate - initial_rate) / .1` in the aware arm and zero in the blind
arm. No future rates or macro observations are feature inputs.

For every training row, both arms share the same parameter initialization,
market/rate data, sampled minibatches, Adam settings, CVaR objective,
turnover penalty and gradient bound. Rates still finance both accounts
identically when the rate feature is masked. A policy hash includes both
parameter bytes and feature masking/centering/scaling; the parameter-only
initial hash is separately retained to prove matched initialization.

The default uses three `(policy_seed,path_seed)` rows `(0,1)`, `(7,2)`,
`(13,3)`. Each row generates three independent training economies, labels
11, 22, 33, in the separately declared `training_baseline` scenario. This
scenario halves productivity at step 4, uses one-month publication lag
and payroll-rate sensitivity 2. Productivity noise standard deviation is
.03. Each economy supplies 500 conditional market paths, totaling 1,500
training paths per row. Both arms train for 60 epochs, sampling 256 paths
with replacement per epoch, at learning rate .01 and gradient norm bound
10. Turnover penalty defaults to zero. The objective is CVaR on this
finite training macro mixture, not a population-risk guarantee.

Training economy and market streams include the row's path seed and macro
label in distinct named domains. Evaluation reuses the original PR-020
bank builder, with seeds 100, 200, 300, 512 market paths per bank and the
same four baseline/publication/payroll/supply scenarios. Training labels
must be disjoint from test labels, and their actual RNG domains differ.
Changing test scenarios or test seeds cannot change the fitted models.

There are six fitted models and 36 evaluation cells. Each cell evaluates
delta, rate-blind and rate-aware policies on the same bank prices, for 108
policy evaluations. Delta uses the current rate and fixed pricing
volatility .2. Premium, strike/spot, execution costs, financing and horizon
remain matched. The initial premium is 9.413403383853016, rate .03, cost
rate .005, strike/spot 100, horizon twelve model months and CVaR alpha .9.

## Contrasts and result

Primary contrast: rate-blind minus rate-aware bank-conditional CVaR.
Secondary contrast: delta minus rate-aware bank-conditional CVaR. Positive
favors the aware arm. Cell risks condition on each realized macro path;
the endpoint averages cell differences without pooling macro/model losses.

The crossed bootstrap resamples whole training rows and shared test-bank
columns, using common bootstrap draws across scenarios/contrasts. The
declared family has eight pairs (four scenarios times two contrasts).
Nominal .95 family confidence allocates .99375 confidence per interval,
with 1,000 percentile-bootstrap resamples and zero economic margin. This
allocation does not establish calibrated finite-seed coverage.

| Scenario | Primary mean difference | Nominal 99.375% crossed interval | Primary verdict |
|----------|-------------------------|---------------------------------|-----------------|
| baseline | -.294842 | [-.758886, .194064] | inconclusive |
| delayed_publication | -.114272 | [-.681958, .593399] | inconclusive |
| no_payroll_channel | -.293741 | [-.758885, .196482] | inconclusive |
| severe_supply_shock | -.385864 | [-.868495, -.092197] | comparator_better |

The overall primary verdict is **inconclusive**, requiring all scenarios
to clear the margin in the same direction. The observed means favor the
blind arm throughout, and the severe-shock interval favors the blind arm
under the declared approximate rule. These results do not establish a
consistent incremental benefit from the rate feature.

| Scenario | Secondary delta-minus-aware mean | Nominal 99.375% crossed interval |
|----------|---------------------------------|---------------------------------|
| baseline | 2.110203 | [1.278583, 2.624255] |
| delayed_publication | 1.589599 | [.596920, 2.156624] |
| no_payroll_channel | 2.108071 | [1.276812, 2.623016] |
| severe_supply_shock | 2.432491 | [1.654720, 2.854608] |

The secondary intervals favor the rate-aware MLP over delta on this
specified experiment. The matched primary control prevents attributing
that difference to the extra rate feature. Both learned arms train on
variable-rate macro data, whereas PR-020's original three-input MLP trains
on constant-rate GBM; this is a separately specified experiment. Three
training and three test-bank levels still provide limited coverage evidence.
No empirical superiority or optimal monetary-policy claim follows.

## Optimization diagnostics

Every epoch logs its sampled-batch CVaR/objective, mean loss/turnover,
gradient norm before clipping, clipping flag and fraction of targets with
absolute value at least .99. These are pre-update training-batch diagnostics,
not held-out validation or a convergence certificate.

| Policy seed | Arm | Largest pre-clip gradient norm | Clipped epochs / 60 | Largest batch saturation fraction |
|-------------|-----|--------------------------------|--------------------|-----------------------------------|
| 0 | blind | 82.674812 | 48 | .0078125 |
| 0 | aware | 85.979774 | 44 | .0205078 |
| 7 | blind | 80.553055 | 43 | .0312500 |
| 7 | aware | 80.860336 | 37 | .4163412 |
| 13 | blind | 80.028366 | 41 | .0338542 |
| 13 | aware | 81.598480 | 44 | .0455729 |

The seed-7 aware arm reaches roughly 41.6% saturation in one sampled batch;
the trace retains this behavior instead of hiding it behind aggregate
performance. All 360 epoch records have finite diagnostics. Initial
parameter hashes and complete minibatch-sequence hashes match within each
aware/blind pair. Training does not alter the caller's global Torch RNG.

## Checks and failure handling

Independent data reconstruction regenerated all three complete training
pools and their rate matrices/hashes. Direct exported-JSON checks covered
nine training macros and twelve evaluation macros: 252 economic steps,
756 future publication records and 1,098 selected macro-input records.
Each step retains 400,000 minor USD cash/equity and exact rational physical
inventory conservation. Policy input publication times, opening/closing
rates, payroll feedback, paired model hashes and all 3x3 contrast matrices
reconcile. Training/test macro trace hashes have no overlap. Named stream
domains and held-out seed validation supply the actual split design;
non-overlapping hashes alone would not prove statistical independence.

Unit tests compare differentiable call/put losses, costs, turnover and
targets to the shared NumPy simulator with changing/path-specific rates,
and verify nonzero finite gradients. A constructed rate-only network
matches an independent tanh formula. Future/expiry rate and terminal-price
perturbations cannot affect earlier decisions; the masked arm ignores rates
as a feature. When every rate equals the feature center, the two arms
produce identical parameter updates and diagnostics exactly.

Any failed training or evaluation macro bank invalidates the complete
study before fitting, retaining all bank records and suppressing model
cards and inference. Tests cover one training-bank failure and actual
unresolved price searches across training/evaluation, including invalid
artifact replay. Numerical fitting/evaluation failures raise instead of
omitting cells. Strict recipe reading rejects missing fields, duplicate
keys and non-finite JSON. Generic replay tests now cover this seventh
computational payload, including fabricated results after rehashing.

## Remaining limits

Current rate is the only added feature; no full macro-history encoder,
empirical calibration or dynamic-policy risk forecast is implemented.
Training is a finite macro mixture, evaluation averages conditional CVaRs,
and percentile coverage remains uncertain at few seed levels. Black-Scholes
delta assumes flat current rates to expiry with fixed volatility. Economic
and hedge books remain separate, without asset-wealth feedback or bank/
central-bank balance sheets. No model family is certified or independently
reviewed.

R0 remains **NO-GO**. The checklist now has 70 distinct blueprint IDs with
some evidence, adding partial HDG-10 diagnostics to PR-020's corrected 69.
The separate R-03 risk-register row is excluded. These counts are not
completion percentages or independent acceptance counts.
