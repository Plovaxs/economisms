"""What the window offers to run, in words a person can choose from.

One entry per allow-listed runner. The one-line summaries paraphrase each runner module's own
docstring and nothing more; `test_catalog` fails if a runner is added to the registry without an
entry here, so the window can never silently omit one.
"""

from __future__ import annotations

from dataclasses import dataclass

GROUPS = ("Forecasting labs", "Models and solvers", "Simulations", "Hedging studies")


@dataclass(frozen=True, slots=True)
class KindInfo:
    kind: str
    title: str
    group: str
    summary: str
    network: bool = False
    """The runner fetches data over the network (from an allow-listed host) before falling back to
    a committed snapshot. Said out loud, because the rest of the application never does."""


KIND_CATALOG: tuple[KindInfo, ...] = (
    KindInfo(
        "inflationcast",
        "INFLATIONCAST",
        "Forecasting labs",
        "CPI nowcasting: naive persistence against linear regression, an MLP, a hybrid quantum "
        "model and a calibrated GRU, on the committed BLS CPI-U and Kaggle macro snapshots.",
    ),
    KindInfo(
        "recessionnet_kaggle",
        "RECESSIONNET",
        "Forecasting labs",
        "Recession prediction from US GDP, unemployment claims, the Fed funds rate, M2 and "
        "NASDAQ (committed Kaggle snapshot): a base rate against logistic regression, an MLP "
        "and a hybrid quantum model.",
    ),
    KindInfo(
        "qmacro",
        "Q-MACRO",
        "Forecasting labs",
        "Forecasting the market factor Mkt-RF several months ahead from Kenneth French factor "
        "data: persistence, AR, linear, MLP and hybrid quantum models. Downloads the factor file "
        "from an allow-listed host and falls back to the committed snapshot when offline.",
        network=True,
    ),
    KindInfo(
        "neural_sde",
        "Neural SDE",
        "Models and solvers",
        "A neural stochastic differential equation fitted to US macro series and benchmarked "
        "against GBM, AR(1), GARCH and persistence by CRPS and log score.",
    ),
    KindInfo(
        "pde_solver",
        "PDE solvers",
        "Models and solvers",
        "One option priced four ways: closed-form Black–Scholes, a Crank–Nicolson grid, a PINN "
        "and a deep-BSDE network, with their measured wall-clock cost.",
    ),
    KindInfo(
        "marl",
        "Multi-agent RL",
        "Models and solvers",
        "A household policy trained alone against a fixed firm rule, compared with the same "
        "household co-learning with the firm, on household utility.",
    ),
    KindInfo(
        "rl_hedge",
        "RL hedging agent",
        "Models and solvers",
        "A REINFORCE hedging agent against a static delta hedge with a no-trade band, on "
        "simulated GBM paths.",
    ),
    KindInfo(
        "economy",
        "Economy",
        "Simulations",
        "A monthly household-and-firm economy with budget-feasible wage and goods price "
        "discovery, on an exact double-entry ledger.",
    ),
    KindInfo(
        "monetary",
        "Monetary loop",
        "Simulations",
        "A causal loop: the price economy, published inflation and output, the policy rate, "
        "then a hedge.",
    ),
    KindInfo(
        "monetary_operations",
        "Central-bank operations",
        "Simulations",
        "A central-bank scenario: open-market operations, the discount window, interbank "
        "lending and a contagion check.",
    ),
    KindInfo(
        "simulation",
        "Monthly scenario",
        "Simulations",
        "A reproducible monthly scenario run through all five step hooks, with a trained MLP "
        "hedge and a delta-hedge baseline.",
    ),
    KindInfo(
        "benchmark",
        "Hedge benchmark",
        "Hedging studies",
        "Train, evaluate and export a fully specified synthetic hedge benchmark with bootstrap "
        "intervals.",
    ),
    KindInfo(
        "study",
        "Hedge study",
        "Hedging studies",
        "Independently retrained hedges crossed with held-out path banks and stress scenarios.",
    ),
    KindInfo(
        "monetary_study",
        "Monetary study",
        "Hedging studies",
        "Retrained hedges with shared macro and market banks and policy-feedback scenarios.",
    ),
    KindInfo(
        "rate_study",
        "Rate-feature study",
        "Hedging studies",
        "A matched ablation: does a hedge that sees the current policy rate beat one that does "
        "not?",
    ),
    KindInfo(
        "mixture_study",
        "Macro-mixture study",
        "Hedging studies",
        "Tail risk under an empirical mixture of macro and market banks, with paired nested "
        "uncertainty.",
    ),
)

_BY_KIND = {entry.kind: entry for entry in KIND_CATALOG}


def info(kind: str) -> KindInfo:
    return _BY_KIND[kind]


ERROR_MESSAGES: dict[str, str] = {
    "worker_failed": "The worker process ended unexpectedly.",
    "invalid_simulation": "The run finished but reported its own result as invalid; the result "
    "is kept so you can see why.",
    "environment_mismatch": "The code or library versions changed after the job was queued. "
    "Run it again.",
    "wall_timeout": "The job ran out of its time limit.",
    "cpu_timeout": "The job used more processor time than its limit.",
    "lease_expired": "The worker stopped reporting, so the job was abandoned.",
    "artifact_invalid": "The result failed its integrity checks and was discarded.",
    "execution_rejected": "The job's recipe no longer matched its recorded hash.",
    "model_error": "The model reported an error (check the parameters).",
    "infrastructure_error": "A file or system error stopped the job.",
    "restore_interrupted": "A restore interrupted the job.",
}


def describe_error(code: str | None) -> str:
    if code is None:
        return ""
    return ERROR_MESSAGES.get(code, f"The job stopped with the error code {code}.")
