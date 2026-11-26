"""The world study: the written verdict rule, and a short run that answers every question."""

from __future__ import annotations

import json

import numpy as np
import pytest

from prometheus.orchestration import worldsim_study as study


def test_verdict_follows_the_written_rule() -> None:
    assert study.verdict(0.1, 0.4) == "SUPPORTED"
    assert study.verdict(-0.4, -0.1) == "CONTRADICTED"
    assert study.verdict(-0.1, 0.2) == "INCONCLUSIVE"
    assert study.verdict(0.52, 0.6, null=0.5) == "SUPPORTED"


def test_max_drawdown_fraction() -> None:
    assert study.max_drawdown_fraction(np.array([1.0, 2.0, 1.0, 3.0])) == pytest.approx(-0.5)
    assert study.max_drawdown_fraction(np.array([1.0, 1.1, 1.2])) == 0.0


def test_a_short_run_answers_every_question_and_is_reproducible() -> None:
    first = study.run_study(n_seeds=6, n_months=120)
    second = study.run_study(n_seeds=6, n_months=120)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert set(first["scenarios"]) == {"calm", "volatile", "stressed"}
    assert set(first["hypotheses"]) == {
        "W-A_some_rule_has_shallower_drawdown_than_equal_weight_volatile",
        "W-B_crises_concentrate_wealth_stressed_minus_calm_top10_share",
        "W-C_fire_sales_amplify_bank_failures_stressed",
        "W-D_warning_composite_has_information_volatile",
    }
    for rule_row in first["scenarios"]["volatile"]["rules"].values():
        assert rule_row["median_max_drawdown"] <= 0.0
    for name in ("calm", "volatile", "stressed"):
        assert 0.0 <= first["scenarios"][name]["stylised_facts"]["mean_crisis_share"] <= 1.0
