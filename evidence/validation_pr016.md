# PR-016 local validation — 2026-11-02

Scope: complete benchmark training/evaluation recipes, actual replay of
monthly and benchmark artifacts, independent RNG streams, financial
metrics, observed source/dependency provenance, strict JSON and atomic
export. This is local validation pending commit and independent review.

| Check | Result |
|-------|--------|
| `.venv/bin/ruff check src tests` | Passed |
| `.venv/bin/mypy --strict src` | Passed; 47 source files |
| `.venv/bin/python -m pytest -q --cov=prometheus --cov-report=term-missing` | 409 passed; 97% line coverage |
| `git diff --check` | Passed |

The full suite ran in 69.99 seconds while the reference benchmark was
also running. The local interpreter was Python 3.14.7. No remote CI
matrix or independent reviewer rerun is claimed.

Source digest observed during generation and replay:

```text
db95494e07265c77b37c5b0adab33b3235cb434410be006b89b0e29911cf278a
```

Dependency versions recorded in the artifacts: NumPy 2.5.4, SciPy 1.18.1
and PyTorch 2.15.0+cpu. These observations do not constitute a dependency
lock, a signed source identity or artifact authentication.

## Corrected benchmark

```bash
.venv/bin/python -m prometheus.orchestration.benchmark_run \
  --output evidence/hedge_benchmark_reference.json
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/hedge_benchmark_reference.json \
  --output evidence/hedge_benchmark_replay.json
```

The recipe trains one MLP on 2,000 paths for 80 epochs, using path seed 1
and policy seed 0. It evaluates 2,000 held-out paths per seed with 1,000
paired bootstrap resamples and 95% percentile intervals. The JSON records
all remaining configuration, exact training-data and policy hashes,
objective history, financial metrics and the fixed decision rule.

The endpoint is delta CVaR minus policy CVaR at alpha 0.9. Positive values
favor the learned policy. These are synthetic per-option loss units.

| Test seed | Delta CVaR | MLP CVaR | Difference | 95% paired interval |
|-----------|------------|----------|------------|--------------------|
| 100 | 4.084232 | 4.054026 | 0.030205 | [-0.147904, 0.204765] |
| 200 | 4.019152 | 4.127062 | -0.107910 | [-0.303829, 0.079820] |
| 300 | 4.021250 | 4.196942 | -0.175691 | [-0.345477, 0.015056] |

Every interval includes zero. The fixed seed-wise decision rule therefore
returns **inconclusive**, with mean seed difference -0.084465. These
intervals condition on one trained policy, not independent retrainings;
there is no claim of multiple-testing adjustment or full factorial/OOD
coverage. This is a fresh corrected reference, not a reconstruction of
the earlier undocumented development configuration.

Reference and recomputed result hashes both equal:

```text
25647e421b4db686afe2c7c7362c003692e0986c94c10889d389fb833aa7fe8b
```

The replay CLI returned 0, reported `matches=true` and no runtime changes.
The recomputed artifact includes its own new run ID and replay comparison.

## Monthly reference replay

```bash
.venv/bin/python -m prometheus.orchestration.replay \
  evidence/multi_step_reference.json --output evidence/multi_step_replay.json
```

The CLI returned 0 and `matches=true` for the complete 12-month recipe:

```text
3525187c1dad682736baf4a10a6d0904832679499caf89d941053d87e920b80e
```

The original PR-015 artifact predates runtime metadata. Replay correctly
reported `runtime metadata absent`; the original file was preserved.
The recomputed file records current runtime observations separately.

All four JSON artifacts were independently read back and checked against
their payload/manifest hashes and model-card policy hashes. Both replay
artifacts carry matching expected/observed digests.

## Failure behavior exercised

Tests reject tampered payloads before training, disagreeing manifest
configuration/seeds, unsupported versions/conventions, incomplete recipes,
duplicate test seeds, train/test seed overlap, duplicate JSON keys,
non-finite results and unsupported JSON values. A fabricated result with a
fresh hash fails actual recomputation. A reproducible invalid monthly run
remains invalid even when replay matches. Atomic-export tests force
serialization and replacement failures and verify that the old destination
survives without temporary-file residue.

Remaining work includes independent training-seed uncertainty, scenario
grids/OOD evaluation, dependency locking and external review. R0 remains
NO-GO; the wider 374-item blueprint is not complete.
