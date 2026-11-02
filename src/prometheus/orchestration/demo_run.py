"""Section 16's "Minimum v0.1 demonstration script", implemented literally:

  1. Simulate a small closed economy.
  2. Verify all journals (the ledger's accounting identities).
  3. Apply one known monetary shock -- here, Appendix B's own SC-01
     scenario: an unanticipated +200bp policy-rate shock.
  4. Generate GBM/Heston market paths.
  5. Price one European option under a separately calibrated Q model.
  6. Compare a Black-Scholes delta hedge against a trained, cost-aware MLP
     hedge.
  7. Compute P&L and CVaR.
  8. Export an auditable report.

"If any invariant, valuation tolerance or data-timing check fails, the run
must be marked invalid rather than silently published" is implemented as
three explicit, independent checks, one per category named in that
sentence:
  - invariant:           the economy's ledger accounting identity (section
                          3.2), and Heston variance non-negativity
  - valuation tolerance:  an independent Monte Carlo price must agree with
                          the Black-Scholes closed form within a
                          configurable number of standard errors
  - data-timing:          the policy-rate path's pre-shock segment must be
                          bit-identical to a path with no shock at all -- a
                          shock cannot leak backward in time

Every check appends to DemoRunResult.invalid_reasons on failure rather than
raising; run_demo() always returns a DemoRunResult.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

import numpy as np

from prometheus.core.ledger import LedgerError
from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.econosim.macro_market_link import simulate_policy_rate_conditioned_market
from prometheus.econosim.policy_rate import PolicyRateRule, simulate_policy_rate_path
from prometheus.econosim.shocks import Shock
from prometheus.evidence.export import build_evidence_bundle
from prometheus.evidence.model_card import ModelCard
from prometheus.evidence.repository_status import (
    build_deep_hedge_model_card,
    current_repository_gate_report,
)
from prometheus.experiments.manifest import RunManifest, compute_result_hash, new_run_id, now_iso
from prometheus.hedging.baseline import black_scholes_delta_hedge_ratios
from prometheus.hedging.deep_hedge import generate_policy_hedge_ratios, train_deep_hedge
from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.stochastica.heston import HestonParams, simulate_heston_paths
from prometheus.titan.risk_metrics import historical_expected_shortfall
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption, OptionType
from prometheus.volterra.market import MarketSnapshot
from prometheus.volterra.monte_carlo import monte_carlo_price_vanilla


@dataclass(frozen=True, slots=True)
class DemoRunConfig:
    seed: int = 0
    n_macro_steps: int = 6
    policy_shock_step: int = 2
    policy_shock_bps: float = 200.0  # Appendix B SC-01: "+200 bp policy-rate shock"
    initial_policy_rate: float = 0.03
    policy_rate_neutral: float = 0.03
    policy_rate_mean_reversion: float = 0.5
    equity_risk_premium: float = 0.04
    volatility: float = 0.2
    spot: float = 100.0
    strike: float = 100.0
    option_maturity_years: float = 0.5
    option_type: OptionType = "call"
    cost_rate: float = 0.005
    n_eval_paths: int = 3_000
    n_train_paths: int = 2_000
    n_train_epochs: int = 80
    cvar_alpha: float = 0.9
    mc_price_n_paths: int = 20_000
    mc_price_tolerance_std_errors: float = 6.0
    heston_kappa: float = 2.0
    heston_theta: float = 0.04
    heston_xi: float = 0.2
    heston_rho: float = -0.5

    def __post_init__(self) -> None:
        if self.n_macro_steps < 1:
            raise ValueError("n_macro_steps must be >= 1")
        if not 0 <= self.policy_shock_step <= self.n_macro_steps:
            raise ValueError("policy_shock_step must be within [0, n_macro_steps]")
        if self.option_maturity_years <= 0:
            raise ValueError("option_maturity_years must be positive")


@dataclass(frozen=True, slots=True)
class DemoRunResult:
    valid: bool
    invalid_reasons: tuple[str, ...] = field(default_factory=tuple)
    ledger_state_hash: str | None = None
    policy_rate_path: tuple[float, ...] | None = None
    black_scholes_price: float | None = None
    monte_carlo_price: float | None = None
    monte_carlo_standard_error: float | None = None
    heston_feller_ratio: float | None = None
    delta_hedge_cvar: float | None = None
    mlp_hedge_cvar: float | None = None
    manifest: RunManifest | None = None
    evidence_bundle: dict[str, Any] | None = None


def run_demo(config: DemoRunConfig, economy: Economy | None = None) -> DemoRunResult:
    """`economy`, if given, is used as-is instead of building a fresh one --
    this exists so a test can inject a deliberately corrupted ledger and
    verify the invariant check actually catches it, not just in theory."""
    invalid_reasons: list[str] = []
    dt = config.option_maturity_years / config.n_macro_steps

    # -- 1/2. small closed economy + verify all journals --------------------
    if economy is None:
        economy = Economy()
        bank = economy.add_bank("bank-1", max_leverage=10.0)
        bank.capitalize(Money(1_000_000_00, "USD"))
        household = economy.add_household("hh-1")
        household.receive_income(Money(10_000_00, "USD"))
    try:
        economy.check_integrity()
        ledger_state_hash = economy.ledger.snapshot(economy.step_index).state_hash()
    except LedgerError as exc:
        invalid_reasons.append(f"invariant: ledger accounting identity violated: {exc}")
        return DemoRunResult(valid=False, invalid_reasons=tuple(invalid_reasons))

    # -- 3. apply one known monetary shock (SC-01: +200bp) -------------------
    rule = PolicyRateRule(
        neutral_rate=config.policy_rate_neutral,
        mean_reversion_speed=config.policy_rate_mean_reversion,
        dt=dt,
    )
    shock_magnitude = config.policy_shock_bps / 10_000.0
    known_shock = Shock(
        shock_id="sc-01-policy-tightening",
        step=config.policy_shock_step,
        kind="policy_rate",
        magnitude=shock_magnitude,
    )
    schedule: list[list[Shock]] = [
        [known_shock] if t == config.policy_shock_step else []
        for t in range(1, config.n_macro_steps + 1)
    ]
    policy_rate_path = simulate_policy_rate_path(rule, config.initial_policy_rate, schedule)

    # data-timing check: the pre-shock segment must be bit-identical to a
    # path with the shock removed entirely -- nothing can leak backward.
    schedule_no_shock: list[list[Shock]] = [[] for _ in range(config.n_macro_steps)]
    reference_path = simulate_policy_rate_path(rule, config.initial_policy_rate, schedule_no_shock)
    pre_shock_slice = policy_rate_path[: config.policy_shock_step]
    reference_slice = reference_path[: config.policy_shock_step]
    if pre_shock_slice != reference_slice:
        invalid_reasons.append(
            "data-timing: policy-rate path before the shock step does not match "
            "the no-shock reference path -- a shock leaked backward in time"
        )

    # -- 4. generate GBM/Heston market paths ----------------------------------
    rng_eval = np.random.default_rng(config.seed)
    eval_paths = simulate_policy_rate_conditioned_market(
        config.spot,
        policy_rate_path,
        config.equity_risk_premium,
        config.volatility,
        dt,
        config.n_eval_paths,
        rng_eval,
    )

    heston_params = HestonParams(
        mu=config.initial_policy_rate + config.equity_risk_premium,
        kappa=config.heston_kappa,
        theta=config.heston_theta,
        xi=config.heston_xi,
        rho=config.heston_rho,
        v0=config.volatility**2,
    )
    rng_heston = np.random.default_rng(config.seed + 1)
    _, heston_variance_paths = simulate_heston_paths(
        config.spot,
        heston_params,
        config.option_maturity_years,
        config.n_macro_steps,
        2_000,
        rng_heston,
    )
    heston_feller_ratio = heston_params.feller_ratio()
    if np.any(heston_variance_paths < 0.0):
        invalid_reasons.append("invariant: Heston diagnostic produced negative variance")

    # -- 5. price one European option under a separately calibrated Q model --
    market = MarketSnapshot(
        as_of=date.today(),
        spot=config.spot,
        risk_free_rate=config.initial_policy_rate,
        volatility=config.volatility,
    )
    option = EuropeanOption(config.strike, config.option_maturity_years, config.option_type)
    bs_price = black_scholes_price(market, option)

    rng_mc = np.random.default_rng(config.seed + 2)
    mc_result = monte_carlo_price_vanilla(
        market, option, config.mc_price_n_paths, config.n_macro_steps, rng_mc
    )
    price_diff_in_std_errors = abs(mc_result.price - bs_price) / mc_result.standard_error
    if price_diff_in_std_errors > config.mc_price_tolerance_std_errors:
        invalid_reasons.append(
            f"valuation tolerance: Monte Carlo price {mc_result.price:.4f} is "
            f"{price_diff_in_std_errors:.2f} standard errors from the Black-Scholes "
            f"price {bs_price:.4f}, exceeding the {config.mc_price_tolerance_std_errors} "
            "standard-error tolerance"
        )

    # -- 6/7. delta vs. trained MLP hedge; P&L and CVaR -----------------------
    rng_train = np.random.default_rng(config.seed + 3)
    training_drift = config.initial_policy_rate + config.equity_risk_premium
    train_paths = simulate_gbm_paths(
        config.spot,
        training_drift,
        config.volatility,
        config.option_maturity_years,
        config.n_macro_steps,
        config.n_train_paths,
        rng_train,
    )
    training_result = train_deep_hedge(
        train_paths,
        dt,
        config.strike,
        config.option_maturity_years,
        config.option_type,
        config.initial_policy_rate,
        config.cost_rate,
        bs_price,
        cvar_alpha=config.cvar_alpha,
        n_epochs=config.n_train_epochs,
        seed=config.seed,
    )

    delta_ratios = black_scholes_delta_hedge_ratios(
        eval_paths,
        dt,
        config.strike,
        config.option_maturity_years,
        config.initial_policy_rate,
        config.volatility,
        config.option_type,
    )
    delta_result = simulate_self_financing_hedge(
        eval_paths,
        dt,
        config.strike,
        config.option_type,
        config.initial_policy_rate,
        config.cost_rate,
        bs_price,
        delta_ratios,
    )
    mlp_ratios = generate_policy_hedge_ratios(
        training_result.policy, eval_paths, dt, config.strike, config.option_maturity_years
    )
    mlp_result = simulate_self_financing_hedge(
        eval_paths,
        dt,
        config.strike,
        config.option_type,
        config.initial_policy_rate,
        config.cost_rate,
        bs_price,
        mlp_ratios,
    )
    delta_cvar = historical_expected_shortfall(delta_result.terminal_loss, config.cvar_alpha)
    mlp_cvar = historical_expected_shortfall(mlp_result.terminal_loss, config.cvar_alpha)

    # -- 8. export an auditable report -----------------------------------------
    model_card: ModelCard = build_deep_hedge_model_card(
        training_result.policy,
        config.n_train_paths,
        config.seed,
        float(mlp_cvar),
        float(mlp_result.terminal_loss.mean()),
        config.cvar_alpha,
    )
    result_payload = {
        "ledger_state_hash": ledger_state_hash,
        "policy_rate_path": [round(r, 10) for r in policy_rate_path],
        "black_scholes_price": round(bs_price, 10),
        "monte_carlo_price": round(mc_result.price, 10),
        "delta_hedge_cvar": round(float(delta_cvar), 10),
        "mlp_hedge_cvar": round(float(mlp_cvar), 10),
        "valid": len(invalid_reasons) == 0,
    }
    manifest = RunManifest(
        run_id=new_run_id("pmth-demo"),
        created_at=now_iso(),
        seed=config.seed,
        config={
            "n_macro_steps": config.n_macro_steps,
            "policy_shock_bps": config.policy_shock_bps,
            "strike": config.strike,
            "option_maturity_years": config.option_maturity_years,
            "volatility": config.volatility,
        },
        result_hash=compute_result_hash(result_payload),
    )
    evidence_bundle = build_evidence_bundle(
        manifest, [model_card], current_repository_gate_report()
    )

    return DemoRunResult(
        valid=len(invalid_reasons) == 0,
        invalid_reasons=tuple(invalid_reasons),
        ledger_state_hash=ledger_state_hash,
        policy_rate_path=tuple(policy_rate_path),
        black_scholes_price=float(bs_price),
        monte_carlo_price=float(mc_result.price),
        monte_carlo_standard_error=float(mc_result.standard_error),
        heston_feller_ratio=float(heston_feller_ratio),
        delta_hedge_cvar=float(delta_cvar),
        mlp_hedge_cvar=float(mlp_cvar),
        manifest=manifest,
        evidence_bundle=evidence_bundle,
    )
