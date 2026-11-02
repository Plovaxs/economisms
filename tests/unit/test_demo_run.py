import pytest

from prometheus.core.ledger import Side
from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.orchestration.demo_run import DemoRunConfig, run_demo


@pytest.fixture(scope="module")
def happy_path_result():
    return run_demo(DemoRunConfig(n_train_epochs=40))


def test_default_config_run_is_valid(happy_path_result) -> None:
    assert happy_path_result.valid
    assert happy_path_result.invalid_reasons == ()


def test_all_report_fields_are_populated_on_a_valid_run(happy_path_result) -> None:
    r = happy_path_result
    assert r.ledger_state_hash is not None
    assert r.policy_rate_path is not None
    assert r.black_scholes_price is not None
    assert r.monte_carlo_price is not None
    assert r.monte_carlo_standard_error is not None
    assert r.heston_feller_ratio is not None
    assert r.delta_hedge_cvar is not None
    assert r.mlp_hedge_cvar is not None
    assert r.manifest is not None
    assert r.evidence_bundle is not None


def test_policy_rate_path_length_and_known_shock(happy_path_result) -> None:
    config = DemoRunConfig()
    path = happy_path_result.policy_rate_path
    assert len(path) == config.n_macro_steps + 1
    # a +200bp shock lands exactly at policy_shock_step, visible as a jump
    jump = path[config.policy_shock_step] - path[config.policy_shock_step - 1]
    assert jump == pytest.approx(config.policy_shock_bps / 10_000.0, abs=1e-9)


def test_result_hash_reproducible_given_identical_config() -> None:
    config = DemoRunConfig(n_train_epochs=20, n_train_paths=500, n_eval_paths=500)
    result_a = run_demo(config)
    result_b = run_demo(config)
    assert result_a.manifest.result_hash == result_b.manifest.result_hash
    assert result_a.manifest.run_id != result_b.manifest.run_id


def test_evidence_bundle_carries_disclaimer_and_is_tagged_no_go() -> None:
    config = DemoRunConfig(n_train_epochs=20, n_train_paths=500, n_eval_paths=500)
    result = run_demo(config)
    bundle = result.evidence_bundle
    assert "SIMULATED DATA" in bundle["disclaimer"]
    assert bundle["source_tag"] == "prometheus-simulation"
    assert bundle["gate_report"]["decision"] == "NO-GO"
    assert bundle["model_cards"][0]["approval_status"] == "NOT REVIEWED"


def test_valuation_tolerance_check_can_actually_fail() -> None:
    """Not just a check that always passes: an absurdly tight tolerance
    must make the run report invalid, with the report fields still
    populated (marked invalid, not silently published -- not crashed
    either)."""
    config = DemoRunConfig(
        n_train_epochs=20,
        n_train_paths=500,
        n_eval_paths=500,
        mc_price_tolerance_std_errors=0.0001,
    )
    result = run_demo(config)
    assert not result.valid
    assert any(r.startswith("valuation tolerance:") for r in result.invalid_reasons)
    # still a full report, not a crash or an empty result:
    assert result.black_scholes_price is not None
    assert result.delta_hedge_cvar is not None


def test_corrupted_ledger_is_caught_via_injected_economy() -> None:
    """The invariant check must catch a genuinely broken ledger, not just
    one that was never going to break. Bypasses the public ledger API the
    way PR-002's ECO-16 test does, to simulate a bug rather than assert a
    tautology."""
    economy = Economy()
    bank = economy.add_bank("bank-1", max_leverage=10.0)
    bank.capitalize(Money(1_000_000_00, "USD"))
    household = economy.add_household("hh-1")
    household.receive_income(Money(10_000_00, "USD"))
    economy.ledger.account("hh-1:deposit")._apply(Side.DEBIT, Money(1, "USD"))

    result = run_demo(DemoRunConfig(), economy=economy)

    assert not result.valid
    assert any(r.startswith("invariant:") for r in result.invalid_reasons)
    # short-circuited before any downstream stage ran:
    assert result.black_scholes_price is None
    assert result.manifest is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"n_macro_steps": 0},
        {"policy_shock_step": 99},
        {"option_maturity_years": 0.0},
    ],
)
def test_invalid_config_rejected_at_construction(overrides: dict) -> None:
    with pytest.raises(ValueError):
        DemoRunConfig(**overrides)
