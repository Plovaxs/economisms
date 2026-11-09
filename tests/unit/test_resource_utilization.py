from datetime import date
from pathlib import Path

import pytest

from prometheus.econosim.price_economy import EconomyRunConfig
from prometheus.evidence.resource_utilization import (
    CapacityForecast,
    ResourceSample,
    UtilizationThresholds,
    classify_utilization,
    forecast_capacity,
    sample_resource_usage,
)
from prometheus.jobs.artifacts import ArtifactStore
from prometheus.orchestration.economy_run import run_economy


def test_sample_resource_usage_against_a_real_empty_artifact_store(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "objects")
    sample = sample_resource_usage(store, date(2026, 1, 1))
    assert sample.artifact_storage_bytes == 0
    assert sample.artifact_storage_max_bytes == store.max_total_bytes
    assert sample.cpu_seconds > 0.0  # this real process has already done real work
    assert sample.ram_bytes > 0


def test_sample_resource_usage_tracks_real_artifacts_put_into_the_store(tmp_path: Path) -> None:
    """Grounded against a REAL `ArtifactStore`, not a mock: putting two
    genuinely different real evidence bundles must grow
    `artifact_storage_bytes` by exactly their combined real size, the
    SAME number `ArtifactStore.put`'s own budget check already uses."""
    store = ArtifactStore(tmp_path / "objects")
    bundle_a = run_economy(EconomyRunConfig(n_steps=2, productivity_shock_step=2)).evidence_bundle
    bundle_b = run_economy(EconomyRunConfig(n_steps=3, productivity_shock_step=2)).evidence_bundle

    stored_a = store.put(bundle_a)
    after_first = sample_resource_usage(store, date(2026, 1, 1))
    assert after_first.artifact_storage_bytes == stored_a.size_bytes

    stored_b = store.put(bundle_b)
    after_second = sample_resource_usage(store, date(2026, 1, 2))
    assert after_second.artifact_storage_bytes == stored_a.size_bytes + stored_b.size_bytes


def test_forecast_capacity_rejects_an_empty_series_name() -> None:
    with pytest.raises(ValueError, match="series_name"):
        forecast_capacity("", [(date(2026, 1, 1), 0.0), (date(2026, 1, 2), 1.0)], budget=10.0)


def test_forecast_capacity_rejects_fewer_than_two_samples() -> None:
    with pytest.raises(ValueError, match="at least two"):
        forecast_capacity("s", [(date(2026, 1, 1), 0.0)], budget=10.0)


def test_forecast_capacity_rejects_a_non_positive_budget() -> None:
    samples = [(date(2026, 1, 1), 0.0), (date(2026, 1, 2), 1.0)]
    with pytest.raises(ValueError, match="budget"):
        forecast_capacity("s", samples, budget=0.0)


def test_forecast_capacity_matches_an_exact_known_linear_trend() -> None:
    """Not an estimate: a deliberately exact linear series (10 units/
    day, starting at 0) has an analytically known slope and a known
    days-until-budget answer, computed by hand: budget 100 is reached
    at day 10, which is 8 days past the last (day-2) sample."""
    samples = [(date(2026, 1, 1), 0.0), (date(2026, 1, 2), 10.0), (date(2026, 1, 3), 20.0)]
    forecast = forecast_capacity("artifact_storage_bytes", samples, budget=100.0)
    assert forecast.current_value == pytest.approx(20.0)
    assert forecast.daily_growth_rate == pytest.approx(10.0, abs=1e-6)
    assert forecast.days_until_budget_exhausted == pytest.approx(8.0, abs=1e-6)


def test_forecast_capacity_is_order_independent_in_the_input_samples() -> None:
    forward = [(date(2026, 1, 1), 0.0), (date(2026, 1, 2), 10.0), (date(2026, 1, 3), 20.0)]
    shuffled = [forward[2], forward[0], forward[1]]
    assert forecast_capacity("s", forward, budget=100.0) == forecast_capacity(
        "s", shuffled, budget=100.0
    )


def test_forecast_capacity_a_flat_series_never_reaches_the_budget() -> None:
    samples = [(date(2026, 1, 1), 5.0), (date(2026, 1, 2), 5.0), (date(2026, 1, 3), 5.0)]
    forecast = forecast_capacity("s", samples, budget=100.0)
    assert forecast.days_until_budget_exhausted is None


def test_forecast_capacity_a_shrinking_series_never_reaches_the_budget() -> None:
    samples = [(date(2026, 1, 1), 20.0), (date(2026, 1, 2), 10.0), (date(2026, 1, 3), 0.0)]
    forecast = forecast_capacity("s", samples, budget=100.0)
    assert forecast.days_until_budget_exhausted is None
    assert forecast.daily_growth_rate < 0.0


def test_utilization_thresholds_rejects_warning_above_critical() -> None:
    with pytest.raises(ValueError, match="thresholds"):
        UtilizationThresholds(warning_fraction=0.9, critical_fraction=0.5)


def test_utilization_thresholds_rejects_a_zero_warning_fraction() -> None:
    with pytest.raises(ValueError, match="thresholds"):
        UtilizationThresholds(warning_fraction=0.0, critical_fraction=0.5)


def test_classify_utilization_rejects_a_non_positive_budget() -> None:
    thresholds = UtilizationThresholds(warning_fraction=0.7, critical_fraction=0.9)
    with pytest.raises(ValueError, match="budget"):
        classify_utilization(1.0, 0.0, thresholds)


def test_classify_utilization_discriminates_ok_warning_and_critical() -> None:
    thresholds = UtilizationThresholds(warning_fraction=0.7, critical_fraction=0.9)
    assert classify_utilization(50, 100, thresholds) == "ok"
    assert classify_utilization(70, 100, thresholds) == "warning"
    assert classify_utilization(90, 100, thresholds) == "critical"
    assert classify_utilization(100, 100, thresholds) == "critical"


def test_resource_sample_is_constructible_directly() -> None:
    sample = ResourceSample(
        as_of=date(2026, 1, 1), cpu_seconds=1.0, ram_bytes=1024,
        artifact_storage_bytes=0, artifact_storage_max_bytes=1000,
    )
    assert sample.ram_bytes == 1024


def test_capacity_forecast_is_constructible_directly() -> None:
    forecast = CapacityForecast(
        series_name="s", current_value=1.0, daily_growth_rate=0.0,
        budget=10.0, days_until_budget_exhausted=None,
    )
    assert forecast.days_until_budget_exhausted is None
