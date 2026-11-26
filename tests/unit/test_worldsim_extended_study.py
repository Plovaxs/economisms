"""The extended world study: every question is answered and a small run is reproducible."""

from __future__ import annotations

import json

from prometheus.orchestration import worldsim_extended_study as study


def test_a_small_run_answers_every_question_and_is_reproducible() -> None:
    kwargs = {"n_seeds": 8, "workers": 1, "sensitivity_seeds": 2, "train_seeds": 12}
    first = study.run_study(**kwargs)
    second = study.run_study(**kwargs)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert set(first["hypotheses"]) == {
        "E-A_recapitalisation_reduces_failed_banks",
        "E-B_recapitalisation_raises_public_debt_at_the_end",
        "E-C_counter_cyclical_rule_raises_the_worst_output_gap",
        "E-D_foreign_currency_bank_debt_raises_failed_banks",
        "E-E_firm_leverage_raises_failed_banks_volatile_full",
        "E-G_moral_hazard_raises_the_total_injected",
        "E-F_learned_warning_beats_the_composite_out_of_sample",
    }
    assert first["arms"]["stressed_full/recapitalise"]["mean_injection"] > 0.0
    assert first["arms"]["stressed_full/none"]["mean_injection"] == 0.0
    warning = first["early_warning"]
    assert 0.0 <= warning["auc_composite"] <= warning["auc_oracle_knows_the_regime"] <= 1.0
    assert len(first["sensitivity_stressed_full_25_percent_moves"]) == len(
        study.sensitivity.PARAMETERS
    )


def test_the_parallel_and_serial_arms_agree() -> None:
    config = study.full_scenario("volatile_full")
    serial = study.run_arm(config, range(6), workers=1)
    parallel = study.run_arm(config, range(6), workers=2)
    assert all((serial[k] == parallel[k]).all() for k in serial)
