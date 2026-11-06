import pytest

from prometheus.econosim.schema_contracts import (
    QuarantinedRecord,
    SchemaContract,
    UnrecognizedCurrencyError,
    UnrecognizedUnitError,
    map_currency_code,
    normalize_unit,
    validate_against_contract,
)


def test_normalize_unit_converts_between_exact_scales() -> None:
    assert normalize_unit(1.0, "usd billions", "usd millions") == pytest.approx(1000.0)
    assert normalize_unit(1000.0, "usd millions", "usd billions") == pytest.approx(1.0)
    assert normalize_unit(50.0, "percent", "fraction") == pytest.approx(0.5)


def test_normalize_unit_is_case_and_whitespace_insensitive() -> None:
    assert normalize_unit(1.0, "  USD Billions  ", "USD MILLIONS") == pytest.approx(1000.0)


def test_normalize_unit_rejects_an_unrecognized_from_unit() -> None:
    with pytest.raises(UnrecognizedUnitError, match="bushels"):
        normalize_unit(1.0, "bushels", "usd")


def test_normalize_unit_rejects_an_unrecognized_to_unit() -> None:
    with pytest.raises(UnrecognizedUnitError, match="bushels"):
        normalize_unit(1.0, "usd", "bushels")


def test_map_currency_code_normalizes_known_spellings() -> None:
    assert map_currency_code("US Dollar") == "USD"
    assert map_currency_code("  euro  ") == "EUR"
    assert map_currency_code("usd") == "USD"


def test_map_currency_code_rejects_an_unknown_spelling() -> None:
    with pytest.raises(UnrecognizedCurrencyError, match="Bitcoin"):
        map_currency_code("Bitcoin")


def test_schema_contract_rejects_an_empty_series_id() -> None:
    with pytest.raises(ValueError, match="series_id"):
        SchemaContract("", "USD millions", "USD")


def test_schema_contract_rejects_an_empty_expected_unit() -> None:
    with pytest.raises(ValueError, match="expected_unit"):
        SchemaContract("gdp_usa", "", "USD")


def test_schema_contract_rejects_an_unrecognized_expected_currency() -> None:
    with pytest.raises(ValueError, match="expected_currency"):
        SchemaContract("gdp_usa", "USD millions", "DOGE")


def test_schema_contract_allows_a_none_expected_currency() -> None:
    contract = SchemaContract("inflation_rate", "percent", None)
    assert contract.expected_currency is None


def test_a_conforming_record_passes_with_no_quarantine() -> None:
    contract = SchemaContract("gdp_usa", "USD millions", "USD")
    assert validate_against_contract("gdp_usa", "USD millions", "USD", contract) is None


def test_a_unit_mismatch_is_quarantined_not_dropped_or_raised() -> None:
    """DAT-10's own acceptance criterion: "contract failures
    quarantined and logged" -- a mismatch returns a structured record a
    caller can log, never silently disappearing and never raising."""
    contract = SchemaContract("gdp_usa", "USD millions", "USD")
    result = validate_against_contract("gdp_usa", "USD billions", "USD", contract)
    assert isinstance(result, QuarantinedRecord)
    assert "unit mismatch" in result.reason
    assert result.observed_unit == "USD billions"


def test_a_currency_mismatch_is_quarantined_separately_from_a_unit_mismatch() -> None:
    """The discriminating half: a currency mismatch on an OTHERWISE
    correct unit must be reported as a currency problem specifically,
    not conflated with a unit mismatch."""
    contract = SchemaContract("gdp_usa", "USD millions", "USD")
    result = validate_against_contract("gdp_usa", "USD millions", "EUR", contract)
    assert isinstance(result, QuarantinedRecord)
    assert "currency mismatch" in result.reason
    assert result.observed_currency == "EUR"


def test_validating_against_the_wrong_series_contract_raises() -> None:
    contract = SchemaContract("gdp_usa", "USD millions", "USD")
    with pytest.raises(ValueError, match="series_id mismatch"):
        validate_against_contract("gdp_idn", "USD millions", "USD", contract)
