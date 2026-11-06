import json
from dataclasses import replace

import pytest

from prometheus.core.ledger import Side
from prometheus.core.money import Money
from prometheus.econosim.economy import Economy
from prometheus.econosim.monetary_operations import MonetaryOperationsConfig
from prometheus.evidence.export import export_evidence_bundle
from prometheus.experiments.manifest import compute_result_hash
from prometheus.orchestration.monetary_operations_run import (
    MODEL_CONVENTION,
    main,
    run_monetary_operations,
)
from prometheus.orchestration.replay import (
    read_evidence_bundle,
    replay_evidence_bundle,
    verified_payload,
)


@pytest.fixture(scope="module")
def config() -> MonetaryOperationsConfig:
    return MonetaryOperationsConfig(n_steps=12)


@pytest.fixture(scope="module")
def result(config: MonetaryOperationsConfig):
    return run_monetary_operations(config)


def test_run_completes_all_steps_with_a_valid_evidence_payload(config, result) -> None:
    assert result.valid and result.invalid_reasons == ()
    assert len(result.steps) == config.n_steps
    payload = result.evidence_bundle["monetary_operations"]
    assert payload["accounting_convention"] == "central-bank-ledger-stephooks-v1"
    assert payload["model_convention"] == MODEL_CONVENTION
    assert compute_result_hash(payload) == result.manifest.result_hash


def test_same_config_is_fully_deterministic() -> None:
    config = MonetaryOperationsConfig(n_steps=10, seed=7)
    first = run_monetary_operations(config)
    second = run_monetary_operations(config)
    assert first.manifest.result_hash == second.manifest.result_hash
    assert [s.ledger_state_hash for s in first.steps] == [
        s.ledger_state_hash for s in second.steps
    ]


def test_different_seed_changes_the_result() -> None:
    base = MonetaryOperationsConfig(n_steps=10, seed=1)
    other = replace(base, seed=2)
    first = run_monetary_operations(base)
    second = run_monetary_operations(other)
    assert first.manifest.result_hash != second.manifest.result_hash


def test_zero_shock_std_leaves_the_policy_rate_at_its_starting_value(config) -> None:
    """With policy_rate_shock_std=0 and initial_policy_rate == neutral, mean
    reversion contributes exactly zero every step -- the rate never moves,
    so every OMO decision is 'none'."""
    still = replace(config, policy_rate_shock_std=0.0)
    result = run_monetary_operations(still)
    for step in result.steps:
        assert step.action.omo_side == "none"


def test_corrupted_ledger_halts_before_any_completed_step(config, monkeypatch) -> None:
    original = Economy.check_integrity

    def corrupt(economy: Economy) -> None:
        first_account_id = next(iter(economy.ledger._accounts))
        economy.ledger.account(first_account_id)._apply(Side.DEBIT, Money(1))
        original(economy)

    monkeypatch.setattr(Economy, "check_integrity", corrupt)
    invalid = run_monetary_operations(config)
    assert not invalid.valid and not invalid.steps
    assert "LedgerIdentityViolation" in invalid.invalid_reasons[0]


def test_full_json_round_trip_and_replay_preserve_the_exact_result(result, tmp_path) -> None:
    path = export_evidence_bundle(result.evidence_bundle, tmp_path / "monetary_operations.json")
    bundle = read_evidence_bundle(path)
    assert compute_result_hash(bundle["monetary_operations"]) == result.manifest.result_hash
    replay = replay_evidence_bundle(bundle)
    assert replay.matches
    assert replay.observed_hash == result.manifest.result_hash


@pytest.mark.parametrize(
    "overrides",
    [
        {"n_steps": 0},
        {"seed": -1},
        {"discount_window_start_step": 99},
        {"max_leverage": 0.0},
        {"policy_rate_shock_std": -1.0},
    ],
)
def test_invalid_configuration_is_rejected(config, overrides) -> None:
    with pytest.raises(ValueError):
        replace(config, **overrides)


def test_from_dict_rejects_invalid_encoding_before_any_run_work(config) -> None:
    from dataclasses import asdict

    values = asdict(config)
    values["bank_a_capital"] = {"minor_units": "nope", "currency": "USD"}
    with pytest.raises(ValueError):
        MonetaryOperationsConfig.from_dict(values)


def test_cli_exports_evidence_with_a_matching_result_hash(tmp_path, capsys) -> None:
    path = tmp_path / "monetary_operations.json"
    assert main(["--steps", "6", "--seed", "3", "--output", str(path)]) == 0
    summary = json.loads(capsys.readouterr().out)
    payload = json.loads(path.read_text())["monetary_operations"]
    assert summary["valid"] and summary["completed_steps"] == 6
    assert summary["result_hash"] == compute_result_hash(payload)


def test_cli_rejects_invalid_config_without_creating_an_artifact(tmp_path) -> None:
    path = tmp_path / "monetary_operations.json"
    with pytest.raises(SystemExit) as error:
        main(["--steps", "0", "--output", str(path)])
    assert error.value.code == 2
    assert not path.exists()


def test_cli_rejects_invalid_interbank_transfer_every(tmp_path) -> None:
    with pytest.raises(SystemExit) as error:
        main(["--interbank-transfer-every", "0"])
    assert error.value.code == 2


def test_replay_rejects_a_tampered_model_convention(result) -> None:
    import copy

    bundle = copy.deepcopy(result.evidence_bundle)
    bundle["monetary_operations"]["model_convention"] = "some-other-convention"
    with pytest.raises(ValueError, match="unsupported monetary operations model_convention"):
        verified_payload(bundle)
