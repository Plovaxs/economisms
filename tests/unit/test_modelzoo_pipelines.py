"""Model zoo pipelines: a price surrogate feeding a hedge feeding a risk metric, and a simulated
banking
system feeding an amplitude-estimation risk estimate."""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest
import torch

from prometheus.modelzoo import pipelines as pl
from prometheus.modelzoo import quantum as qm
from prometheus.orchestration import modelzoo_pipeline_study as study
from prometheus.titan.risk_metrics import historical_expected_shortfall
from prometheus.volterra.black_scholes import black_scholes_greeks, black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def test_the_time_dependent_closed_form_matches_the_projects_pricer_and_greeks() -> None:
    market = MarketSnapshot(
        as_of=date(2024, 1, 1), spot=104.0, risk_free_rate=pl.RATE, volatility=0.27
    )
    option = EuropeanOption(strike=98.0, maturity=0.4, option_type="call")
    spot = np.array([104.0])
    assert float(pl.bs_call_tau(spot, 98.0, 0.27, 0.4)[0]) == pytest.approx(
        black_scholes_price(market, option), rel=1e-10
    )
    assert float(pl.bs_delta_tau(spot, 98.0, 0.27, 0.4)[0]) == pytest.approx(
        black_scholes_greeks(market, option).delta, rel=1e-10
    )


def test_surface_data_is_scaled_and_the_surrogate_takes_any_grid() -> None:
    data = pl.make_surface_data(20, 32, seed=1)
    assert data.payoff.shape == (20, 32) and np.abs(data.payoff).max() == pytest.approx(1.0)
    assert (data.scalars[:, 1] >= pl.TAU_LOW).all() and (data.scalars[:, 1] <= pl.TAU_HIGH).all()
    model = pl.TimeConditionedFNO(width=8, modes=4, layers=2)
    for size in (32, 100):
        out = model(torch.zeros(3, size), torch.zeros(3, 2))
        assert out.shape == (3, size)
    delta = pl.surrogate_delta(model, np.array([90.0, 100.0, 110.0]), 100.0, 0.2, 0.5)
    assert delta.shape == (3,) and ((delta >= 0) & (delta <= 1)).all()


def test_training_the_surrogate_makes_its_price_curve_closer_to_the_truth() -> None:
    data = pl.make_surface_data(400, 32, seed=2)
    test = pl.make_surface_data(50, 32, seed=3)

    def error(model: pl.TimeConditionedFNO) -> float:
        with torch.no_grad():
            pred = model(
                torch.as_tensor(test.payoff, dtype=torch.float32),
                torch.as_tensor(test.scalars, dtype=torch.float32),
            ).numpy()
        return float(
            np.mean(np.linalg.norm(pred - test.price, axis=1) / np.linalg.norm(test.price, axis=1))
        )

    torch.manual_seed(1)
    before = error(pl.TimeConditionedFNO())
    after = error(pl.train_surface(data, epochs=15, seed=1))
    assert after < 0.5 * before


def test_the_exact_delta_hedge_removes_most_of_the_risk_and_finer_hedging_removes_more() -> None:
    model = pl.TimeConditionedFNO(
        width=8, modes=4, layers=2
    )  # untrained: only the exact column is used
    coarse = pl.run_hedge(model, seed=1, paths=1500, steps=13)
    fine = pl.run_hedge(model, seed=1, paths=1500, steps=104)
    assert (
        np.std(fine.errors["exact"])
        < np.std(coarse.errors["exact"])
        < 0.5 * np.std(coarse.errors["unhedged"])
    )
    risk = pl.hedge_risk(fine.errors["exact"])
    assert risk["expected_shortfall"] >= risk["var"] > -1.0 and risk["std"] > 0.0


def test_the_bank_loss_pipeline_agrees_with_the_direct_expected_shortfall() -> None:
    samples = pl.bank_loss_samples((1, 2, 3, 4))
    assert samples.shape == (72,) and (samples >= 0).all() or samples.min() > -5
    info = pl.loss_amplitude(samples, 0.95)
    direct = float(historical_expected_shortfall(samples, 0.95))
    # the binned distribution's exact amplitude gives the Expected Shortfall to within the bin width
    assert info.expected_shortfall(info.distribution.amplitude) == pytest.approx(direct, rel=0.03)
    rng = np.random.default_rng(1)
    estimate, calls = pl.quantum_expected_shortfall(info, qm.mlae_schedule(5), 400, rng)
    assert estimate == pytest.approx(info.expected_shortfall(info.distribution.amplitude), rel=0.02)
    assert calls == 400 * sum(2 * k + 1 for k in qm.mlae_schedule(5))
    classical = pl.monte_carlo_expected_shortfall(info, 200_000, rng)
    assert classical == pytest.approx(
        info.expected_shortfall(info.distribution.amplitude), rel=0.05
    )


def test_the_study_states_every_hypothesis_and_discloses_what_was_seen() -> None:
    doc = study.__doc__ or ""
    for label in ("Z-I1", "Z-I2", "Z-I3", "Z-I4", "Z-I5", "Z-I6"):
        assert label in doc
    assert "What I had looked at before writing this" in doc


def test_tiny_runs_of_both_pipelines_return_their_verdicts() -> None:
    h = study.hedge_study((1, 2), samples=60, epochs=1, paths=100)
    assert {"Z-I1", "Z-I2", "Z-I3"} <= set(h)
    b = study.bank_risk_study((1, 2, 3), repetitions=5)
    assert {"Z-I4", "Z-I5", "Z-I6"} <= set(b)
