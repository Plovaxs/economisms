"""Recomputing a risk report's reported values from raw facts (AUD-09:
"document reporting metric formulas, units and conventions"; acceptance
criterion: "each report can be recomputed from raw facts").

The formulas themselves are not reinvented or restated as logic here --
`titan.risk_metrics.historical_var`/`historical_expected_shortfall`
already document their exact mathematical definition, interpolation/
estimator choice and sign convention in their own docstrings (RISK-02/
RISK-04), and are called here unchanged. What AUD-09 adds is twofold:
a structured, auditor-facing `MetricFormula` restating each metric's
formula/units/convention as inspectable DATA rather than prose a
reader has to go find, and `recompute_risk_report_from_raw_losses`,
which closes the loop end to end -- given the RAW loss array a
`service.reports.RiskReportResponse` was supposedly built from, it
recomputes VaR/ES independently via those same documented functions
and reports any mismatch through `service.reports.check_risk_tolerance`
(reused, not reimplemented): an empty result means the report is
genuinely reproducible from its own raw facts, not merely claimed to
be.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from prometheus.service.reports import RiskReportResponse, ToleranceViolation, check_risk_tolerance
from prometheus.titan.risk_metrics import historical_expected_shortfall, historical_var


@dataclass(frozen=True, slots=True)
class MetricFormula:
    metric_name: str
    formula: str
    units: str
    sign_convention: str


VALUE_AT_RISK_FORMULA = MetricFormula(
    metric_name="value_at_risk",
    formula=(
        "VaR_alpha(L) = empirical alpha-quantile of the loss sample L "
        "(numpy.quantile, method='linear')"
    ),
    units="same currency/units as the raw loss series L",
    sign_convention="a loss is positive when money is lost (titan.risk_metrics convention)",
)

EXPECTED_SHORTFALL_FORMULA = MetricFormula(
    metric_name="expected_shortfall",
    formula=(
        "ES_alpha(L) = [sum_{i=k+1}^{n} L_(i) + (k - alpha*n) * L_(k)] / (n * (1 - alpha)), "
        "k = ceil(alpha * n), on sorted order statistics L_(1) <= ... <= L_(n) "
        "(tie/atom-safe quantile-integral estimator)"
    ),
    units="same currency/units as the raw loss series L",
    sign_convention="a loss is positive when money is lost (titan.risk_metrics convention)",
)


def recompute_risk_report_from_raw_losses(
    report: RiskReportResponse, raw_losses: np.ndarray
) -> list[ToleranceViolation]:
    """Recomputes VaR/ES from `raw_losses` at `report.alpha`, via the
    exact functions `VALUE_AT_RISK_FORMULA`/`EXPECTED_SHORTFALL_FORMULA`
    document, and returns every `ToleranceViolation` against the
    report's own declared budget -- an empty list means the report was
    genuinely reproduced from these raw facts."""
    reference_var = historical_var(raw_losses, report.alpha)
    reference_es = historical_expected_shortfall(raw_losses, report.alpha)
    return check_risk_tolerance(report, reference_var, reference_es)
