import dataclasses
from datetime import date

import pytest

from prometheus.service.reports import (
    PricingReportResponse,
    RiskReportResponse,
    ToleranceViolation,
    build_pricing_report,
    build_risk_report,
    check_pricing_tolerance,
    check_risk_tolerance,
    market_snapshot_id,
)
from prometheus.volterra.market import MarketSnapshot


def _snapshot(spot: float = 100.0) -> MarketSnapshot:
    return MarketSnapshot(
        as_of=date(2026, 1, 1), spot=spot, risk_free_rate=0.03, volatility=0.2
    )


def _pricing_report(**overrides: object) -> PricingReportResponse:
    defaults: dict = dict(
        snapshot=_snapshot(), model_version="black_scholes@1.0", measure="Q",
        price=10.45, price_tolerance=0.01,
    )
    defaults.update(overrides)
    return build_pricing_report(**defaults)  # type: ignore[arg-type]


def _risk_report(**overrides: object) -> RiskReportResponse:
    defaults: dict = dict(
        snapshot=_snapshot(), model_version="historical_var@1.0", measure="P", alpha=0.95,
        value_at_risk=2.33, value_at_risk_tolerance=0.05,
        expected_shortfall=2.90, expected_shortfall_tolerance=0.05,
    )
    defaults.update(overrides)
    return build_risk_report(**defaults)  # type: ignore[arg-type]


def test_market_snapshot_id_is_deterministic_for_identical_snapshots() -> None:
    """Two separately-constructed but field-identical snapshots must
    produce the IDENTICAL id -- it is derived from content, not object
    identity or construction order."""
    s1 = _snapshot()
    s2 = _snapshot()
    assert s1 is not s2
    assert market_snapshot_id(s1) == market_snapshot_id(s2)


def test_market_snapshot_id_differs_for_different_snapshots() -> None:
    """The discriminating half: changing even one field must change the
    id -- otherwise it would be a useless constant, not a real
    content-derived reference."""
    assert market_snapshot_id(_snapshot(spot=100.0)) != market_snapshot_id(_snapshot(spot=101.0))


def test_pricing_report_carries_the_correct_snapshot_id_and_model_version() -> None:
    snapshot = _snapshot()
    report = _pricing_report(snapshot=snapshot)
    assert report.market_snapshot_id == market_snapshot_id(snapshot)
    assert report.model_version == "black_scholes@1.0"
    assert report.price == 10.45
    assert report.price_tolerance == 0.01


def test_pricing_report_with_different_snapshots_carries_different_ids() -> None:
    report_a = _pricing_report(snapshot=_snapshot(spot=100.0), price=10.45)
    report_b = _pricing_report(snapshot=_snapshot(spot=105.0), price=12.10)
    assert report_a.market_snapshot_id != report_b.market_snapshot_id


def test_pricing_report_is_immutable() -> None:
    """API-05's own "immutable" wording, confirmed by test rather than
    assumed from the frozen=True decorator: attempting to mutate any
    field after construction must raise, not silently succeed."""
    report = _pricing_report()
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.price = 999.0  # type: ignore[misc]


def test_risk_report_carries_the_correct_snapshot_id_and_model_version() -> None:
    snapshot = _snapshot()
    report = _risk_report(snapshot=snapshot)
    assert report.market_snapshot_id == market_snapshot_id(snapshot)
    assert report.model_version == "historical_var@1.0"
    assert report.alpha == 0.95
    assert report.value_at_risk == 2.33
    assert report.value_at_risk_tolerance == 0.05
    assert report.expected_shortfall == 2.90
    assert report.expected_shortfall_tolerance == 0.05


def test_risk_report_is_immutable() -> None:
    report = _risk_report()
    with pytest.raises(dataclasses.FrozenInstanceError):
        report.value_at_risk = 0.0  # type: ignore[misc]


def test_pricing_report_optional_greeks_default_to_none() -> None:
    assert _pricing_report().greeks is None


def test_pricing_report_carries_greeks_when_supplied() -> None:
    greeks = {"delta": 0.6, "gamma": 0.02}
    assert _pricing_report(greeks=greeks).greeks == greeks


@pytest.mark.parametrize("bad_tolerance", [0.0, -0.01])
def test_pricing_report_rejects_a_non_positive_tolerance(bad_tolerance: float) -> None:
    with pytest.raises(ValueError, match="price_tolerance"):
        _pricing_report(price_tolerance=bad_tolerance)


def test_risk_report_rejects_a_non_positive_var_tolerance() -> None:
    with pytest.raises(ValueError, match="value_at_risk_tolerance"):
        _risk_report(value_at_risk_tolerance=0.0)


def test_risk_report_rejects_a_non_positive_es_tolerance() -> None:
    with pytest.raises(ValueError, match="expected_shortfall_tolerance"):
        _risk_report(expected_shortfall_tolerance=-1.0)


def test_check_pricing_tolerance_passes_within_budget() -> None:
    report = _pricing_report()
    assert check_pricing_tolerance(report, reference_price=10.455) is None


def test_check_pricing_tolerance_flags_a_violation_outside_budget() -> None:
    """The discriminating half: a reference price just past the
    declared budget must be reported, with the exact error and budget
    that were compared, not merely a boolean."""
    report = _pricing_report()
    violation = check_pricing_tolerance(report, reference_price=10.50)
    assert violation == ToleranceViolation(
        field="price", reported=10.45, reference=10.50,
        absolute_error=pytest.approx(0.05), tolerance=0.01,
    )


def test_check_pricing_tolerance_boundary_is_inclusive() -> None:
    """Exactly AT the budget is not a violation -- only strictly past it
    is, so a reference that matches the declared budget exactly passes."""
    report = _pricing_report(price=10.00, price_tolerance=0.5)
    assert check_pricing_tolerance(report, reference_price=10.50) is None


def test_check_risk_tolerance_passes_when_both_fields_are_within_budget() -> None:
    report = _risk_report(value_at_risk_tolerance=0.1, expected_shortfall_tolerance=0.1)
    violations = check_risk_tolerance(
        report, reference_value_at_risk=2.35, reference_expected_shortfall=2.92
    )
    assert violations == []


def test_check_risk_tolerance_flags_only_the_field_that_actually_violates() -> None:
    """VaR and ES carry SEPARATE budgets: a reference that breaks only
    one of the two fields' budgets must report exactly that one field,
    not both and not neither."""
    report = _risk_report(value_at_risk_tolerance=0.1, expected_shortfall_tolerance=0.1)
    violations = check_risk_tolerance(
        report, reference_value_at_risk=2.35, reference_expected_shortfall=3.50
    )
    assert len(violations) == 1
    assert violations[0].field == "expected_shortfall"


def test_check_risk_tolerance_can_flag_both_fields_at_once() -> None:
    report = _risk_report(value_at_risk_tolerance=0.01, expected_shortfall_tolerance=0.01)
    violations = check_risk_tolerance(
        report, reference_value_at_risk=3.00, reference_expected_shortfall=3.50
    )
    assert {v.field for v in violations} == {"value_at_risk", "expected_shortfall"}


def test_tolerance_violation_str_mentions_field_error_and_tolerance() -> None:
    violation = ToleranceViolation(
        field="price", reported=10.45, reference=10.60, absolute_error=0.15, tolerance=0.01
    )
    text = str(violation)
    assert "price" in text
    assert "0.15" in text
    assert "0.01" in text


def test_pricing_report_carries_an_explicit_q_measure() -> None:
    """AUD-04's own acceptance criterion: an auditor must be able to
    differentiate P from Q by reading the report itself, not by
    inferring it from the response's Python class name."""
    assert _pricing_report(measure="Q").measure == "Q"


def test_risk_report_carries_an_explicit_p_measure() -> None:
    assert _risk_report(measure="P").measure == "P"


def test_risk_report_measure_can_be_overridden_to_q() -> None:
    """The discriminating half: VaR/ES are not unconditionally P-measure
    in general (a risk-neutral VaR of a derivatives book is legitimate),
    so the field must actually be settable to "Q" on a risk report, not
    silently forced to "P"."""
    assert _risk_report(measure="Q").measure == "Q"


def test_pricing_report_rejects_an_unknown_measure() -> None:
    with pytest.raises(ValueError, match="measure"):
        _pricing_report(measure="X")


def test_risk_report_rejects_an_unknown_measure() -> None:
    with pytest.raises(ValueError, match="measure"):
        _risk_report(measure="X")


def test_build_pricing_report_requires_measure_to_be_passed_explicitly() -> None:
    """No default: a silently-omitted measure would not be a deliberate
    declaration by the caller computing the value (this module's own
    docstring states the same reasoning already applied to the
    tolerance fields)."""
    with pytest.raises(TypeError):
        build_pricing_report(_snapshot(), "black_scholes@1.0", price=10.45, price_tolerance=0.01)  # type: ignore[call-arg]


def test_build_risk_report_requires_measure_to_be_passed_explicitly() -> None:
    with pytest.raises(TypeError):
        build_risk_report(  # type: ignore[call-arg]
            _snapshot(), "historical_var@1.0", alpha=0.95,
            value_at_risk=2.33, value_at_risk_tolerance=0.05,
            expected_shortfall=2.90, expected_shortfall_tolerance=0.05,
        )
