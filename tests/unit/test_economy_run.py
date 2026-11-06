import json
from dataclasses import asdict, replace
from fractions import Fraction as F

import pytest

from prometheus.core.ledger import Side
from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.evidence.export import export_evidence_bundle
from prometheus.experiments.manifest import compute_result_hash
from prometheus.orchestration.economy_run import EconomyRunConfig, main, run_economy
from prometheus.orchestration.replay import read_evidence_bundle, replay_evidence_bundle


@pytest.fixture(scope="module")
def config():
    return EconomyRunConfig()


@pytest.fixture(scope="module")
def result(config):
    return run_economy(config)


def test_every_step_conserves_cash_equity_and_physical_inventory(config, result) -> None:
    assert result.valid and result.invalid_reasons == ()
    assert len(result.steps) == config.n_steps
    injected = config.firm_capital + config.household_initial_cash * config.n_households
    for step in result.steps:
        settlement = step.settlement
        assert step.total_cash == step.total_equity == injected
        assert step.firm_cash.minor_units >= 0
        assert all(cash.minor_units >= 0 for _, cash in step.household_cash)
        assert config.initial_inventory + step.cumulative_production == (
            settlement.inventory_after + step.cumulative_sales
        )
        assert settlement.inventory_before + settlement.produced == (
            settlement.inventory_after + settlement.sales.realized_quantity
        )
        assert settlement.produced == settlement.wages.realized_quantity * step.actions.productivity
        assert settlement.wages.total_paid <= step.actions.payroll_budget
        assert 0 <= settlement.wages.rounding_remainder < 1
        assert 0 <= settlement.sales.rounding_remainder < 1
        for market in (settlement.labor, settlement.goods):
            assert len(market.evaluations) <= config.max_price_evaluations
            assert market.status != "iteration_limit"
        for paid in (settlement.wages, settlement.sales):
            if paid.transaction is not None:
                assert paid.transaction.is_balanced()


def test_prices_are_discovered_and_tick_residuals_are_visible(config, result) -> None:
    first = result.steps[0].settlement
    assert first.labor.allocation.price == Money(966)
    assert first.goods.allocation.price == Money(108)
    assert first.labor.allocation.price != config.initial_wage
    assert first.goods.allocation.price != config.initial_goods_price
    assert first.labor.status == first.goods.status == "tick_limited"
    assert first.labor.allocation.excess_demand != 0
    assert first.goods.allocation.excess_demand != 0


def test_firm_cash_follows_actual_rounded_payroll_and_sales(config, result) -> None:
    cash = config.firm_capital
    previous_households = {
        name: config.household_initial_cash for name, _ in result.steps[0].household_cash
    }
    for step in result.steps:
        settlement = step.settlement
        cash = cash - settlement.wages.total_paid + settlement.sales.total_paid
        assert step.firm_cash == cash
        wage_by_id = {item.household_id: item.paid for item in settlement.wages.payments}
        sales_by_id = {item.household_id: item.paid for item in settlement.sales.payments}
        for name, balance in step.household_cash:
            assert balance == previous_households[name] + wage_by_id[name] - sales_by_id[name]
            assert sales_by_id[name] <= wage_by_id[name]
            previous_households[name] = balance


def test_future_productivity_shock_cannot_change_earlier_prices_or_balances(config, result) -> None:
    control = run_economy(replace(config, productivity_shock_step=None))
    before = config.productivity_shock_step - 1
    assert result.steps[:before] == control.steps[:before]
    assert result.steps[before].actions.productivity == (
        control.steps[before].actions.productivity * config.productivity_shock_multiplier
    )
    assert (
        result.steps[-1].settlement.goods.allocation.price
        > control.steps[-1].settlement.goods.allocation.price
    )


def test_seeded_productivity_noise_replays_and_a_different_seed_changes_it(config) -> None:
    noisy = replace(config, productivity_noise_std=0.02)
    first, second = run_economy(noisy), run_economy(noisy)
    assert first.valid and second.valid
    assert first.manifest.result_hash == second.manifest.result_hash
    different = run_economy(replace(noisy, seed=10))
    assert first.steps[0].actions.productivity != different.steps[0].actions.productivity


def test_negative_productivity_noise_factor_is_clipped_and_explicitly_reported(config, monkeypatch):
    from prometheus.core.seeds import SeedHierarchy

    class ForcedNoise:
        def normal(self, *args):
            return -2.0

    monkeypatch.setattr(SeedHierarchy, "stream", lambda *args: ForcedNoise())
    clipped = run_economy(config)
    assert clipped.valid
    assert all(step.actions.noise_clamped for step in clipped.steps)
    assert all(step.actions.productivity == 0 for step in clipped.steps)
    assert all(step.settlement.produced == 0 for step in clipped.steps)


def test_zero_firm_funds_ration_demand_without_creating_cash(config) -> None:
    unfunded = run_economy(replace(config, firm_capital=Money(0)))
    assert unfunded.valid
    for step in unfunded.steps:
        assert step.actions.payroll_budget_binding
        assert step.actions.payroll_budget == Money(0)
        assert step.settlement.wages.total_paid == Money(0)
        assert step.settlement.produced == 0
        assert step.settlement.sales.total_paid == Money(0)


def test_household_saving_can_exhaust_firm_funding_without_an_overdraft(config) -> None:
    saving = run_economy(replace(config, firm_capital=Money(1000), consumption_propensity=F(0)))
    assert saving.valid
    assert saving.steps[0].actions.payroll_budget == Money(1000)
    assert saving.steps[-1].firm_cash == Money(0)
    assert sum(step.settlement.wages.total_paid.minor_units for step in saving.steps) == 1000


def test_unresolved_price_search_halts_with_invalid_evidence(config) -> None:
    unresolved = run_economy(replace(config, max_price_evaluations=3))
    assert not unresolved.valid
    assert not unresolved.steps
    assert "price search evaluation limit" in unresolved.invalid_reasons[0]
    assert unresolved.evidence_bundle["economy"]["final_inventory"] is None


def test_optional_unresolved_price_rationing_is_recorded_without_false_clearing(config) -> None:
    approximate = run_economy(
        replace(config, max_price_evaluations=3, require_price_resolution=False)
    )
    assert approximate.valid
    assert approximate.steps[0].settlement.labor.status == "iteration_limit"


def test_corrupted_ledger_halts_before_any_completed_step(config, monkeypatch) -> None:
    original = Economy.check_integrity

    def corrupt(economy):
        economy.ledger.account("firm-1:deposit")._apply(Side.DEBIT, Money(1))
        original(economy)

    monkeypatch.setattr(Economy, "check_integrity", corrupt)
    invalid = run_economy(config)
    assert not invalid.valid and not invalid.steps
    assert "LedgerIdentityViolation" in invalid.invalid_reasons[0]


def test_full_json_round_trip_and_replay_preserve_exact_quantities(result, tmp_path) -> None:
    path = export_evidence_bundle(result.evidence_bundle, tmp_path / "economy.json")
    bundle = read_evidence_bundle(path)
    assert compute_result_hash(bundle["economy"]) == result.manifest.result_hash
    assert bundle["economy"]["config"]["labor_supply_slope"] == {"numerator": 1, "denominator": 50}
    replay = replay_evidence_bundle(bundle)
    assert replay.matches
    assert replay.observed_hash == result.manifest.result_hash


@pytest.mark.parametrize(
    "overrides",
    [
        {"n_steps": 0},
        {"n_households": 0},
        {"seed": -1},
        {"firm_capital": Money(-1)},
        {"household_initial_cash": Money(1, "EUR")},
        {"consumption_propensity": F(3, 2)},
        {"productivity": F(-1)},
        {"productivity_noise_std": float("nan")},
        {"productivity_shock_step": 99},
        {"wage_floor": Money(0)},
        {"initial_wage": Money(9999)},
        {"max_price_evaluations": 2},
        {"require_price_resolution": 1},
    ],
)
def test_invalid_economic_configuration_is_rejected(config, overrides) -> None:
    with pytest.raises(ValueError):
        replace(config, **overrides)


def test_invalid_rational_encoding_is_rejected_before_replay(config) -> None:
    values = asdict(config)
    values["productivity"] = {"numerator": 1, "denominator": 0}
    with pytest.raises(ValueError):
        EconomyRunConfig.from_dict(values)


def test_cli_exports_price_search_and_atomic_settlement_evidence(tmp_path, capsys) -> None:
    path = tmp_path / "economy.json"
    assert main(["--steps", "2", "--no-shock", "--output", str(path)]) == 0
    summary = json.loads(capsys.readouterr().out)
    payload = json.loads(path.read_text())["economy"]
    assert summary["valid"] and summary["completed_steps"] == 2
    assert summary["result_hash"] == compute_result_hash(payload)


def test_cli_rejects_invalid_config_without_creating_an_artifact(tmp_path) -> None:
    path = tmp_path / "economy.json"
    with pytest.raises(SystemExit) as error:
        main(["--steps", "0", "--output", str(path)])
    assert error.value.code == 2
    assert not path.exists()
