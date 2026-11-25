"""PR-215: the tuned, GJR-anchored neural volatility model.

Unit tests of the parts on tiny synthetic markets, plus the committed study output checked for the
properties the selection rule promises (not for a particular winner).
"""

from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from prometheus.orchestration import neural_volatility_v2_study as study
from prometheus.orchestration.market_risk_study import MarketData, prepare_market, trailing_features
from prometheus.titan.garch_family import fit_garch_family, simulate_gjr_garch

COMMITTED = Path(__file__).resolve().parents[2] / "docs" / "numerics" / "neural_volatility_v2.json"


def _write_market(path: Path, first: date, last: date, seed: int) -> Path:
    days = []
    day = first
    while day <= last:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    returns = simulate_gjr_garch(
        len(days) - 1, mu=0.0003, omega=2e-6, alpha=0.04, gamma=0.08, beta=0.88, seed=seed
    )
    prices = 100.0 * np.exp(np.concatenate([[0.0], np.cumsum(returns)]))
    rows = ["date,close", *(f"{d.isoformat()},{p:.6f}" for d, p in zip(days, prices, strict=True))]
    path.write_text("\n".join(rows) + "\n")
    return path


@pytest.fixture(scope="module")
def markets(tmp_path_factory: pytest.TempPathFactory) -> dict[str, MarketData]:
    root = tmp_path_factory.mktemp("v2")
    return {
        "a": prepare_market(
            _write_market(root / "a.csv", date(1985, 1, 1), date(2012, 6, 30), 1), "a"
        ),
        "b": prepare_market(
            _write_market(root / "b.csv", date(1990, 6, 1), date(2012, 3, 31), 2), "b"
        ),
    }


def test_the_grid_has_sixteen_distinct_configurations_simplest_first() -> None:
    grid = study.config_grid()
    assert len(grid) == len(set(grid)) == 16
    assert grid[0] == study.Config("constant", "base", 16, 0.0)
    assert {c.anchor for c in grid} == {"constant", "gjr"}


def test_extended_features_extend_the_original_six_without_changing_them() -> None:
    returns = np.random.default_rng(0).normal(0.0, 0.01, 600)
    extended = study.extended_features(returns)
    base = trailing_features(returns)
    np.testing.assert_array_equal(extended[:, :6], base)
    assert extended.shape == (600, study.EXTENDED_FEATURES)
    assert np.isnan(extended[: study.LONG_LOOKBACK, -1]).all()
    assert not np.isnan(extended[study.LONG_LOOKBACK :]).any()


def test_no_feature_uses_the_return_of_its_own_day_or_later() -> None:
    """The leak test: change a FUTURE return and no earlier feature row moves."""
    rng = np.random.default_rng(1)
    returns = rng.normal(0.0, 0.01, 700)
    before = study.extended_features(returns)
    changed = returns.copy()
    changed[500] += 0.2
    after = study.extended_features(changed)
    np.testing.assert_array_equal(before[:501], after[:501])  # row 500 sees returns[:500] only
    assert not np.array_equal(before[501], after[501])


def test_an_untrained_gjr_anchored_model_reproduces_the_anchor_exactly() -> None:
    x = np.random.default_rng(2).normal(size=(50, 10))
    anchor = np.log(np.full(50, 0.012))
    model = study.AnchoredVolatility(10, 16, x.mean(axis=0), x.std(axis=0), 0, zero_init=True)
    np.testing.assert_allclose(model.sigma(x, anchor), np.full(50, 0.012), rtol=1e-6)


def test_without_zero_init_the_network_moves_the_forecast_off_the_anchor() -> None:
    x = np.random.default_rng(3).normal(size=(50, 10))
    anchor = np.log(np.full(50, 0.012))
    model = study.AnchoredVolatility(10, 16, x.mean(axis=0), x.std(axis=0), 0, zero_init=False)
    assert not np.allclose(model.sigma(x, anchor), 0.012, rtol=1e-3)


def test_training_is_deterministic_in_the_seed() -> None:
    rng = np.random.default_rng(4)
    x = rng.normal(size=(400, 6))
    r = rng.normal(0.0, 0.01, 400)
    block = study.Block(x, r, np.full(400, np.log(0.01)))

    def run(seed: int) -> np.ndarray:
        return study.train_anchored(
            block,
            block,
            hidden=8,
            weight_decay=0.0,
            zero_init=True,
            seed=seed,
            max_epochs=20,
            patience=5,
        ).sigma(x, block.anchor)

    np.testing.assert_array_equal(run(0), run(0))
    assert not np.array_equal(run(0), run(1))


def test_validation_chooses_the_epoch_and_never_makes_the_loss_worse_than_the_start() -> None:
    rng = np.random.default_rng(5)
    x = rng.normal(size=(500, 6))
    r = rng.normal(0.0, 0.01, 500) * np.exp(0.5 * x[:, 0])
    train = study.Block(x, r, np.full(500, np.log(r.std())))
    model = study.train_anchored(
        train, train, hidden=8, weight_decay=0.0, zero_init=True, seed=0, max_epochs=60, patience=10
    )
    start = study.AnchoredVolatility(6, 8, x.mean(axis=0), x.std(axis=0) + 1e-12, 0, zero_init=True)
    assert float(model.nll(x, train.anchor, r)) <= float(start.nll(x, train.anchor, r))


def test_blocks_use_the_same_days_whatever_the_feature_set_or_anchor(
    markets: dict[str, MarketData],
) -> None:
    data = markets["a"]
    shapes = {
        (c.anchor, c.features): study.build_blocks(data, c).train.r.shape
        for c in study.config_grid()
    }
    assert len(set(shapes.values())) == 1
    base = study.build_blocks(data, study.Config("constant", "base", 16, 0.0))
    ext = study.build_blocks(data, study.Config("gjr", "extended", 16, 0.0))
    np.testing.assert_array_equal(base.test.r, ext.test.r)
    assert base.test.x.shape[1] == 6 and ext.test.x.shape[1] == 10


def test_the_gjr_anchor_is_the_gjr_fit_on_the_training_rows_only(
    markets: dict[str, MarketData],
) -> None:
    data = markets["a"]
    fit = fit_garch_family(data.returns[data.train_mask], asymmetric=True)
    expected = 0.5 * np.log(fit.conditional_variances(data.returns))
    anchor, _ = study._anchor_log_sigma(data, "gjr")
    np.testing.assert_allclose(anchor, expected)


def _trained(name: str, loss: float) -> study.Trained:
    return study.Trained(study.Config("constant", "base", 16, 0.0), {}, loss, {})


def test_selection_takes_the_lowest_validation_loss_and_breaks_ties_toward_the_earlier() -> None:
    first, second, third = _trained("a", -1.0), _trained("b", -2.0), _trained("c", -2.0)
    assert study.select([first, second, third]) is second
    assert study.select([third, second]) is third


def test_the_fhs_quantile_is_the_training_residual_quantile_times_the_test_sigma() -> None:
    train_r = np.linspace(-0.04, 0.04, 1001)
    thresholds = study.fhs_thresholds(train_r, np.full(1001, 0.01), np.array([0.01, 0.02]))
    expected = float(np.quantile(train_r / 0.01, 0.01))
    np.testing.assert_allclose(thresholds[0.99], [expected * 0.01, expected * 0.02])


def test_a_small_end_to_end_run_reports_every_question_and_never_selects_on_the_test_window(
    markets: dict[str, MarketData], tmp_path: Path
) -> None:
    paths = {name: Path(tmp_path / f"{name}.csv") for name in markets}
    _write_market(paths["a"], date(1985, 1, 1), date(2012, 6, 30), 1)
    _write_market(paths["b"], date(1990, 6, 1), date(2012, 3, 31), 2)
    grid = [study.Config("constant", "base", 8, 0.0), study.Config("gjr", "extended", 8, 0.0)]
    report = study.run_study(
        paths, seeds=[0], max_epochs=15, patience=5, block_resamples=50, grid=grid
    )
    assert set(report["hypotheses"]) == {"V-A", "V-B", "V-C"}
    ranked = [g["pooled_validation_qlike"] for g in report["grid"]]
    assert ranked == sorted(ranked)
    best = report["grid"][0]["config"]
    chosen = report["config"]["selected"]
    assert best == study.Config(**chosen).name
    for market in report["markets"].values():
        assert set(market["comparisons"]) == {"V-A", "V-B"}
        for row in market["comparisons"].values():
            assert row["preregistered_verdict"] in {"SUPPORTED", "CONTRADICTED", "INCONCLUSIVE"}


@pytest.mark.skipif(not COMMITTED.exists(), reason="committed study output is absent")
def test_the_committed_report_is_internally_consistent() -> None:
    report = json.loads(COMMITTED.read_text())
    ranked = [g["pooled_validation_qlike"] for g in report["grid"]]
    assert len(ranked) == 16 and ranked == sorted(ranked)
    assert report["grid"][0]["config"] == study.Config(**report["config"]["selected"]).name
    for market in report["markets"].values():
        for label in ("V-A", "V-B"):
            row = market["comparisons"][label]
            assert row["ci_low"] <= row["qlike_difference_first_minus_second"] <= row["ci_high"]
