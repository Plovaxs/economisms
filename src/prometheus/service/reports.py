"""Immutable pricing and risk report responses (API-05: "responses
reference market snapshots and model versions"; VAL-12: "set a
numerical accuracy budget per API output"; AUD-04: "capture pricing
measure and market snapshot for reports").

Every response below is a frozen dataclass (`FrozenInstanceError` on any
attempted mutation, confirmed by test rather than assumed from the
decorator) carrying `market_snapshot_id` and `model_version` -- the two
fields API-05 explicitly asks for. `market_snapshot_id` is not an
arbitrary caller-chosen label: it is derived deterministically from the
`MarketSnapshot`'s own fields via `compute_result_hash` (the same
canonical-JSON SHA256 hash `evidence.integrity`'s artifact seals already
use), so two reports built from bit-identical snapshots always carry the
identical id, and two reports built from different snapshots always
carry different ids -- a verifiable property, not a convention taken on
faith.

`build_pricing_report`/`build_risk_report` are the only intended way to
construct these responses: they compute `market_snapshot_id` from the
snapshot themselves, so a caller can never accidentally pass a response
with a snapshot id that does not actually match the snapshot it claims
to describe.

VAL-12's own acceptance criterion is "tolerance fields present and
tested for violations", so each numerical output carries its own
declared accuracy budget as a REQUIRED field (`price_tolerance`,
`value_at_risk_tolerance`, `expected_shortfall_tolerance`) -- there is
no default, because a silently-defaulted budget would not be a
deliberate declaration by the caller computing the value, and a
non-positive tolerance is rejected since it could never be satisfied by
any computed value. `check_pricing_tolerance`/`check_risk_tolerance`
compare a report's reported value(s) against an independently obtained
reference (a higher-precision recomputation, a second model, or a
Monte Carlo confidence bound) and report any field whose absolute error
exceeds its own declared budget as a `ToleranceViolation`.

AUD-04's own acceptance criterion is "auditor can differentiate P risk
model from Q pricer". `volterra.market.MarketSnapshot` already carries
a `measure` field, but it is structurally PINNED to `"Q"` -- every
VOLTERRA pricing input is risk-neutral by construction (see that
module's own docstring, SDE-09), so the snapshot alone can never
distinguish a P-measure risk computation from a Q-measure pricing one:
both `PricingReportResponse` and `RiskReportResponse` were, before this
addition, built from the exact same always-"Q" snapshot type, with
nothing on the RESPONSE itself recording which measure the reported
NUMBER (price, or VaR/ES) was actually computed under. `measure` is
therefore added here as its own REQUIRED field (no default, for the
same reason the tolerance fields have none: a silently-defaulted
measure would not be a deliberate declaration by whichever code
computed the value) directly on each response -- an auditor reading a
serialized report can now tell P from Q by that field alone, without
inferring it from the Python class name or assuming VaR/ES are always
P-measure (they need not be: a risk-neutral VaR of a derivatives book
is a legitimate, if less common, Q-measure risk computation).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Literal

from prometheus.experiments.manifest import compute_result_hash
from prometheus.volterra.market import MarketSnapshot

Measure = Literal["P", "Q"]
_MEASURES: frozenset[str] = frozenset({"P", "Q"})


def market_snapshot_id(snapshot: MarketSnapshot) -> str:
    return compute_result_hash(dataclasses.asdict(snapshot))


def _validate_tolerance(name: str, value: float) -> None:
    if not value > 0:
        raise ValueError(f"{name} must be positive, got {value}")


def _validate_measure(measure: str) -> None:
    if measure not in _MEASURES:
        raise ValueError(f"measure must be one of {sorted(_MEASURES)}, got {measure!r}")


@dataclasses.dataclass(frozen=True, slots=True)
class PricingReportResponse:
    market_snapshot_id: str
    model_version: str
    measure: Measure
    price: float
    price_tolerance: float
    greeks: Mapping[str, float] | None = None

    def __post_init__(self) -> None:
        _validate_measure(self.measure)
        _validate_tolerance("price_tolerance", self.price_tolerance)


@dataclasses.dataclass(frozen=True, slots=True)
class RiskReportResponse:
    market_snapshot_id: str
    model_version: str
    measure: Measure
    alpha: float
    value_at_risk: float
    value_at_risk_tolerance: float
    expected_shortfall: float
    expected_shortfall_tolerance: float

    def __post_init__(self) -> None:
        _validate_measure(self.measure)
        _validate_tolerance("value_at_risk_tolerance", self.value_at_risk_tolerance)
        _validate_tolerance("expected_shortfall_tolerance", self.expected_shortfall_tolerance)


@dataclasses.dataclass(frozen=True, slots=True)
class ToleranceViolation:
    field: str
    reported: float
    reference: float
    absolute_error: float
    tolerance: float

    def __str__(self) -> str:
        return (
            f"{self.field}: |{self.reported} - {self.reference}| = "
            f"{self.absolute_error} exceeds tolerance {self.tolerance}"
        )


def build_pricing_report(
    snapshot: MarketSnapshot,
    model_version: str,
    measure: Measure,
    price: float,
    price_tolerance: float,
    greeks: Mapping[str, float] | None = None,
) -> PricingReportResponse:
    """`measure` has no default -- same reasoning as the tolerance
    fields (see this module's own docstring): even though every
    VOLTERRA pricer this repository has is risk-neutral by construction
    (SDE-09) and so would in practice always be called with `"Q"`, a
    silent default would not be a deliberate declaration by the caller
    computing the value, which is the entire point of AUD-04."""
    return PricingReportResponse(
        market_snapshot_id=market_snapshot_id(snapshot),
        model_version=model_version,
        measure=measure,
        price=price,
        price_tolerance=price_tolerance,
        greeks=greeks,
    )


def build_risk_report(
    snapshot: MarketSnapshot,
    model_version: str,
    measure: Measure,
    alpha: float,
    value_at_risk: float,
    value_at_risk_tolerance: float,
    expected_shortfall: float,
    expected_shortfall_tolerance: float,
) -> RiskReportResponse:
    """`measure` has no default, for the same reason
    `build_pricing_report`'s does not: a risk-neutral VaR of a
    derivatives book is a legitimate Q-measure risk computation, so `"P"`
    cannot be silently assumed just because this repository's VaR/ES
    (`titan.risk_metrics`) are ordinarily computed over historical/
    simulated physical-measure loss distributions."""
    return RiskReportResponse(
        market_snapshot_id=market_snapshot_id(snapshot),
        model_version=model_version,
        measure=measure,
        alpha=alpha,
        value_at_risk=value_at_risk,
        value_at_risk_tolerance=value_at_risk_tolerance,
        expected_shortfall=expected_shortfall,
        expected_shortfall_tolerance=expected_shortfall_tolerance,
    )


def check_pricing_tolerance(
    report: PricingReportResponse, reference_price: float
) -> ToleranceViolation | None:
    """None if `report.price` is within its own declared budget of
    `reference_price`; otherwise the violation describing by how much
    it was exceeded."""
    error = abs(report.price - reference_price)
    if error > report.price_tolerance:
        return ToleranceViolation(
            field="price",
            reported=report.price,
            reference=reference_price,
            absolute_error=error,
            tolerance=report.price_tolerance,
        )
    return None


def check_risk_tolerance(
    report: RiskReportResponse,
    reference_value_at_risk: float,
    reference_expected_shortfall: float,
) -> list[ToleranceViolation]:
    """Every field of `report` whose declared budget is exceeded by the
    corresponding reference value, independently -- a VaR violation and
    an ES violation are reported separately since they carry separate
    budgets."""
    violations = []
    var_error = abs(report.value_at_risk - reference_value_at_risk)
    if var_error > report.value_at_risk_tolerance:
        violations.append(
            ToleranceViolation(
                field="value_at_risk",
                reported=report.value_at_risk,
                reference=reference_value_at_risk,
                absolute_error=var_error,
                tolerance=report.value_at_risk_tolerance,
            )
        )
    es_error = abs(report.expected_shortfall - reference_expected_shortfall)
    if es_error > report.expected_shortfall_tolerance:
        violations.append(
            ToleranceViolation(
                field="expected_shortfall",
                reported=report.expected_shortfall,
                reference=reference_expected_shortfall,
                absolute_error=es_error,
                tolerance=report.expected_shortfall_tolerance,
            )
        )
    return violations
