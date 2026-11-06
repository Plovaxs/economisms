# PR-015 local validation — 2026-11-02

Scope: the monthly StepHooks reference scenario, online hedge accounts,
single-state MLP inference, corrected trade/financing timing in NumPy and
PyTorch, and the post-hook ledger integrity check. These are local results,
not an independent review or evidence that production gates have passed.

| Check | Result |
|-------|--------|
| `.venv/bin/ruff check src tests` | Passed |
| `.venv/bin/mypy --strict src` | Passed; 45 source files |
| `.venv/bin/python -m pytest -q --cov=prometheus --cov-report=term-missing` | 336 passed in 17.21s; 98% line coverage |
| `git diff --check` | Passed |

The full test run used Python 3.14.7 in the existing local virtual
environment. The repository's GitHub Actions matrix was not run remotely.

The integration tests cover call and put expiry, independent cash-flow
reconciliation with changing financing rates, physical-measure portfolio
CVaR, deterministic replay, exported JSON hash verification, future-shock
causality, isolated market/risk RNG streams, funding failures and ledger
corruption. A one-period borrowed-cash closed form detects the original
interest-ordering bug. Training rollout, batch evaluation and online
accounts are compared on identical actions and paths.

The reference artifact was generated with:

```bash
.venv/bin/python -m prometheus.orchestration.multi_step_run \
  --seed 42 --start-date 2026-01-02 --steps 12 \
  --output evidence/multi_step_reference.json
```

It completed all 12 steps with `valid=true`. Its deterministic result hash is:

```text
3525187c1dad682736baf4a10a6d0904832679499caf89d941053d87e920b80e
```

JSON round-trip verification confirmed that
`compute_result_hash(bundle["simulation"])` equals the manifest hash,
the policy hash equals the model card's content hash, and the gate report
matches the regenerated `gate_report_r0.json`. The reference is one
synthetic realized scenario, not a statistical comparison of policies.

The financing correction changes previously reported losses and learned
weights. Earlier benchmark numbers must be rerun under the corrected
trade-then-accrue convention before being cited as current evidence.
The 374-item checklist remains unverified pending appropriate review.
