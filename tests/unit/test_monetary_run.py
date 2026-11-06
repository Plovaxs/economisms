import json
import math
from dataclasses import asdict, replace
from fractions import Fraction as F

import pytest

from prometheus.core.money import Money
from prometheus.econosim.price_economy import EconomyRunConfig
from prometheus.evidence.export import export_evidence_bundle
from prometheus.experiments.manifest import compute_result_hash
from prometheus.hedging.comparison import HedgeComparisonSettings
from prometheus.orchestration.economy_run import run_economy
from prometheus.orchestration.monetary_run import MonetaryRunConfig, main, run_monetary_simulation
from prometheus.orchestration.replay import read_evidence_bundle, replay_evidence_bundle


@pytest.fixture(scope="module")
def config():
    return MonetaryRunConfig(
        seed=42,
        economy=EconomyRunConfig(n_steps=8),
        hedge=HedgeComparisonSettings(
            n_train_paths=32, n_train_epochs=3, batch_size=16, risk_eval_n_paths=64
        ),
    )


@pytest.fixture(scope="module", params=["call", "put"])
def result(request, config):
    cfg = replace(config, hedge=replace(config.hedge, option_type=request.param))
    return cfg, run_monetary_simulation(cfg)


def test_coupled_steps_preserve_economic_conservation_and_opening_rate_timing(result) -> None:
    config, run = result
    assert run.valid and run.invalid_reasons == ()
    assert len(run.steps) == config.economy.n_steps
    previous_rate = config.initial_rate
    for step in run.steps:
        assert step.financial.funding_rate == step.policy.previous_rate == previous_rate
        assert step.valuation.closing_rate == step.policy.next_rate
        assert step.financial.physical_drift == previous_rate + config.hedge.equity_risk_premium
        assert step.economic.total_cash == step.economic.total_equity == Money(400_000)
        assert step.economic.actions.payroll_budget <= step.adjusted_payroll_target
        assert step.payroll_multiplier == F(
            str(
                math.exp(
                    -config.payroll_rate_sensitivity * (previous_rate - config.policy.neutral_rate)
                )
            )
        )
        if step.policy.signal is not None:
            assert step.policy.signal.latest_step < step.step
            assert all(
                item.published_at <= step.economic.step_date for item in step.policy.signal.inputs
            )
        for observation in step.new_publications:
            assert observation.observation_at == step.economic.step_date
            assert observation.published_at > observation.observation_at
        previous_rate = step.policy.next_rate
    assert run.steps[-1].risk.delta_cvar == -run.delta_final_wealth
    assert run.steps[-1].risk.mlp_cvar == -run.mlp_final_wealth
    assert run.steps[-1].valuation.remaining_years == 0


def test_delayed_publication_prevents_any_policy_or_real_activity_feedback(config) -> None:
    cfg = replace(config, publication_lag_months=20)
    coupled = run_monetary_simulation(cfg)
    standalone = run_economy(cfg.economy)
    assert coupled.valid and standalone.valid
    assert tuple(step.economic for step in coupled.steps) == standalone.steps
    assert all(step.policy.signal is None for step in coupled.steps)
    assert all(step.policy.next_rate == cfg.initial_rate for step in coupled.steps)


@pytest.mark.parametrize("lag", [1, 2])
def test_productivity_shock_affects_policy_only_after_release_and_market_one_interval_later(
    config, lag
) -> None:
    cfg = replace(config, publication_lag_months=lag, payroll_rate_sensitivity=0.0)
    shocked = run_monetary_simulation(cfg)
    control = run_monetary_simulation(
        replace(cfg, economy=replace(cfg.economy, productivity_shock_step=None))
    )
    assert shocked.valid and control.valid
    shock = cfg.economy.productivity_shock_step
    policy_step = shock + lag
    assert shocked.steps[: shock - 1] == control.steps[: shock - 1]
    assert [step.policy for step in shocked.steps[: policy_step - 1]] == [
        step.policy for step in control.steps[: policy_step - 1]
    ]
    assert (
        shocked.steps[policy_step - 1].policy.next_rate
        != control.steps[policy_step - 1].policy.next_rate
    )
    assert [step.financial for step in shocked.steps[:policy_step]] == [
        step.financial for step in control.steps[:policy_step]
    ]
    assert (
        shocked.steps[policy_step].financial.closing_spot
        != control.steps[policy_step].financial.closing_spot
    )
    assert (
        shocked.evidence_bundle["monetary"]["training"]["policy_content_hash"]
        == (control.evidence_bundle["monetary"]["training"]["policy_content_hash"])
    )


def test_last_step_productivity_shock_cannot_change_financial_history(config) -> None:
    cfg = replace(
        config, economy=replace(config.economy, productivity_shock_step=config.economy.n_steps)
    )
    shocked = run_monetary_simulation(cfg)
    control = run_monetary_simulation(
        replace(cfg, economy=replace(cfg.economy, productivity_shock_step=None))
    )
    assert shocked.valid and control.valid
    assert (
        shocked.steps[-1].economic.actions.productivity
        != control.steps[-1].economic.actions.productivity
    )
    assert [step.financial for step in shocked.steps] == [step.financial for step in control.steps]
    assert shocked.delta_final_wealth == control.delta_final_wealth
    assert shocked.mlp_final_wealth == control.mlp_final_wealth


def test_hedge_cash_reconciles_with_opening_rates_and_actual_executions(result) -> None:
    config, run = result
    payload = run.evidence_bundle["monetary"]
    for policy in ("delta", "mlp"):
        initial = payload[f"initial_{policy}_hedge"]
        cash, holdings = initial["cash_after"], initial["target_holdings"]
        for step in run.steps:
            target = getattr(step.valuation, f"{policy}_holdings")
            trade = target - holdings
            spot = step.financial.closing_spot
            cost = config.hedge.cost_rate * abs(trade) * spot
            cash = cash * math.exp(step.financial.funding_rate / 12) - trade * spot - cost
            assert cash == pytest.approx(getattr(step.valuation, f"{policy}_cash"), abs=1e-9)
            holdings = target
        final = (
            cash
            + holdings * run.steps[-1].financial.closing_spot
            - run.steps[-1].valuation.option_value
        )
        assert final == pytest.approx(getattr(run, f"{policy}_final_wealth"))


def test_higher_opening_rates_reduce_desired_payroll_and_real_activity(config) -> None:
    with_channel = run_monetary_simulation(config)
    without_channel = run_monetary_simulation(replace(config, payroll_rate_sensitivity=0.0))
    assert with_channel.valid and without_channel.valid
    tightened = [
        step
        for step in with_channel.steps
        if step.financial.funding_rate > config.policy.neutral_rate
    ]
    assert tightened
    assert all(step.adjusted_payroll_target < config.economy.payroll_target for step in tightened)
    assert with_channel.steps[-1].economic.settlement.wages.realized_quantity < (
        without_channel.steps[-1].economic.settlement.wages.realized_quantity
    )


def test_zero_trade_produces_no_invented_inflation_and_policy_stays_in_warmup(config) -> None:
    run = run_monetary_simulation(
        replace(config, economy=replace(config.economy, firm_capital=Money(0)))
    )
    assert run.valid
    assert not run.evidence_bundle["monetary"]["publication_ledger"]
    assert all(step.policy.signal is None for step in run.steps)
    assert all(step.policy.next_rate == config.initial_rate for step in run.steps)


def test_price_search_failure_halts_before_financial_history_and_omits_terminal_wealth(
    config,
) -> None:
    run = run_monetary_simulation(
        replace(config, economy=replace(config.economy, max_price_evaluations=3))
    )
    assert not run.valid and not run.steps
    assert "economic_settlement_and_publication" in run.invalid_reasons[0]
    assert run.delta_final_wealth is None and run.mlp_final_wealth is None


def test_conditional_risk_sample_count_cannot_affect_prices_rates_trades_or_market(config) -> None:
    first = run_monetary_simulation(config)
    second = run_monetary_simulation(
        replace(config, hedge=replace(config.hedge, risk_eval_n_paths=17))
    )
    for a, b in zip(first.steps, second.steps, strict=True):
        assert a.economic == b.economic
        assert a.policy == b.policy
        assert a.financial == b.financial
        assert a.valuation == b.valuation
    assert first.mlp_final_wealth == second.mlp_final_wealth


def test_full_nested_recipe_json_and_actual_replay(result, tmp_path) -> None:
    _, run = result
    path = export_evidence_bundle(run.evidence_bundle, tmp_path / "monetary.json")
    bundle = read_evidence_bundle(path)
    assert compute_result_hash(bundle["monetary"]) == run.manifest.result_hash
    assert bundle["model_cards"][0]["primary_metrics"] == {
        "realized_terminal_loss": -run.mlp_final_wealth
    }
    assert (
        bundle["model_cards"][0]["content_hash"]
        == bundle["monetary"]["training"]["policy_content_hash"]
    )
    assert replay_evidence_bundle(bundle).matches


@pytest.mark.parametrize(
    "overrides",
    [
        {"publication_lag_months": 0},
        {"inflation_window_months": 0},
        {"initial_rate": 1.0},
        {"potential_output": 0.0},
        {"payroll_rate_sensitivity": -1.0},
        {"seed": True},
    ],
)
def test_invalid_nested_configuration_is_rejected(config, overrides) -> None:
    with pytest.raises(ValueError):
        replace(config, **overrides)


def test_nested_recipe_fields_cannot_silently_use_defaults(config) -> None:
    values = asdict(config)
    del values["policy"]["inertia"]
    with pytest.raises(ValueError, match="complete policy"):
        MonetaryRunConfig.from_dict(values)


def test_cli_exports_coupled_evidence(tmp_path, capsys) -> None:
    output = tmp_path / "monetary.json"
    assert (
        main(
            [
                "--steps",
                "3",
                "--train-paths",
                "16",
                "--batch-size",
                "8",
                "--train-epochs",
                "1",
                "--risk-paths",
                "16",
                "--output",
                str(output),
            ]
        )
        == 0
    )
    summary = json.loads(capsys.readouterr().out)
    payload = json.loads(output.read_text())["monetary"]
    assert summary["valid"] and summary["completed_steps"] == 3
    assert summary["result_hash"] == compute_result_hash(payload)
