import math
from dataclasses import replace
from datetime import date
from fractions import Fraction as F

import pytest

from prometheus.core.calendar import BusinessDayCalendar
from prometheus.core.money import Money
from prometheus.econosim.monetary_feedback import (
    PRICE_SERIES,
    InflationOutputRule,
    publish_macro_observation,
    published_macro_signal,
)
from prometheus.econosim.pit import MacroObservation, PointInTimeStore


def publish(store, step, observed, price, output=180, lag=1):
    return publish_macro_observation(
        store,
        BusinessDayCalendar(),
        step=step,
        observed_at=observed,
        lag_months=lag,
        price=Money(price),
        produced=F(output),
        trade_quantity=F(1),
    )


def signal_at(store, as_of, step=3, window=12):
    return published_macro_signal(
        store.all_eligible_as_of(as_of),
        as_of=as_of,
        decision_step=step,
        window_months=window,
        potential_output=180.0,
    )


def test_macro_data_is_unavailable_until_publication_and_warms_up_on_two_prices() -> None:
    store = PointInTimeStore()
    first = publish(store, 1, date(2026, 2, 2), 100)
    publish(store, 2, date(2026, 3, 2), 110, output=198)
    assert signal_at(store, date(2026, 2, 2), step=1) is None
    warmup = signal_at(store, date(2026, 3, 2), step=2)
    assert warmup.latest_step == 1 and warmup.annualized_log_inflation is None
    assert first[0].published_at == date(2026, 3, 2)
    complete = signal_at(store, date(2026, 4, 2))
    assert complete.annualized_log_inflation == pytest.approx(12 * math.log(1.1))
    assert complete.output_gap == pytest.approx(0.1)
    assert complete.latest_step == 2 and complete.base_step == 1
    assert all(item.published_at <= date(2026, 4, 2) for item in complete.inputs)


def test_model_month_metadata_prevents_business_day_rolls_from_changing_annualization() -> None:
    store = PointInTimeStore()
    publish(store, 1, date(2026, 1, 30), 100)
    publish(store, 2, date(2026, 3, 2), 110)
    result = signal_at(store, date(2026, 4, 2))
    assert result.price.observation_at.month - result.base_price.observation_at.month == 2
    assert result.annualized_log_inflation == pytest.approx(12 * math.log(1.1))


def test_inflation_window_uses_declared_model_steps() -> None:
    store = PointInTimeStore()
    for step, price in enumerate((100, 105, 110, 121), 1):
        publish(store, step, date(2026, step, 2), price)
    result = signal_at(store, date(2026, 5, 4), step=5, window=2)
    assert result.latest_step == 4 and result.base_step == 2
    assert result.annualized_log_inflation == pytest.approx(math.log(121 / 105) / (2 / 12))


def test_no_trade_quote_never_manufactures_a_macro_observation() -> None:
    store = PointInTimeStore()
    observations = publish_macro_observation(
        store,
        BusinessDayCalendar(),
        step=1,
        observed_at=date(2026, 2, 2),
        lag_months=1,
        price=Money(1),
        produced=F(10),
        trade_quantity=F(0),
    )
    assert observations == ()
    assert store.all_eligible_as_of(date(2030, 1, 1)) == ()


def test_future_publication_is_rejected_if_a_caller_bypasses_point_in_time_store() -> None:
    future = MacroObservation(PRICE_SERIES, date(2026, 2, 2), date(2026, 5, 2), 100.0)
    with pytest.raises(ValueError, match="future observation"):
        published_macro_signal(
            (future,),
            as_of=date(2026, 4, 2),
            decision_step=3,
            window_months=12,
            potential_output=180.0,
        )


def test_policy_reaction_matches_independent_coefficients_and_smoothing() -> None:
    store = PointInTimeStore()
    publish(store, 1, date(2026, 1, 2), 100)
    publish(store, 2, date(2026, 2, 2), 101)
    signal = replace(
        signal_at(store, date(2026, 3, 2)), annualized_log_inflation=0.04, output_gap=0.1
    )
    rule = InflationOutputRule()
    decision = rule.decide(0.03, signal)
    assert decision.unconstrained_target == pytest.approx(0.042)
    assert decision.next_rate == pytest.approx(0.0324)
    assert not decision.floor_binding and not decision.ceiling_binding
    assert rule.decide(0.03, None).next_rate == 0.03


def test_policy_bounds_are_applied_after_smoothing_and_reported() -> None:
    store = PointInTimeStore()
    publish(store, 1, date(2026, 1, 2), 100)
    publish(store, 2, date(2026, 2, 2), 101)
    original = signal_at(store, date(2026, 3, 2))
    rule = InflationOutputRule()
    high = rule.decide(0.03, replace(original, annualized_log_inflation=100.0))
    low = rule.decide(0.03, replace(original, annualized_log_inflation=-100.0))
    assert high.next_rate == rule.rate_ceiling and high.ceiling_binding
    assert low.next_rate == rule.rate_floor and low.floor_binding


@pytest.mark.parametrize(
    "overrides",
    [
        {"inertia": 1.0},
        {"inflation_response": -1.0},
        {"neutral_rate": float("nan")},
        {"rate_floor": 0.04},
        {"output_response": True},
    ],
)
def test_invalid_feedback_rule_is_rejected(overrides) -> None:
    with pytest.raises(ValueError):
        InflationOutputRule(**overrides)


def test_publication_rejects_inexact_integer_price_without_recording_a_partial_release() -> None:
    store = PointInTimeStore()
    with pytest.raises(ValueError, match="represented exactly"):
        publish(store, 1, date(2026, 1, 2), 2**53 + 1)
    assert store.all_eligible_as_of(date(2030, 1, 1)) == ()
