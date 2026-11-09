from datetime import date

import numpy as np
import pytest
from scipy import stats

from prometheus.evidence.model_monitoring import (
    InvestigationStep,
    MonitoringSignal,
    build_investigation_playbook,
    build_model_monitoring_report,
    calibration_signal,
    drift_signal,
    tail_breach_signal,
)
from prometheus.evidence.retraining_trigger import RetrainingThreshold, evaluate_retraining_trigger
from prometheus.experiments.bootstrap import paired_bootstrap_difference
from prometheus.hedging.baseline import apply_no_trade_band, black_scholes_delta_hedge_ratios
from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.titan.risk_metrics import (
    es_unconditional_calibration_test,
    var_exception_coverage_test,
)
from prometheus.volterra.black_scholes import black_scholes_price
from prometheus.volterra.instruments import EuropeanOption
from prometheus.volterra.market import MarketSnapshot


def test_investigation_step_rejects_an_empty_action() -> None:
    with pytest.raises(ValueError, match="action"):
        InvestigationStep(signal="drift", action="", owner="team")


def test_investigation_step_rejects_an_empty_owner() -> None:
    with pytest.raises(ValueError, match="owner"):
        InvestigationStep(signal="drift", action="investigate", owner="")


def test_tail_breach_signal_rejects_an_out_of_range_p_value() -> None:
    coverage = var_exception_coverage_test(np.array([0.1, 0.2, 0.3]), 0.5, 0.95)
    with pytest.raises(ValueError, match="min_p_value"):
        tail_breach_signal(coverage, min_p_value=1.5)


def test_a_real_well_calibrated_var_does_not_trigger_a_tail_breach() -> None:
    rng = np.random.default_rng(0)
    losses = rng.normal(0, 1, 2000)
    alpha = 0.95
    true_var = float(stats.norm.ppf(alpha))
    coverage = var_exception_coverage_test(losses, true_var, alpha)
    signal = tail_breach_signal(coverage, min_p_value=0.01)
    assert signal.triggered is False
    assert signal.name == "tail_breach"


def test_a_real_miscalibrated_var_triggers_a_tail_breach() -> None:
    """The discriminating half: a VaR threshold set far too low (so far
    more real losses exceed it than the model's own confidence level
    implies) must trigger the signal."""
    rng = np.random.default_rng(0)
    losses = rng.normal(0, 1, 2000)
    alpha = 0.95
    true_var = float(stats.norm.ppf(alpha))
    bad_var = true_var * 0.3
    coverage = var_exception_coverage_test(losses, bad_var, alpha)
    signal = tail_breach_signal(coverage, min_p_value=0.01)
    assert signal.triggered is True


def _real_es_calibration_p_value(es_scale: float) -> float:
    """Reuses RISK-09's own `es_unconditional_calibration_test` against
    a real loss sample, scaling the ES forecast away from its true
    value to control how miscalibrated it is -- the exact pattern
    `test_retraining_trigger.py` already established for MLO-13."""
    rng = np.random.default_rng(0)
    losses = rng.normal(0, 1, 2000)
    alpha = 0.95
    true_var = float(stats.norm.ppf(alpha))
    true_es = float(stats.norm.pdf(true_var) / (1 - alpha))
    result = es_unconditional_calibration_test(
        losses, true_var, true_es * es_scale, alpha, np.random.default_rng(1)
    )
    return result.p_value


def test_a_real_well_calibrated_es_does_not_trigger_the_calibration_signal() -> None:
    threshold = RetrainingThreshold("es_calibration", 0.05, date(2026, 1, 1))
    p_value = _real_es_calibration_p_value(es_scale=1.0)
    assert p_value > 0.05  # sanity
    escalation = evaluate_retraining_trigger(threshold, p_value, date(2026, 2, 1))
    signal = calibration_signal(escalation)
    assert signal.triggered is False
    assert signal.name == "calibration"


def test_a_real_miscalibrated_es_triggers_the_calibration_signal() -> None:
    threshold = RetrainingThreshold("es_calibration", 0.05, date(2026, 1, 1))
    p_value = _real_es_calibration_p_value(es_scale=3.0)
    assert p_value < 0.05  # sanity
    escalation = evaluate_retraining_trigger(threshold, p_value, date(2026, 2, 1))
    signal = calibration_signal(escalation)
    assert signal.triggered is True


def _hedge_losses(band_width: float, cost_rate: float) -> np.ndarray:
    """A real delta-hedge strategy's terminal losses on a real
    simulated path set, with a no-trade band applied -- the same
    matched-data pattern `test_champion_challenger.py` already uses."""
    rng = np.random.default_rng(0)
    s0, mu, sigma, maturity, n_steps, n_paths = 100.0, 0.03, 0.2, 1.0, 50, 2000
    dt = maturity / n_steps
    paths = simulate_gbm_paths(s0, mu, sigma, maturity, n_steps, n_paths, rng)
    strike = 100.0
    market = MarketSnapshot(as_of=date(2026, 1, 1), spot=s0, risk_free_rate=mu, volatility=sigma)
    option = EuropeanOption(strike=strike, maturity=maturity, option_type="call")
    premium = black_scholes_price(market, option)
    ratios = black_scholes_delta_hedge_ratios(paths, dt, strike, maturity, mu, sigma, "call")
    banded = apply_no_trade_band(ratios, band_width=band_width)
    result = simulate_self_financing_hedge(
        paths, dt, strike, "call", mu, cost_rate, premium, banded
    )
    return result.terminal_loss


def test_an_unchanged_hedge_configuration_does_not_trigger_the_drift_signal() -> None:
    baseline_losses = _hedge_losses(band_width=0.0, cost_rate=0.0)
    current_losses = _hedge_losses(band_width=0.0, cost_rate=0.0)
    comparison = paired_bootstrap_difference(
        lambda x: float(np.mean(x)), current_losses, baseline_losses, np.random.default_rng(3)
    )
    signal = drift_signal(comparison)
    assert signal.triggered is False
    assert signal.name == "drift"


def test_a_real_configuration_change_triggers_the_drift_signal() -> None:
    """The discriminating half: a real band-width/cost-rate change to
    the SAME delta-hedge strategy, evaluated on the SAME simulated
    paths, must produce a statistically significant, detected drift."""
    baseline_losses = _hedge_losses(band_width=0.0, cost_rate=0.0)
    current_losses = _hedge_losses(band_width=0.1, cost_rate=0.001)
    comparison = paired_bootstrap_difference(
        lambda x: float(np.mean(x)), current_losses, baseline_losses, np.random.default_rng(2)
    )
    signal = drift_signal(comparison)
    assert signal.triggered is True


def test_playbook_only_includes_steps_for_triggered_signals() -> None:
    signals = [
        MonitoringSignal(name="tail_breach", triggered=False, detail="ok"),
        MonitoringSignal(name="calibration", triggered=True, detail="bad"),
        MonitoringSignal(name="drift", triggered=False, detail="ok"),
    ]
    playbook = build_investigation_playbook(signals, owner="risk-team")
    assert len(playbook) == 1
    assert playbook[0].signal == "calibration"
    assert playbook[0].owner == "risk-team"


def test_playbook_is_empty_when_nothing_triggered() -> None:
    signals = [MonitoringSignal(name="tail_breach", triggered=False, detail="ok")]
    assert build_investigation_playbook(signals, owner="team") == ()


def test_build_investigation_playbook_rejects_an_empty_owner() -> None:
    with pytest.raises(ValueError, match="owner"):
        build_investigation_playbook([], owner="")


def test_build_model_monitoring_report_composes_signals_and_playbook() -> None:
    signals = [
        MonitoringSignal(name="tail_breach", triggered=True, detail="bad"),
        MonitoringSignal(name="drift", triggered=False, detail="ok"),
    ]
    report = build_model_monitoring_report(signals, owner="risk-team")
    assert report.any_triggered is True
    assert len(report.playbook) == 1
    assert report.playbook[0].signal == "tail_breach"


def test_report_any_triggered_is_false_when_nothing_fires() -> None:
    signals = [MonitoringSignal(name="drift", triggered=False, detail="ok")]
    report = build_model_monitoring_report(signals, owner="team")
    assert report.any_triggered is False
