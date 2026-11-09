from __future__ import annotations

from datetime import date

import pytest

from prometheus.evidence.risk_register import RiskException, RiskRegister


def test_an_exception_requires_a_non_empty_approver_and_description() -> None:
    with pytest.raises(ValueError, match="approver"):
        RiskException(
            description="FRED substituted for home.treasury.gov",
            approver="",
            accepted_at=date(2026, 11, 9),
            sunset_date=date(2027, 2, 9),
        )
    with pytest.raises(ValueError, match="description"):
        RiskException(
            description="   ",
            approver="project maintainer",
            accepted_at=date(2026, 11, 9),
            sunset_date=date(2027, 2, 9),
        )


def test_sunset_date_is_required_and_cannot_precede_accepted_at() -> None:
    with pytest.raises(ValueError, match="sunset_date cannot precede"):
        RiskException(
            description="x",
            approver="project maintainer",
            accepted_at=date(2026, 11, 9),
            sunset_date=date(2026, 1, 1),
        )


def test_a_real_disclosed_exception_from_this_repository_is_active_within_its_window() -> None:
    # PR-146's real, disclosed substitution: home.treasury.gov timed out from
    # this environment, so fred.stlouisfed.org's republication of the same
    # Treasury CMT series was used instead (see CHECKLIST_STATUS.md's PR-146
    # entry and data_ingestion/treasury_yield_curve.py's own docstring).
    exception = RiskException(
        description=(
            "data_ingestion.treasury_yield_curve sources Treasury CMT yields "
            "from FRED's fredgraph.csv rather than home.treasury.gov directly, "
            "because home.treasury.gov timed out from this environment "
            "(confirmed by direct probe, not assumed)"
        ),
        approver="project maintainer",
        accepted_at=date(2026, 11, 9),
        sunset_date=date(2027, 2, 9),
        mitigation=(
            "FRED republishes the identical Federal Reserve H.15 release; "
            "re-probe home.treasury.gov reachability at the next review"
        ),
    )
    assert exception.is_active(date(2026, 12, 1))
    assert not exception.is_active(date(2027, 3, 1))
    assert not exception.is_active(date(2026, 1, 1))


def test_exception_id_is_content_addressed_and_order_independent_of_construction() -> None:
    accepted_at, sunset_date = date(2026, 11, 9), date(2027, 2, 9)
    a = RiskException(
        description="same exception",
        approver="project maintainer",
        accepted_at=accepted_at,
        sunset_date=sunset_date,
    )
    b = RiskException(
        description="same exception",
        approver="project maintainer",
        accepted_at=accepted_at,
        sunset_date=sunset_date,
    )
    assert a.exception_id == b.exception_id
    different = RiskException(
        description="a different exception",
        approver="project maintainer",
        accepted_at=accepted_at,
        sunset_date=sunset_date,
    )
    assert different.exception_id != a.exception_id


def test_register_partitions_active_and_inactive_exceptions_as_of_a_date() -> None:
    # Two real, disclosed exceptions from this repository's own recent PRs.
    fred_substitution = RiskException(
        description="FRED substituted for home.treasury.gov (PR-146)",
        approver="project maintainer",
        accepted_at=date(2026, 11, 9),
        sunset_date=date(2027, 2, 9),
    )
    egress_allowlist_not_wired = RiskException(
        description=(
            "data_ingestion.egress_allowlist.AllowlistedTransport exists but no "
            "connector's production call site was switched to use it yet (PR-148)"
        ),
        approver="project maintainer",
        accepted_at=date(2026, 11, 9),
        sunset_date=date(2026, 12, 9),
    )
    register = RiskRegister(exceptions=(fred_substitution, egress_allowlist_not_wired))

    active_early = register.active_as_of(date(2026, 11, 15))
    assert set(active_early) == {fred_substitution, egress_allowlist_not_wired}
    assert register.inactive_as_of(date(2026, 11, 15)) == ()

    active_later = register.active_as_of(date(2026, 12, 20))
    assert active_later == (fred_substitution,)
    assert register.inactive_as_of(date(2026, 12, 20)) == (egress_allowlist_not_wired,)
