from pathlib import Path

import pytest

from prometheus.data_ingestion.source_inventory import (
    DataSourceCatalogEntry,
    SourceInventoryError,
    build_source_catalog,
    discover_data_sources,
)


def _repo_data_ingestion_root() -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "prometheus" / "data_ingestion"


def test_data_source_catalog_entry_rejects_an_empty_module() -> None:
    with pytest.raises(ValueError, match="module"):
        DataSourceCatalogEntry(
            module="", source_url="https://x", source_license="CC0",
            approved_by="a", allowed_use="b",
        )


def test_data_source_catalog_entry_rejects_an_empty_approved_by() -> None:
    with pytest.raises(ValueError, match="approved_by"):
        DataSourceCatalogEntry(
            module="m", source_url="https://x", source_license="CC0",
            approved_by="", allowed_use="b",
        )


def test_data_source_catalog_entry_rejects_an_empty_allowed_use() -> None:
    with pytest.raises(ValueError, match="allowed_use"):
        DataSourceCatalogEntry(
            module="m", source_url="https://x", source_license="CC0",
            approved_by="a", allowed_use="",
        )


def test_discovers_exactly_the_real_connectors_in_this_repository() -> None:
    """A real integration check against this repository's own actual
    `data_ingestion` package -- not a hand-built fixture -- confirming
    `transport` (shared infra, not a source) and `__init__` are
    correctly excluded. `kaggle_macro` (real US GDP/claims/Fed-funds/
    M2/NASDAQ data, PR-145) is a genuinely new real source this
    scanner is correctly expected to pick up; `monthly_matrix` has no
    `*_URL`/`*LICENSE` constants of its own (it is a shared helper, not
    a source) and is correctly NOT picked up."""
    discovered = discover_data_sources(_repo_data_ingestion_root())
    assert discovered == ("french_factors", "kaggle_macro", "worldbank")


def test_real_catalog_carries_each_connectors_actual_url_and_license() -> None:
    catalog = build_source_catalog(
        _repo_data_ingestion_root(),
        approved_by="research-lead",
        allowed_use="internal research only",
    )
    by_module = {entry.module: entry for entry in catalog}

    assert by_module["worldbank"].source_url == (
        "https://api.worldbank.org/v2/country/{countries}/indicator/{indicator}"
    )
    assert by_module["worldbank"].source_license == "CC-BY-4.0 (World Bank Open Data)"
    assert by_module["french_factors"].source_url == (
        "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
        "F-F_Research_Data_Factors_CSV.zip"
    )
    assert by_module["french_factors"].source_license == (
        "Kenneth R. French Data Library (free for academic research use)"
    )
    assert all(entry.approved_by == "research-lead" for entry in catalog)
    assert all(entry.allowed_use == "internal research only" for entry in catalog)


def test_a_module_with_only_a_url_constant_raises(tmp_path: Path) -> None:
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "half_source.py").write_text('HALF_SOURCE_URL = "https://example.com/data"\n')
    with pytest.raises(SourceInventoryError, match="half_source"):
        build_source_catalog(tmp_path, approved_by="a", allowed_use="b")


def test_a_module_with_only_a_license_constant_raises(tmp_path: Path) -> None:
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "half_source.py").write_text('HALF_SOURCE_LICENSE = "CC0"\n')
    with pytest.raises(SourceInventoryError, match="half_source"):
        build_source_catalog(tmp_path, approved_by="a", allowed_use="b")


def test_a_module_with_neither_constant_is_excluded(tmp_path: Path) -> None:
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "pure_helper.py").write_text("def helper() -> int:\n    return 1\n")
    assert discover_data_sources(tmp_path) == ()
    assert build_source_catalog(tmp_path, approved_by="a", allowed_use="b") == ()


def test_a_fully_declared_module_in_an_isolated_directory_is_cataloged(tmp_path: Path) -> None:
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "fake_source.py").write_text(
        'FAKE_SOURCE_URL = "https://example.com/fake"\n'
        'FAKE_SOURCE_LICENSE = "MIT"\n'
    )
    catalog = build_source_catalog(tmp_path, approved_by="a", allowed_use="b")
    assert len(catalog) == 1
    assert catalog[0] == DataSourceCatalogEntry(
        module="fake_source",
        source_url="https://example.com/fake",
        source_license="MIT",
        approved_by="a",
        allowed_use="b",
    )
