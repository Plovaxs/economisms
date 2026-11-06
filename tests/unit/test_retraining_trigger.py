from datetime import date

import numpy as np
import pytest
from scipy import stats

from prometheus.evidence.retraining_trigger import (
    RetrainingThreshold,
    evaluate_retraining_trigger,
)
from prometheus.titan.risk_metrics import es_unconditional_calibration_test


def _real_es_calibration_p_value(es_scale: float) -> float:
    """A genuine calibration-test p-value, not a fabricated number:
    reuses RISK-09's own `es_unconditional_calibration_test` against a
    real loss sample, with the ES forecast scaled by `es_scale` away
    from its true value to control how miscalibrated it is."""
    rng = np.random.default_rng(0)
    losses = rng.normal(0, 1, 2000)
    alpha = 0.95
    true_var = float(stats.norm.ppf(alpha))
    true_es = float(stats.norm.pdf(true_var) / (1 - alpha))
    result = es_unconditional_calibration_test(
        losses, true_var, true_es * es_scale, alpha, np.random.default_rng(1)
    )
    return result.p_value


def test_threshold_rejects_a_p_value_floor_outside_zero_one() -> None:
    with pytest.raises(ValueError, match="min_acceptable_p_value"):
        RetrainingThreshold("es_calibration", 1.5, date(2026, 1, 1))


def test_threshold_rejects_an_empty_metric_name() -> None:
    with pytest.raises(ValueError, match="metric_name"):
        RetrainingThreshold("", 0.05, date(2026, 1, 1))


def test_a_well_calibrated_real_forecast_does_not_escalate() -> None:
    """MLO-13's own framing: a model whose Expected Shortfall is
    genuinely well-calibrated (confirmed via a REAL calibration test
    p-value, not an assumed one) must not trigger retraining."""
    threshold = RetrainingThreshold("es_calibration", 0.05, date(2026, 1, 1))
    p_value = _real_es_calibration_p_value(es_scale=1.0)  # the true ES, correctly calibrated
    assert p_value > 0.05  # sanity: this really is the "well calibrated" case
    escalation = evaluate_retraining_trigger(threshold, p_value, date(2026, 2, 1))
    assert escalation.escalate is False


def test_a_genuinely_miscalibrated_real_forecast_escalates() -> None:
    """The discriminating half: a model whose ES forecast genuinely
    understates tail severity (confirmed via the same real calibration
    test) must trigger retraining."""
    threshold = RetrainingThreshold("es_calibration", 0.05, date(2026, 1, 1))
    p_value = _real_es_calibration_p_value(es_scale=0.3)  # understated tail severity
    assert p_value < 0.05  # sanity: this really is the "miscalibrated" case
    escalation = evaluate_retraining_trigger(threshold, p_value, date(2026, 2, 1))
    assert escalation.escalate is True


def test_a_threshold_cannot_be_evaluated_against_a_backdated_observation() -> None:
    """"Thresholds ... recorded before deployment" is enforced, not
    merely named: an observation dated before the threshold's own
    recorded date would mean the threshold was set AFTER already
    knowing the outcome -- rejected."""
    threshold = RetrainingThreshold("es_calibration", 0.05, date(2026, 6, 1))
    with pytest.raises(ValueError, match="recorded before deployment"):
        evaluate_retraining_trigger(threshold, 0.01, date(2026, 1, 1))


def test_an_observation_on_the_same_day_as_the_threshold_is_allowed() -> None:
    threshold = RetrainingThreshold("es_calibration", 0.05, date(2026, 1, 1))
    escalation = evaluate_retraining_trigger(threshold, 0.5, date(2026, 1, 1))
    assert escalation.escalate is False


def test_threshold_is_immutable() -> None:
    import dataclasses

    threshold = RetrainingThreshold("es_calibration", 0.05, date(2026, 1, 1))
    with pytest.raises(dataclasses.FrozenInstanceError):
        threshold.min_acceptable_p_value = 0.99  # type: ignore[misc]
