"""Publication-aware feedback from simulated goods prices and physical output.

Inflation is an annualized log change of positive-volume trade prices over
model months, not CPI or a calibrated inflation measure. Step metadata is
released alongside each observation so business-day date rolls do not
silently change the annualization horizon. Missing trade observations do
not manufacture inflation from an arbitrary no-trade quote.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from fractions import Fraction

from prometheus.core.calendar import BusinessDayCalendar, add_months
from prometheus.core.money import Money
from prometheus.econosim.pit import MacroObservation, PointInTimeStore

PRICE_SERIES = "SIM_GOODS_PRICE_MINOR_USD"
OUTPUT_SERIES = "SIM_PHYSICAL_OUTPUT"
STEP_SERIES = "SIM_OBSERVATION_STEP"
DT = 1.0 / 12.0


@dataclass(frozen=True, slots=True)
class PublishedMacroSignal:
    latest_step: int
    base_step: int | None
    annualized_log_inflation: float | None
    output_gap: float
    price: MacroObservation
    output: MacroObservation
    base_price: MacroObservation | None
    inputs: tuple[MacroObservation, ...]


def publish_macro_observation(
    store: PointInTimeStore,
    calendar: BusinessDayCalendar,
    *,
    step: int,
    observed_at: date,
    lag_months: int,
    price: Money,
    produced: Fraction,
    trade_quantity: Fraction,
) -> tuple[MacroObservation, ...]:
    if type(lag_months) is not int or lag_months < 1 or type(step) is not int or step < 1:
        raise ValueError("publication lag and observation step must be positive integers")
    if price.currency != "USD" or price.minor_units <= 0 or produced < 0 or trade_quantity < 0:
        raise ValueError("invalid realized macro observation")
    if trade_quantity == 0:
        return ()
    numeric_price, numeric_output = float(price.minor_units), float(produced)
    if not math.isfinite(numeric_price) or int(numeric_price) != price.minor_units:
        raise ValueError("macro price cannot be represented exactly as a float")
    if not math.isfinite(numeric_output) or step > 2**53:
        raise ValueError("macro observation cannot be represented with finite numeric values")
    published_at = observed_at
    for _ in range(lag_months):
        published_at = calendar.next_business_day(add_months(published_at, 1))
    observations = tuple(
        MacroObservation(series, observed_at, published_at, value)
        for series, value in (
            (PRICE_SERIES, numeric_price),
            (OUTPUT_SERIES, numeric_output),
            (STEP_SERIES, float(step)),
        )
    )
    for observation in observations:
        store.record(observation)
    return observations


def published_macro_signal(
    released: Sequence[MacroObservation],
    *,
    as_of: date,
    decision_step: int,
    window_months: int,
    potential_output: float,
) -> PublishedMacroSignal | None:
    if type(window_months) is not int or window_months < 1:
        raise ValueError("inflation window must be a positive number of model months")
    if type(decision_step) is not int or decision_step < 1:
        raise ValueError("decision_step must be a positive model step")
    if not math.isfinite(potential_output) or potential_output <= 0:
        raise ValueError("potential_output must be finite and positive")
    series: dict[str, dict[date, MacroObservation]] = {
        key: {} for key in (PRICE_SERIES, OUTPUT_SERIES, STEP_SERIES)
    }
    for observation in released:
        if observation.series_id not in series:
            continue
        if not observation.observation_at <= observation.published_at <= as_of:
            raise ValueError("macro feedback received an unavailable or future observation")
        if not math.isfinite(observation.value):
            raise ValueError("macro feedback values must be finite")
        current = series[observation.series_id].get(observation.observation_at)
        if current is None or observation.published_at > current.published_at:
            series[observation.series_id][observation.observation_at] = observation
    prices, outputs, steps = (series[key] for key in (PRICE_SERIES, OUTPUT_SERIES, STEP_SERIES))
    records: dict[int, tuple[MacroObservation, MacroObservation, MacroObservation]] = {}
    for period in prices.keys() & outputs.keys() & steps.keys():
        price, output, step_meta = prices[period], outputs[period], steps[period]
        step = int(step_meta.value)
        if step_meta.value != step or not 1 <= step <= decision_step:
            raise ValueError("published step metadata is invalid or from the future")
        if step in records or price.value <= 0 or output.value < 0:
            raise ValueError("ambiguous or invalid realized macro observation")
        records[step] = (price, output, step_meta)
    if not records:
        return None
    latest_step = max(records)
    price, output, latest_meta = records[latest_step]
    candidates = [step for step in records if latest_step - window_months <= step < latest_step]
    base_step = min(candidates) if candidates else None
    base_price = records[base_step][0] if base_step is not None else None
    inflation = (
        math.log(price.value / base_price.value) / ((latest_step - base_step) * DT)
        if base_price is not None and base_step is not None
        else None
    )
    gap = output.value / potential_output - 1.0
    if not math.isfinite(gap) or (inflation is not None and not math.isfinite(inflation)):
        raise ValueError("macro feedback transformation produced a non-finite signal")
    inputs: tuple[MacroObservation, ...] = (price, output, latest_meta)
    if base_step is not None:
        inputs += (records[base_step][0], records[base_step][2])
    return PublishedMacroSignal(
        latest_step, base_step, inflation, gap, price, output, base_price, inputs
    )


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    previous_rate: float
    next_rate: float
    unconstrained_target: float | None
    smoothed_rate: float | None
    floor_binding: bool
    ceiling_binding: bool
    signal: PublishedMacroSignal | None
    reason: str


@dataclass(frozen=True, slots=True)
class InflationOutputRule:
    neutral_rate: float = 0.03
    inflation_target: float = 0.02
    inflation_response: float = 0.5
    output_response: float = 0.02
    inertia: float = 0.8
    rate_floor: float = -0.02
    rate_ceiling: float = 0.25

    def __post_init__(self) -> None:
        for value in (
            self.neutral_rate,
            self.inflation_target,
            self.inflation_response,
            self.output_response,
            self.inertia,
            self.rate_floor,
            self.rate_ceiling,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise ValueError("monetary rule parameters must be finite numbers")
        if self.inflation_response < 0 or self.output_response < 0 or not 0 <= self.inertia < 1:
            raise ValueError("responses must be non-negative and inertia in [0, 1)")
        if not self.rate_floor <= self.neutral_rate <= self.rate_ceiling:
            raise ValueError("neutral rate must lie within ordered rate bounds")

    def decide(self, previous_rate: float, signal: PublishedMacroSignal | None) -> PolicyDecision:
        if isinstance(previous_rate, bool) or not isinstance(previous_rate, (int, float)):
            raise ValueError("previous rate must be finite numeric data")
        if (
            not math.isfinite(previous_rate)
            or not self.rate_floor <= previous_rate <= self.rate_ceiling
        ):
            raise ValueError("previous rate must be finite and within policy bounds")
        if signal is None or signal.annualized_log_inflation is None:
            return PolicyDecision(
                previous_rate,
                previous_rate,
                None,
                None,
                False,
                False,
                signal,
                "insufficient_published_history",
            )
        target = (
            self.neutral_rate
            + self.inflation_response * (signal.annualized_log_inflation - self.inflation_target)
            + self.output_response * signal.output_gap
        )
        smoothed = self.inertia * previous_rate + (1 - self.inertia) * target
        if not math.isfinite(target) or not math.isfinite(smoothed):
            raise ValueError("policy response produced a non-finite rate")
        rate = min(self.rate_ceiling, max(self.rate_floor, smoothed))
        return PolicyDecision(
            previous_rate,
            rate,
            target,
            smoothed,
            smoothed < self.rate_floor,
            smoothed > self.rate_ceiling,
            signal,
            "published_price_output_feedback",
        )
