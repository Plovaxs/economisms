# Replication guide

For someone who did not write this software and wants to check whether it does what it says. It tells you what
to run, what you should see, how much difference is expected, and how to report what you got. Nothing here has
been done by anyone else yet: the project has had **no independent replication**, and this guide is the thing
that would let one happen. If a step is unclear or wrong, that is a result; please report it.

Research software: **NO-GO for trading or advice**. Everything here is simulation or historical backtest.

## 0. Set up a clean, pinned environment

Use a machine that is not the maintainer's. Either route gives the same pinned dependencies (`uv.lock`):

- **Linux, easiest:** `curl -fsSLO https://github.com/Plovaxs/economisms/releases/latest/download/install-linux.sh`,
  read it, then `bash install-linux.sh` (about 1.8 GB; no root; it checks the source archive against
  `SHA256SUMS`). To pin a version: `ECONOSIM_VERSION=0.5.3 bash install-linux.sh`.
- **Any system with Python 3.11 or newer, from a source checkout of a tagged release:**
  `python3 -m pip install --require-hashes --only-binary=:all: -r requirements/bootstrap.txt`, then
  `uv sync --locked --all-extras --group build`, then use `.venv/bin/python`. Jobs need Linux; the numerical
  studies do not.

Then run `econosim doctor` (or `.venv/bin/python -m prometheus.doctor`). **It must end with `doctor: all clear`.**
Its `locked_dependencies` check fails if numpy, scipy, torch or pennylane differ from the lock, because this
project has found that a different numpy changes a result. Do not continue on a failing doctor; report it.

## 1. The quickest check: the confirmatory reproduction

```
python -m prometheus.confirmatory reproduce
```

About six minutes (add `--skip-e1` for 15 seconds without the hedging runs). It re-runs three studies on the
committed data and compares 16 numbers with the ones the findings document. **Expected:** `"all_checks_match": true`
and `"n_checks": 16`. The numbers are the inflation base-effect result (277 months, errors 0.326 and 0.226
percentage points, a difference of -0.100 with the interval [-0.136, -0.068]), the value-at-risk result (3,235
days, 48 and 56 exceedances, pinball losses 3.92, 8.22, 5.63 and 10.40 basis points) the hedging range
(1.04 to 1.41 times the baseline over eight seeds at two epoch budgets, none below 1) and Finding 5's COVID
degradations for seed 0 (+6.99 neural, +26.45 GBM).

## 2. Re-run a finding

Each finding in [`RESULTS_AND_LIMITATIONS.md`](./RESULTS_AND_LIMITATIONS.md) names the module that produced it and
the pull request in [`PR_LEDGER.md`](./PR_LEDGER.md). Every runner has a command line:

```
python -m prometheus.orchestration.inflationcast_long_study --output inflation.json   # Finding 18
python -m prometheus.orchestration.market_risk_study --output risk.json               # Finding 15
python -m prometheus.orchestration.rl_hedge_run --seed 0 --output hedge.json          # Finding 8
python -m prometheus.orchestration.<module> --help                                    # the others
```

The 16 runner kinds are listed in `src/prometheus/orchestration/recipes.py`. `--help` prints each one's
settings; the defaults are the ones the findings used.

## 3. What counts as "the same"

- **Same machine, same lock:** the sealed `result_hash` of a run should be identical. Exact-hash replay is a
  single-machine guarantee only: on another CPU or another BLAS the last bits of a floating-point sum can differ,
  and `tests/unit/test_replay.py` says why that check is local and opt-in.
- **Another machine, same lock:** expect the headline numbers to agree to the digits printed in the findings and
  the conclusions (which side of a baseline, whether an interval contains zero) to be identical. A run that
  reverses a conclusion is a discrepancy, whatever the digits.
- **A different dependency version:** not a replication; the doctor will say so.

## 4. Report what you got

Open an issue with the **Replication report** form (`.github/ISSUE_TEMPLATE/replication-report.yml`). Paste the
`econosim doctor` output, the exact commands and the real numbers, and say whether you are independent of the
maintainer. Report a failure to install or run as carefully as a failure to match: how long each step took and
what confused you is the usability evidence the project does not have.

## What this does not establish

A match shows that the code produces the numbers the documents quote, on your machine. It does not show that the
numbers are right (a replication shares the original's assumptions, and the project has found bugs that its own
tests, written from the same assumptions, missed), nor that any finding holds on new data. That is what the
[confirmatory protocol](./CONFIRMATORY_PROTOCOL.md) is for, and it is still a draft.
