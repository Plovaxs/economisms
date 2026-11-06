from datetime import date

import numpy as np
import pytest

from prometheus.evidence.champion_challenger import (
    ChampionNeverApprovedError,
    build_champion_challenger_report,
)
from prometheus.evidence.model_package import build_model_package
from prometheus.evidence.model_registry import ModelRegistryEntry
from prometheus.hedging.baseline import apply_no_trade_band, black_scholes_delta_hedge_ratios
from prometheus.hedging.simulate import simulate_self_financing_hedge
from prometheus.stochastica.gbm import simulate_gbm_paths
from prometheus.titan.risk_metrics import historical_expected_shortfall


def _matched_hedge_outcomes() -> tuple[np.ndarray, np.ndarray]:
    """A real champion-vs-challenger comparison, not synthetic arrays:
    the classic Black-Scholes delta hedge (champion) against the same
    hedge with a cost-reducing no-trade band (challenger), BOTH
    evaluated on the identical simulated price paths -- "matched data"
    in the most literal sense."""
    rng = np.random.default_rng(0)
    dt = 1 / 252
    n_steps = 60
    maturity = n_steps * dt
    price_paths = simulate_gbm_paths(
        100.0, 0.08, 0.2, maturity, n_steps=n_steps, n_paths=2000, rng=rng
    )
    delta_ratios = black_scholes_delta_hedge_ratios(
        price_paths, dt, 100.0, maturity, 0.03, 0.2, "call"
    )
    banded_ratios = apply_no_trade_band(delta_ratios, band_width=0.05)
    champion = simulate_self_financing_hedge(
        price_paths, dt, 100.0, "call", 0.03, 0.001, 5.0, delta_ratios
    )
    challenger = simulate_self_financing_hedge(
        price_paths, dt, 100.0, "call", 0.03, 0.001, 5.0, banded_ratios
    )
    return champion.terminal_loss, challenger.terminal_loss


def _approved_champion_entry() -> ModelRegistryEntry:
    entry = ModelRegistryEntry("delta_hedge")
    entry.transition(
        "evaluated", "alice", date(2026, 1, 1), "backtest complete", approved_by="alice"
    )
    entry.transition(
        "approved", "alice", date(2026, 1, 2), "beats baseline", approved_by="carol"
    )
    return entry


def test_rejects_a_champion_whose_entry_was_never_approved() -> None:
    """MLO-14's own framing: comparison against the LAST APPROVED
    champion -- a model that was never approved cannot serve as one,
    confirmed against the real `model_registry` audit trail, not a
    caller-asserted label."""
    champion_outcomes, challenger_outcomes = _matched_hedge_outcomes()
    never_approved = ModelRegistryEntry("not-approved")
    with pytest.raises(ChampionNeverApprovedError, match="never been approved"):
        build_champion_challenger_report(
            build_model_package("delta_hedge", "v1", b"champion"),
            never_approved,
            build_model_package("delta_hedge_banded", "v1", b"challenger"),
            metric_fn=lambda losses: historical_expected_shortfall(losses, 0.95),
            champion_outcomes=champion_outcomes,
            challenger_outcomes=challenger_outcomes,
            metric_name="expected_shortfall_95",
            rng=np.random.default_rng(1),
            higher_is_better=False,
        )


def test_rejects_mismatched_shapes_as_not_matched_data() -> None:
    champion_outcomes, challenger_outcomes = _matched_hedge_outcomes()
    with pytest.raises(ValueError, match="MATCHED data"):
        build_champion_challenger_report(
            build_model_package("delta_hedge", "v1", b"champion"),
            _approved_champion_entry(),
            build_model_package("delta_hedge_banded", "v1", b"challenger"),
            metric_fn=lambda losses: historical_expected_shortfall(losses, 0.95),
            champion_outcomes=champion_outcomes,
            challenger_outcomes=challenger_outcomes[:-1],
            metric_name="expected_shortfall_95",
            rng=np.random.default_rng(1),
            higher_is_better=False,
        )


def test_report_carries_the_champion_and_challenger_packages_and_metric_name() -> None:
    champion_outcomes, challenger_outcomes = _matched_hedge_outcomes()
    champion_pkg = build_model_package("delta_hedge", "v1", b"champion")
    challenger_pkg = build_model_package("delta_hedge_banded", "v1", b"challenger")
    report = build_champion_challenger_report(
        champion_pkg,
        _approved_champion_entry(),
        challenger_pkg,
        metric_fn=lambda losses: historical_expected_shortfall(losses, 0.95),
        champion_outcomes=champion_outcomes,
        challenger_outcomes=challenger_outcomes,
        metric_name="expected_shortfall_95",
        rng=np.random.default_rng(1),
        higher_is_better=False,
    )
    assert report.champion == champion_pkg
    assert report.challenger == challenger_pkg
    assert report.metric_name == "expected_shortfall_95"


def test_challenger_is_better_reflects_a_real_lower_is_better_metric() -> None:
    """Grounded in the real matched hedge outcomes: the comparison's
    CI and `challenger_is_better` flag must agree with each other,
    using the lower-is-better convention for a loss metric (ES)."""
    champion_outcomes, challenger_outcomes = _matched_hedge_outcomes()
    report = build_champion_challenger_report(
        build_model_package("delta_hedge", "v1", b"champion"),
        _approved_champion_entry(),
        build_model_package("delta_hedge_banded", "v1", b"challenger"),
        metric_fn=lambda losses: historical_expected_shortfall(losses, 0.95),
        champion_outcomes=champion_outcomes,
        challenger_outcomes=challenger_outcomes,
        metric_name="expected_shortfall_95",
        rng=np.random.default_rng(1),
        higher_is_better=False,
    )
    assert report.challenger_is_better == (report.comparison.ci_high < 0.0)


def test_challenger_is_better_uses_the_opposite_convention_when_higher_is_better() -> None:
    """The discriminating half: flipping `higher_is_better` must flip
    which side of the CI decides "better" -- it is not silently
    ignored."""
    champion_outcomes, challenger_outcomes = _matched_hedge_outcomes()
    report_lower = build_champion_challenger_report(
        build_model_package("delta_hedge", "v1", b"champion"),
        _approved_champion_entry(),
        build_model_package("delta_hedge_banded", "v1", b"challenger"),
        metric_fn=lambda losses: historical_expected_shortfall(losses, 0.95),
        champion_outcomes=champion_outcomes,
        challenger_outcomes=challenger_outcomes,
        metric_name="expected_shortfall_95",
        rng=np.random.default_rng(1),
        higher_is_better=False,
    )
    report_higher = build_champion_challenger_report(
        build_model_package("delta_hedge", "v1", b"champion"),
        _approved_champion_entry(),
        build_model_package("delta_hedge_banded", "v1", b"challenger"),
        metric_fn=lambda losses: historical_expected_shortfall(losses, 0.95),
        champion_outcomes=champion_outcomes,
        challenger_outcomes=challenger_outcomes,
        metric_name="expected_shortfall_95",
        rng=np.random.default_rng(1),
        higher_is_better=True,
    )
    assert report_lower.challenger_is_better == (report_lower.comparison.ci_high < 0.0)
    assert report_higher.challenger_is_better == (report_higher.comparison.ci_low > 0.0)


def test_a_champion_entry_that_was_staged_after_approval_still_counts() -> None:
    """The 'last approved' champion need not CURRENTLY be in the
    'approved' state -- a model that was approved and has since moved
    on to 'staged' is still a legitimate champion to compare against,
    since its audit trail still shows it WAS approved."""
    champion_outcomes, challenger_outcomes = _matched_hedge_outcomes()
    entry = _approved_champion_entry()
    entry.transition("staged", "bob", date(2026, 1, 3), "deployed to staging", approved_by="bob")
    report = build_champion_challenger_report(
        build_model_package("delta_hedge", "v1", b"champion"),
        entry,
        build_model_package("delta_hedge_banded", "v1", b"challenger"),
        metric_fn=lambda losses: historical_expected_shortfall(losses, 0.95),
        champion_outcomes=champion_outcomes,
        challenger_outcomes=challenger_outcomes,
        metric_name="expected_shortfall_95",
        rng=np.random.default_rng(1),
        higher_is_better=False,
    )
    assert report.champion.model_id == "delta_hedge"
