# PR-017 local validation — 2026-11-02

Scope: independently retrained policies crossed with shared held-out test
banks and predefined parameter stresses; exploratory crossed/single-axis
bootstrap diagnostics; nominal scenario-family tail allocation; economic
margins; actual replay of the full study. This is local work pending commit
and independent review.

| Check | Result |
|-------|--------|
| `.venv/bin/ruff check src tests` | Passed |
| `.venv/bin/mypy --strict src` | Passed; 49 source files |
| `.venv/bin/python -m pytest -q --cov=prometheus --cov-report=term-missing` | 473 passed in 19.60 seconds; 97% line coverage |
| `git diff --check` | Passed |

Local Python was 3.14.7, with NumPy 2.5.4, SciPy 1.18.1 and PyTorch
2.15.0+cpu. The reference/replay observed the same source digest:

```text
af0bdd7468624b239685430126204e78460bfa03ba2c40104c48a4085bb670eb
```

These observations are not a dependency lock or signed source identity.
No remote CI run or independent scientific review is claimed.

## Recorded design and commands

```bash
.venv/bin/python -m prometheus.orchestration.study_run \
  --output evidence/hedge_study_reference.json
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/hedge_study_reference.json --output evidence/hedge_study_replay.json
```

The default design uses policy/training-data seed pairs (0, 1), (7, 2) and
(13, 3), with held-out test-bank seeds 100, 200 and 300. Each model trains
once on 2,000 paths for 80 epochs. Each model is evaluated on 2,000 paths
per bank/scenario at 20 hedge steps, retaining all 27 cells. Training paths,
policy weights and actual test banks have content hashes in the artifact.

All scenarios use spot/strike 100, maturity one year, physical drift 0.08
and financing rate 0.05. Training volatility is 0.20 and execution cost is
0.005. The stress grid is fixed before the run:

| Scenario | Realized volatility | Execution cost |
|----------|---------------------|----------------|
| baseline | 0.20 | 0.005 |
| high_volatility | 0.35 | 0.005 |
| higher_costs | 0.20 | 0.010 |

The initial premium stays 10.450583572185565 throughout. Delta's assumed
volatility stays 0.20, and learned policies receive no oracle stress
parameter feature. Models are not refitted under stress. Canonical ordering
makes seed/scenario input order irrelevant to the full result hash.

## Endpoint and interpretation

The endpoint is the mean of cell-level delta-minus-policy CVaR differences
at alpha 0.9, expressed in synthetic per-option loss units. Positive values
favor the learned policy. Cell path-conditional intervals use 1,000 paired
bootstrap resamples at nominal 95% confidence.

The study resamples complete training rows and shared test-bank columns
independently, following the [pigeonhole construction of Owen
(2007)](https://arxiv.org/abs/0712.1111). There are 1,000 outer resamples.
Bonferroni allocates a nominal 95% family confidence across the three
crossed scenario intervals, giving 98.333333% nominal marginal confidence.
The single-axis intervals are conditional diagnostics outside the decision
rule. No exact marginal or family coverage is established with three seed
levels; tail allocation cannot fix uncalibrated bootstrap coverage.

The predeclared economic margin is zero. The overall rule requires every
scenario interval to exceed that margin in the same direction.

| Scenario | Mean CVaR difference | Crossed interval, nominal 98.333333% | Scenario verdict |
|----------|----------------------|-------------------------------------|------------------|
| baseline | -0.082037 | [-0.209623, 0.061128] | inconclusive |
| high_volatility | 1.960804 | [1.337773, 2.597626] | policy_better |
| higher_costs | 0.289735 | [0.176671, 0.462774] | policy_better |

The overall verdict is **inconclusive**, because the baseline interval
includes zero. The two stress scores refer to hedges under frozen training
assumptions. A recalibrated stress-volatility delta comparison remains open.

## Actual replay and compatibility

The reference and full recomputation both produced:

```text
9bf23df564bb9877498766d520f79cdda018d708da631cf4503a90d0946a4763
```

The replay CLI returned 0, `matches=true`, and no runtime changes. Separate
JSON read-back verified the result hashes, all 27 cells, all three policy
hashes against their model cards, and common path hashes across models for
every scenario/test-bank pair. No result was omitted based on performance.

Compatibility with the previous single-policy reference was checked with:

```bash
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/hedge_benchmark_reference.json \
  --output evidence/hedge_benchmark_replay_pr017.json
```

It returned 0 and reproduced the original result hash:

```text
25647e421b4db686afe2c7c7362c003692e0986c94c10889d389fb833aa7fe8b
```

It correctly reported source-digest drift while the computational result
remained unchanged. The original reference and prior replay were preserved.

## Verified behaviors and remaining limits

Tests show that more test banks do not erase training variation and more
models do not erase shared-bank variation. Constant effects yield exact
point intervals; a known crossed draw checks row/column interactions.
Integration tests cover calls/puts, common paths, stress volatility without
an oracle delta update, once-per-model training, complete cells, canonical
ordering, margin boundaries, strict design validation, full replay and
rejection of rehashed fabricated results.

The endpoint averages empirical cell CVaRs, not pooled losses, portfolio
CVaR or an ensemble hedge. Outer resampling does not correct finite-bank
CVaR estimation bias. Policy initialization and training data vary jointly;
their individual variance contributions are not identified. The row-only
and column-only diagnostics are not independent variance components.

Historical data, Heston/jumps, market impact/liquidity, the full macro
factorial, stronger coverage calibration and independent review remain
open. R0 remains NO-GO; this is not completion of the 374-item blueprint.
