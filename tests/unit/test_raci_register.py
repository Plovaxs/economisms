from __future__ import annotations

import pytest

from prometheus.evidence.raci_register import (
    RACI_REGISTER,
    REQUIRED_DOMAINS,
    RACICoverageError,
    RACIEntry,
    verify_raci_register,
)


def test_every_required_domain_has_a_real_entry_with_a_named_owner() -> None:
    """GOV-03's own acceptance wording: "RACI register with named
    owners" -- checked directly against the real register."""
    domains = {e.domain for e in RACI_REGISTER}
    assert domains == set(REQUIRED_DOMAINS)
    for entry in RACI_REGISTER:
        assert entry.accountable_owner.strip()
        assert entry.responsible.strip()


def test_no_entry_fabricates_a_second_identity_as_deputy() -> None:
    """The honest half of this item: this repository has no second
    identity to name as a deputy, so every entry says so explicitly
    rather than inventing one."""
    for entry in RACI_REGISTER:
        assert entry.deputy is None


def test_verify_raci_register_passes_on_the_real_register() -> None:
    verify_raci_register()  # must not raise


def test_verify_raci_register_rejects_a_missing_domain() -> None:
    incomplete = tuple(e for e in RACI_REGISTER if e.domain != "risk")
    with pytest.raises(RACICoverageError, match="risk"):
        verify_raci_register(incomplete)


def test_an_entry_rejects_an_unknown_domain() -> None:
    with pytest.raises(ValueError, match="domain"):
        RACIEntry(
            domain="marketing",
            accountable_owner="someone",
            responsible="someone",
            consulted=(),
            informed=(),
            deputy=None,
        )


def test_an_entry_requires_a_non_empty_accountable_owner() -> None:
    with pytest.raises(ValueError, match="accountable_owner"):
        RACIEntry(
            domain="risk",
            accountable_owner="   ",
            responsible="someone",
            consulted=(),
            informed=(),
            deputy=None,
        )
