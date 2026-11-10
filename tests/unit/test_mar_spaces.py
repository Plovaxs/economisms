from __future__ import annotations

import pytest

from prometheus.marl.spaces import (
    SCHEMA_VERSION,
    BankAction,
    CentralBankAction,
    FirmAction,
    HouseholdAction,
)


def test_schema_version_is_a_real_version_string() -> None:
    assert SCHEMA_VERSION == "mar-spaces-v1"


@pytest.mark.parametrize("raw", [-5.0, -0.001, 0.0, 0.5, 1.0, 1.001, 100.0])
def test_household_action_always_clips_into_zero_one(raw: float) -> None:
    action = HouseholdAction(consumption_fraction=raw)
    assert 0.0 <= action.consumption_fraction <= 1.0


@pytest.mark.parametrize("raw", [-5.0, -0.001, 0.0, 0.5, 1.0, 1.001, 100.0])
def test_firm_action_always_clips_into_zero_one(raw: float) -> None:
    action = FirmAction(wage_fraction=raw)
    assert 0.0 <= action.wage_fraction <= 1.0


@pytest.mark.parametrize("raw", [-5.0, -0.001, 0.0, 0.5, 1.0, 1.001, 100.0])
def test_bank_action_always_clips_into_zero_one(raw: float) -> None:
    action = BankAction(lending_fraction=raw)
    assert 0.0 <= action.lending_fraction <= 1.0


@pytest.mark.parametrize("raw", [-10.0, -0.001, 0.0, 0.1, 0.19, 0.25, 1.0, 1000.0])
def test_central_bank_action_always_clips_into_the_configured_band(raw: float) -> None:
    action = CentralBankAction(policy_rate=raw, rate_min=0.0, rate_max=0.20)
    assert 0.0 <= action.policy_rate <= 0.20


def test_central_bank_action_rejects_an_inverted_band() -> None:
    with pytest.raises(ValueError, match="rate_min"):
        CentralBankAction(policy_rate=0.05, rate_min=0.30, rate_max=0.10)


def test_central_bank_action_honors_a_custom_band() -> None:
    action = CentralBankAction(policy_rate=50.0, rate_min=-0.01, rate_max=0.05)
    assert action.policy_rate == 0.05
