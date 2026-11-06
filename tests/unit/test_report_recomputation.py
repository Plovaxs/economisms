from datetime import date

import numpy as np
import pytest

from prometheus.service.report_recomputation import (
    EXPECTED_SHORTFALL_FORMULA,
    VALUE_AT_RISK_FORMULA,
    MetricFormula,
    recompute_risk_report_from_raw_losses,
)
from prometheus.service.reports import build_risk_report
from prometheus.titan.risk_metrics import historical_expected_shortfall, historical_var
from prometheus.volterra.market import MarketSnapshot


def _snapshot() -> MarketSnapshot:
    return MarketSnapshot(as_of=date(2026, 1, 1), spot=100.0, risk_free_rate=0.03, volatility=0.2)


def _raw_losses() -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.normal(0.0, 1.0, 500)


@pytest.mark.parametrize("formula", [VALUE_AT_RISK_FORMULA, EXPECTED_SHORTFALL_FORMULA])
def test_every_formula_documents_all_four_fields(formula: MetricFormula) -> None:
    """AUD-09's own wording: formulas, units AND conventions, each
    actually present, not merely a formula with the rest left blank."""
    assert formula.metric_name
    assert formula.formula
    assert formula.units
    assert formula.sign_convention


def test_value_at_risk_formula_matches_the_metric_it_documents() -> None:
    assert VALUE_AT_RISK_FORMULA.metric_name == "value_at_risk"


def test_expected_shortfall_formula_matches_the_metric_it_documents() -> None:
    assert EXPECTED_SHORTFALL_FORMULA.metric_name == "expected_shortfall"


def test_a_report_built_honestly_from_raw_losses_is_reproducible() -> None:
    """AUD-09's own acceptance criterion: "each report can be
    recomputed from raw facts" -- confirmed here against a real raw
    loss array passed through the SAME documented formulas, not a
    toy/fabricated pair of numbers."""
    raw_losses = _raw_losses()
    alpha = 0.95
    report = build_risk_report(
        _snapshot(), "historical_var@1.0", measure="P", alpha=alpha,
        value_at_risk=historical_var(raw_losses, alpha), value_at_risk_tolerance=1e-9,
        expected_shortfall=historical_expected_shortfall(raw_losses, alpha),
        expected_shortfall_tolerance=1e-9,
    )
    assert recompute_risk_report_from_raw_losses(report, raw_losses) == []


def test_a_report_with_a_tampered_var_is_caught_against_the_raw_facts() -> None:
    """The discriminating half: a report claiming a VaR that does not
    actually follow from the raw losses it is supposedly built from
    must be flagged, with the exact mismatch, not silently accepted."""
    raw_losses = _raw_losses()
    alpha = 0.95
    true_var = historical_var(raw_losses, alpha)
    true_es = historical_expected_shortfall(raw_losses, alpha)
    tampered = build_risk_report(
        _snapshot(), "historical_var@1.0", measure="P", alpha=alpha,
        value_at_risk=true_var + 5.0, value_at_risk_tolerance=1e-9,
        expected_shortfall=true_es, expected_shortfall_tolerance=1e-9,
    )
    violations = recompute_risk_report_from_raw_losses(tampered, raw_losses)
    assert len(violations) == 1
    assert violations[0].field == "value_at_risk"
    assert violations[0].absolute_error == pytest.approx(5.0)


def test_a_report_with_a_tampered_es_is_caught_against_the_raw_facts() -> None:
    raw_losses = _raw_losses()
    alpha = 0.95
    true_var = historical_var(raw_losses, alpha)
    true_es = historical_expected_shortfall(raw_losses, alpha)
    tampered = build_risk_report(
        _snapshot(), "historical_var@1.0", measure="P", alpha=alpha,
        value_at_risk=true_var, value_at_risk_tolerance=1e-9,
        expected_shortfall=true_es - 3.0, expected_shortfall_tolerance=1e-9,
    )
    violations = recompute_risk_report_from_raw_losses(tampered, raw_losses)
    assert len(violations) == 1
    assert violations[0].field == "expected_shortfall"


def test_recomputation_is_specific_to_the_reports_own_alpha() -> None:
    """A report at a DIFFERENT alpha than the raw facts would naively
    suggest must still be checked at ITS OWN alpha, not some fixed
    default -- confirming `report.alpha` genuinely drives the
    recomputation, not a hardcoded constant."""
    raw_losses = _raw_losses()
    alpha = 0.99
    report = build_risk_report(
        _snapshot(), "historical_var@1.0", measure="P", alpha=alpha,
        value_at_risk=historical_var(raw_losses, alpha), value_at_risk_tolerance=1e-9,
        expected_shortfall=historical_expected_shortfall(raw_losses, alpha),
        expected_shortfall_tolerance=1e-9,
    )
    assert recompute_risk_report_from_raw_losses(report, raw_losses) == []
