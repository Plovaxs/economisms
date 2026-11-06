import json
import math
from dataclasses import replace
from datetime import date

import numpy as np
import pytest

from prometheus.core.calendar import BusinessDayCalendar, add_months
from prometheus.core.ledger import Side
from prometheus.core.money import Money
from prometheus.core.seeds import SeedHierarchy
from prometheus.econosim.economy import Economy
from prometheus.evidence.export import export_evidence_bundle
from prometheus.experiments.manifest import compute_result_hash
from prometheus.orchestration.multi_step_run import (
    DT,
    MultiStepRunConfig,
    main,
    run_multi_step_simulation,
)
from prometheus.titan.risk_metrics import historical_expected_shortfall


@pytest.fixture(scope="module")
def config():
    return MultiStepRunConfig(
        seed=42,
        n_steps=6,
        policy_shock_step=3,
        start_date=date(2026, 1, 3),
        n_train_paths=64,
        n_train_epochs=3,
        risk_eval_n_paths=128,
    )


@pytest.fixture(scope="module", params=["call", "put"])
def scenario(request, config):
    cfg = replace(config, option_type=request.param)
    return cfg, run_multi_step_simulation(cfg)


def test_all_months_are_completed_and_expiry_is_exact(scenario) -> None:
    config, result = scenario
    assert result.valid and result.invalid_reasons == ()
    assert len(result.steps) == config.n_steps
    calendar = BusinessDayCalendar()
    current_date = calendar.next_business_day(config.start_date)
    for index, step in enumerate(result.steps, 1):
        current_date = calendar.next_business_day(add_months(current_date, 1))
        assert step.step == index
        assert step.step_date == current_date
        assert step.remaining_years == (config.n_steps - index) * DT
        assert len(step.ledger_state_hash) == 64
        assert step.labor_realized_hours == 18.0
        assert step.goods_realized_quantity == 180.0
        assert step.firm_cash_minor == config.firm_seed_capital.minor_units
    terminal = result.steps[-1]
    intrinsic = terminal.spot - config.strike
    payoff = max(intrinsic if config.option_type == "call" else -intrinsic, 0.0)
    assert terminal.remaining_years == 0
    assert terminal.black_scholes_price == payoff
    assert terminal.delta_cvar == -result.delta_final_wealth
    assert terminal.mlp_cvar == -result.mlp_final_wealth
    # No new transaction is charged on an expired option.
    assert terminal.delta_cost == result.steps[-2].delta_cost
    assert terminal.mlp_cost == result.steps[-2].mlp_cost


@pytest.mark.parametrize("policy", ["delta", "mlp"])
def test_trajectory_reconciles_to_independent_cash_flow_calculation(scenario, policy) -> None:
    config, result = scenario
    initial = getattr(result, f"initial_{policy}_hedge")
    holdings = initial.target_holdings
    expected_cost = config.cost_rate * abs(holdings) * config.spot0
    cash = result.initial_premium - holdings * config.spot0 - expected_cost
    turnover = abs(holdings)
    assert initial.spot == config.spot0
    assert initial.cash_after == pytest.approx(cash)
    for step in result.steps:
        cash *= math.exp(step.policy_rate * DT)
        new_holdings = getattr(step, f"{policy}_holdings")
        trade = new_holdings - holdings
        cost = config.cost_rate * abs(trade) * step.spot
        cash -= trade * step.spot + cost
        expected_cost += cost
        turnover += abs(trade)
        holdings = new_holdings
        assert cash == pytest.approx(getattr(step, f"{policy}_cash"))
        assert expected_cost == pytest.approx(getattr(step, f"{policy}_cost"))
        assert turnover == pytest.approx(getattr(step, f"{policy}_turnover"))
    wealth = cash + holdings * result.steps[-1].spot - result.steps[-1].black_scholes_price
    assert wealth == pytest.approx(getattr(result, f"{policy}_final_wealth"))


def test_conditional_risk_uses_physical_portfolio_losses(scenario) -> None:
    config, result = scenario
    first = result.steps[0]
    z = (
        SeedHierarchy(config.seed)
        .stream("conditional-risk/1")
        .standard_normal(config.risk_eval_n_paths)
    )
    terminal = first.spot * np.exp(
        (first.policy_rate + config.equity_risk_premium - 0.5 * config.volatility**2)
        * first.remaining_years
        + config.volatility * np.sqrt(first.remaining_years) * z
    )
    intrinsic = terminal - config.strike
    payoff = np.maximum(intrinsic if config.option_type == "call" else -intrinsic, 0.0)
    for policy in ("delta", "mlp"):
        cash = getattr(first, f"{policy}_cash")
        holdings = getattr(first, f"{policy}_holdings")
        losses = (
            payoff - holdings * terminal - cash * np.exp(first.policy_rate * first.remaining_years)
        )
        expected = historical_expected_shortfall(losses, config.cvar_alpha)
        assert getattr(first, f"{policy}_cvar") == pytest.approx(expected)


def test_export_round_trip_preserves_full_result_hash_and_metric_meaning(
    scenario, tmp_path
) -> None:
    config, result = scenario
    path = export_evidence_bundle(result.evidence_bundle, tmp_path / "bundle.json")
    bundle = json.loads(path.read_text())
    assert compute_result_hash(bundle["simulation"]) == result.manifest.result_hash
    assert bundle["run_manifest"]["config"]["cost_rate"] == config.cost_rate
    assert bundle["run_manifest"]["config"]["start_date"] == config.start_date.isoformat()
    assert bundle["run_manifest"]["config"]["firm_seed_capital"]["minor_units"] == 200_000
    assert bundle["simulation"]["accounting_convention"] == "trade-then-accrue-v1"
    assert "SIMULATED DATA" in bundle["disclaimer"]
    assert bundle["gate_report"]["decision"] == "NO-GO"
    metrics = bundle["model_cards"][0]["primary_metrics"]
    assert metrics == {"realized_terminal_loss": -result.mlp_final_wealth}
    assert not any("cvar" in name for name in metrics)


def test_replay_is_identical_but_run_id_is_unique(config) -> None:
    first = run_multi_step_simulation(config)
    second = run_multi_step_simulation(config)
    assert first.steps == second.steps
    assert first.manifest.result_hash == second.manifest.result_hash
    assert first.manifest.run_id != second.manifest.run_id


def test_future_policy_shock_cannot_change_earlier_results(config) -> None:
    shocked = run_multi_step_simulation(config)
    control = run_multi_step_simulation(replace(config, policy_shock_bps=0.0))
    before = config.policy_shock_step - 1
    assert shocked.initial_mlp_hedge == control.initial_mlp_hedge
    assert shocked.steps[:before] == control.steps[:before]
    assert shocked.steps[before].policy_rate - control.steps[before].policy_rate == pytest.approx(
        config.policy_shock_bps / 10_000.0
    )
    assert shocked.steps[before].spot != control.steps[before].spot


def test_risk_sample_count_cannot_change_market_or_hedge_decisions(config) -> None:
    first = run_multi_step_simulation(config)
    second = run_multi_step_simulation(replace(config, risk_eval_n_paths=17))
    for a, b in zip(first.steps, second.steps, strict=True):
        assert (a.spot, a.mlp_holdings, a.delta_holdings, a.ledger_state_hash) == (
            b.spot,
            b.mlp_holdings,
            b.delta_holdings,
            b.ledger_state_hash,
        )
    assert first.mlp_final_wealth == second.mlp_final_wealth


def test_single_month_has_only_the_initial_hedge(config) -> None:
    result = run_multi_step_simulation(replace(config, n_steps=1, policy_shock_step=1))
    assert result.valid and len(result.steps) == 1
    assert result.steps[0].delta_cost == result.initial_delta_hedge.cost
    assert result.steps[0].mlp_cost == result.initial_mlp_hedge.cost


def test_firm_funding_failure_preserves_completed_steps_and_invalid_evidence(config) -> None:
    # 400 dollars funds two full 180-dollar wage bills; households save all wages.
    result = run_multi_step_simulation(
        replace(config, firm_seed_capital=Money(40_000), consumption_propensity=0.0)
    )
    assert not result.valid
    assert len(result.steps) == 2
    assert "step 3: InsufficientFundsError" in result.invalid_reasons[0]
    assert result.delta_final_wealth is None and result.mlp_final_wealth is None
    assert result.evidence_bundle["simulation"]["valid"] is False
    assert compute_result_hash(result.evidence_bundle["simulation"]) == result.manifest.result_hash


def test_corrupted_ledger_cannot_produce_a_valid_run(config, monkeypatch) -> None:
    original = Economy.check_integrity

    def corrupt(economy):
        economy.ledger.account("firm-1:deposit")._apply(Side.DEBIT, Money(1))
        original(economy)

    monkeypatch.setattr(Economy, "check_integrity", corrupt)
    result = run_multi_step_simulation(config)
    assert not result.valid and not result.steps
    assert "LedgerIdentityViolation" in result.invalid_reasons[0]
    assert result.mlp_final_wealth is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"n_steps": 0},
        {"n_steps": True},
        {"seed": -1},
        {"seed": 0.5},
        {"policy_shock_step": 0},
        {"policy_shock_step": 7},
        {"volatility": float("nan")},
        {"strike": float("inf")},
        {"cost_rate": -0.1},
        {"n_train_paths": 0},
        {"n_train_epochs": 0},
        {"risk_eval_n_paths": 0},
        {"consumption_propensity": 1.01},
        {"goods_price": Money(0)},
        {"wage_rate_per_hour": Money(100, "EUR")},
        {"option_maturity_years": 1.0},
        {"option_type": "invalid"},
        {"cvar_alpha": 1.0},
    ],
)
def test_invalid_configuration_is_rejected_before_training(config, overrides) -> None:
    with pytest.raises(ValueError):
        replace(config, **overrides)


def test_cli_exports_a_replayable_bundle_and_prints_summary(tmp_path, capsys) -> None:
    path = tmp_path / "new" / "bundle.json"
    code = main(
        [
            "--steps",
            "1",
            "--train-paths",
            "16",
            "--train-epochs",
            "1",
            "--risk-paths",
            "16",
            "--no-shock",
            "--output",
            str(path),
        ]
    )
    assert code == 0
    summary = json.loads(capsys.readouterr().out)
    bundle = json.loads(path.read_text())
    assert summary["valid"] and summary["completed_steps"] == 1
    assert summary["result_hash"] == compute_result_hash(bundle["simulation"])


def test_cli_rejects_invalid_config_before_creating_output(tmp_path) -> None:
    path = tmp_path / "bundle.json"
    with pytest.raises(SystemExit) as error:
        main(["--steps", "0", "--output", str(path)])
    assert error.value.code == 2
    assert not path.exists()
