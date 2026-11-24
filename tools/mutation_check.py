"""Targeted mutation check: does the test suite notice when a critical rule is broken on purpose?

A passing suite says the code agrees with the tests; it does not say the tests would disagree with
broken code. This tool injects ONE deliberate fault at a time into a critical module (a flipped
sign, a dropped check, an off-by-one), runs only the tests that are meant to guard that module, and
requires them to FAIL. A fault that survives is a hole in the tests, not in the tool.

    python tools/mutation_check.py --list          # the catalogue
    python tools/mutation_check.py                  # run every mutation (minutes)
    python tools/mutation_check.py --only ledger    # the mutations whose name contains "ledger"
    python tools/mutation_check.py --json out.json  # also write the result

No third-party tool: the catalogue below is the whole mechanism, and a unit test
(`tests/unit/test_mutation_catalogue.py`) checks on every run that each snippet still occurs exactly
once, so the catalogue cannot silently go stale. The files are restored even on an error or Ctrl-C;
a leftover `.mutation-backup` file from a killed run is restored by `--restore`. It refuses to start
if a target file has uncommitted changes, so it can never destroy work.

Exit status: 0 every mutation was caught; 1 at least one survived; 2 the catalogue is stale or the
tree is not clean.
"""

# ruff: noqa: E501, S603, S607
# E501: a mutation names an exact line of source and cannot be wrapped. S603/S607: the only processes
# started are `git status` and this project's own pytest, with fixed arguments and no shell.
from __future__ import annotations

import argparse
import json
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from types import FrameType

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "prometheus"
BACKUP_SUFFIX = ".mutation-backup"


@dataclass(frozen=True)
class Mutation:
    name: str
    file: str
    """Relative to `src/prometheus`."""
    old: str
    """Must occur exactly once in the file."""
    new: str
    tests: tuple[str, ...]
    """The tests meant to guard this code; at least one must fail."""


_LEDGER = ("tests/unit/test_ledger.py", "tests/property/test_ledger_invariants.py")
_BS = ("tests/unit/test_black_scholes.py",)
_RISK = ("tests/unit/test_risk_metrics.py",)
_HEDGE = ("tests/unit/test_hedging_simulate.py",)
_BOOT = ("tests/unit/test_block_bootstrap.py",)

MUTATIONS: tuple[Mutation, ...] = (
    # ---- double-entry ledger: conservation is the property every other result rests on
    Mutation(
        "ledger: an imbalanced transaction is accepted",
        "core/ledger.py",
        "            if debits != credits:\n",
        "            if False:\n",
        _LEDGER,
    ),
    Mutation(
        "ledger: a debit lowers an asset",
        "core/ledger.py",
        "sign = 1 if side is Side.DEBIT else -1",
        "sign = -1 if side is Side.DEBIT else 1",
        _LEDGER,
    ),
    Mutation(
        "ledger: the per-sector balance check is skipped",
        "core/ledger.py",
        "        self._check_sector_balance(txn)\n",
        "        pass\n",
        _LEDGER,
    ),
    Mutation(
        "ledger: a duplicate transaction id is accepted",
        "core/ledger.py",
        "        if transaction_id in self._transaction_ids:\n            raise DuplicateTransactionError(transaction_id)\n",
        "        if False:\n            raise DuplicateTransactionError(transaction_id)\n",
        _LEDGER,
    ),
    Mutation(
        "ledger: a posting in the wrong currency is accepted",
        "core/ledger.py",
        "            if account.currency != p.amount.currency:\n                raise CurrencyMismatchError(account.currency, p.amount.currency)\n",
        "            if False:\n                raise CurrencyMismatchError(account.currency, p.amount.currency)\n",
        _LEDGER,
    ),
    Mutation(
        "ledger: a zero posting is accepted",
        "core/ledger.py",
        "if self.amount.is_negative() or self.amount.is_zero():",
        "if self.amount.is_negative():",
        _LEDGER,
    ),
    # ---- Black-Scholes: closed forms that the numerical pricers are checked against
    Mutation(
        "black-scholes: the drift term has the wrong sign",
        "volterra/black_scholes.py",
        "(r - q + 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))",
        "(r - q - 0.5 * sigma**2) * t) / (sigma * math.sqrt(t))",
        _BS,
    ),
    Mutation(
        "black-scholes: d2 adds the volatility term",
        "volterra/black_scholes.py",
        "d2 = d1 - sigma * math.sqrt(t)",
        "d2 = d1 + sigma * math.sqrt(t)",
        _BS,
    ),
    Mutation(
        "black-scholes: the put uses d2 instead of -d2",
        "volterra/black_scholes.py",
        "    return _discounted_expectation(k, r, t, norm.cdf(-d2)) - _discounted_expectation(",
        "    return _discounted_expectation(k, r, t, norm.cdf(d2)) - _discounted_expectation(",
        _BS,
    ),
    Mutation(
        "black-scholes: the call discounts the asset at the rate, not the dividend yield",
        "volterra/black_scholes.py",
        "return _discounted_expectation(s, q, t, norm.cdf(d1)) - _discounted_expectation(",
        "return _discounted_expectation(s, r, t, norm.cdf(d1)) - _discounted_expectation(",
        _BS,
    ),
    Mutation(
        "black-scholes: no discounting",
        "volterra/black_scholes.py",
        "return notional * math.exp(exponent) * probability",
        "return notional * probability",
        _BS,
    ),
    # ---- risk metrics
    Mutation(
        "risk: parametric VaR subtracts the volatility term",
        "titan/risk_metrics.py",
        "return float(mean + std * stats.norm.ppf(alpha))",
        "return float(mean - std * stats.norm.ppf(alpha))",
        _RISK,
    ),
    Mutation(
        "risk: historical VaR uses the other tail",
        "titan/risk_metrics.py",
        "return float(np.quantile(losses, alpha, method=interpolation))",
        "return float(np.quantile(losses, 1 - alpha, method=interpolation))",
        _RISK,
    ),
    Mutation(
        "risk: expected shortfall rounds the tail down",
        "titan/risk_metrics.py",
        "k = min(math.ceil(alpha * n), n)",
        "k = min(math.floor(alpha * n), n)",
        _RISK,
    ),
    Mutation(
        "risk: expected shortfall mis-weights the boundary observation",
        "titan/risk_metrics.py",
        "boundary_weight = k - alpha * n",
        "boundary_weight = alpha * n - k",
        _RISK,
    ),
    Mutation(
        "risk: expected shortfall divides by the wrong tail mass",
        "titan/risk_metrics.py",
        "denominator = n * (1 - alpha)",
        "denominator = n * alpha",
        _RISK,
    ),
    Mutation(
        "risk: drawdown measured from the trough",
        "titan/risk_metrics.py",
        "drawdowns = cumulative_values - running_max",
        "drawdowns = running_max - cumulative_values",
        _RISK,
    ),
    # ---- hedging accounting
    Mutation(
        "hedging: transaction costs can be negative",
        "hedging/simulate.py",
        "cost = cost_rate * np.abs(trade) * s_t",
        "cost = cost_rate * trade * s_t",
        _HEDGE,
    ),
    Mutation(
        "hedging: a purchase adds cash",
        "hedging/simulate.py",
        "cash = (cash - trade * s_t - cost) * accrual",
        "cash = (cash + trade * s_t - cost) * accrual",
        _HEDGE,
    ),
    Mutation(
        "hedging: terminal holdings are subtracted",
        "hedging/simulate.py",
        "final_wealth = cash + holdings * s_terminal - payoff",
        "final_wealth = cash - holdings * s_terminal - payoff",
        _HEDGE,
    ),
    Mutation(
        "hedging: the put pays the call's payoff",
        "hedging/simulate.py",
        "payoff = np.maximum(strike - s_terminal, 0.0)",
        "payoff = np.maximum(s_terminal - strike, 0.0)",
        _HEDGE,
    ),
    # ---- the bootstrap every interval in the findings comes from
    Mutation(
        "bootstrap: the last block can never be drawn",
        "experiments/block_bootstrap.py",
        "max_start = n - block_length + 1",
        "max_start = n - block_length",
        _BOOT,
    ),
    Mutation(
        "bootstrap: too few blocks are drawn",
        "experiments/block_bootstrap.py",
        "n_blocks = -(-n // block_length)  # ceil(n / block_length)",
        "n_blocks = n // block_length",
        _BOOT,
    ),
    Mutation(
        "bootstrap: the interval is the wrong quantile pair",
        "experiments/block_bootstrap.py",
        "np.quantile(values, [alpha / 2, 1 - alpha / 2])",
        "np.quantile(values, [alpha, 1 - alpha])",
        _BOOT,
    ),
)


def occurrences(mutation: Mutation) -> int:
    return (SRC / mutation.file).read_text(encoding="utf-8").count(mutation.old)


def _dirty(path: Path) -> bool:
    status = subprocess.run(
        ["git", "status", "--porcelain", "--", str(path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return bool(status.stdout.strip())


def restore_leftovers() -> list[Path]:
    restored = []
    for backup in SRC.rglob(f"*{BACKUP_SUFFIX}"):
        original = backup.with_name(backup.name.removesuffix(BACKUP_SUFFIX))
        original.write_bytes(backup.read_bytes())
        backup.unlink()
        restored.append(original)
    return restored


def run_one(mutation: Mutation) -> dict[str, object]:
    path = SRC / mutation.file
    original = path.read_bytes()
    backup = path.with_name(path.name + BACKUP_SUFFIX)
    backup.write_bytes(original)

    def restore(_signum: int | None = None, _frame: FrameType | None = None) -> None:
        path.write_bytes(original)
        backup.unlink(missing_ok=True)
        if _signum is not None:
            raise SystemExit(130)

    previous = signal.signal(signal.SIGINT, restore)
    started = time.monotonic()
    try:
        path.write_text(original.decode().replace(mutation.old, mutation.new, 1), encoding="utf-8")
        result = subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *mutation.tests],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        restore()
        signal.signal(signal.SIGINT, previous)
    caught = result.returncode != 0
    first_failure = next((ln for ln in result.stdout.splitlines() if ln.startswith("FAILED")), "")
    return {
        "name": mutation.name,
        "file": mutation.file,
        "caught": caught,
        "first_failing_test": first_failure,
        "seconds": round(time.monotonic() - started, 1),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--only", help="run only mutations whose name contains this text")
    parser.add_argument("--json", type=Path, help="write the result here")
    parser.add_argument("--restore", action="store_true", help="restore files left by a killed run")
    args = parser.parse_args(argv)

    if args.restore:
        print("restored:", [str(p.relative_to(ROOT)) for p in restore_leftovers()])
        return 0
    chosen = [m for m in MUTATIONS if not args.only or args.only in m.name]
    if args.list:
        for m in chosen:
            print(f"{m.file:34s} {m.name}")
        return 0
    stale = [m.name for m in chosen if occurrences(m) != 1]
    if stale:
        print(
            "stale catalogue (the snippet is not there exactly once):",
            *stale,
            sep="\n  ",
            file=sys.stderr,
        )
        return 2
    if any(SRC.rglob(f"*{BACKUP_SUFFIX}")):
        print("a .mutation-backup file exists: run with --restore first", file=sys.stderr)
        return 2
    dirty = sorted({m.file for m in chosen if _dirty(SRC / m.file)})
    if dirty:
        print("uncommitted changes in", *dirty, "(commit or stash them first)", file=sys.stderr)
        return 2

    results = []
    for m in chosen:
        outcome = run_one(m)
        results.append(outcome)
        print(
            ("CAUGHT " if outcome["caught"] else "MISSED ") + m.name,
            f"({outcome['seconds']}s)",
            flush=True,
        )
    missed = [r for r in results if not r["caught"]]
    print(f"\n{len(results) - len(missed)} of {len(results)} caught; {len(missed)} survived")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps({"results": results, "missed": [r["name"] for r in missed]}, indent=2)
        )
    return 1 if missed else 0


if __name__ == "__main__":
    raise SystemExit(main())
