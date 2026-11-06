import numpy as np
import pytest

from prometheus.titan.contagion import (
    ClearingNotConvergedError,
    eisenberg_noe_clearing,
    network_concentration,
)


def test_rejects_non_square_liabilities() -> None:
    with pytest.raises(ValueError):
        eisenberg_noe_clearing(np.ones((3, 2)), np.ones(3))


def test_rejects_mismatched_external_assets_shape() -> None:
    with pytest.raises(ValueError):
        eisenberg_noe_clearing(np.ones((2, 2)), np.ones(3))


def test_rejects_negative_liabilities() -> None:
    with pytest.raises(ValueError):
        eisenberg_noe_clearing(-np.ones((2, 2)), np.ones(2))


def test_rejects_nonzero_diagonal() -> None:
    bad = np.array([[1.0, 0.0], [0.0, 0.0]])
    with pytest.raises(ValueError):
        eisenberg_noe_clearing(bad, np.ones(2))


def test_rejects_negative_external_assets() -> None:
    liabilities = np.ones((2, 2)) - np.eye(2)
    with pytest.raises(ValueError):
        eisenberg_noe_clearing(liabilities, np.array([-1.0, 1.0]))


def test_raises_when_iteration_budget_is_exhausted() -> None:
    liabilities = np.array([[0.0, 100.0], [0.0, 0.0]])
    with pytest.raises(ClearingNotConvergedError):
        eisenberg_noe_clearing(liabilities, np.zeros(2), max_iterations=0)


def test_fully_solvent_network_pays_every_obligation_in_full_in_one_step() -> None:
    """When every bank's external assets alone cover its obligations, the
    clearing vector is p_bar exactly, and the very first iteration of the
    fixed-point map is already a fixed point (Phi(p_bar) = p_bar)."""
    liabilities = np.array([[0.0, 30.0], [20.0, 0.0]])
    external_assets = np.array([100.0, 100.0])
    result = eisenberg_noe_clearing(liabilities, external_assets)
    assert result.payments == pytest.approx([30.0, 20.0])
    assert result.iterations == 1
    assert not result.defaulted.any()
    assert result.debtor_shortfall == pytest.approx([0.0, 0.0])
    assert result.creditor_loss == pytest.approx([0.0, 0.0])


def test_two_bank_partial_default_matches_hand_derivation() -> None:
    """Bank 0 owes bank 1 $100 but has only $50 of external assets and no
    other income -- it defaults, paying exactly its available $50. Bank 1
    has no interbank debt of its own, so its own 'shortfall' is zero, but
    it suffers a real $50 creditor loss on the $100 it was owed."""
    liabilities = np.array([[0.0, 100.0], [0.0, 0.0]])
    external_assets = np.array([50.0, 200.0])
    result = eisenberg_noe_clearing(liabilities, external_assets)

    assert result.payments == pytest.approx([50.0, 0.0])
    assert result.nominal_obligations == pytest.approx([100.0, 0.0])
    assert result.received == pytest.approx([0.0, 50.0])
    assert result.nominal_claims == pytest.approx([0.0, 100.0])
    assert list(result.defaulted) == [True, False]
    assert result.debtor_shortfall == pytest.approx([50.0, 0.0])
    assert result.creditor_loss == pytest.approx([0.0, 50.0])
    assert result.equity_after == pytest.approx([0.0, 250.0])


def test_three_bank_cascade_fully_defaults_down_the_chain() -> None:
    """A -> B -> C, each owing $100, with A and B having zero external
    assets: A can't pay anyone, so B receives nothing and also can't pay,
    so both fully default (pay $0). C, well-capitalized with $1000 of
    external assets, survives (it owed nothing itself) but loses the full
    $100 it was counting on receiving from B -- a two-hop cascade."""
    liabilities = np.array(
        [
            [0.0, 100.0, 0.0],
            [0.0, 0.0, 100.0],
            [0.0, 0.0, 0.0],
        ]
    )
    external_assets = np.array([0.0, 0.0, 1000.0])
    result = eisenberg_noe_clearing(liabilities, external_assets)

    assert result.payments == pytest.approx([0.0, 0.0, 0.0])
    assert result.debtor_shortfall == pytest.approx([100.0, 100.0, 0.0])
    assert result.creditor_loss == pytest.approx([0.0, 100.0, 100.0])
    assert list(result.defaulted) == [True, True, False]
    # bank C itself never defaults (it owed nothing) but still absorbs a
    # real loss as a creditor -- captured by creditor_loss, not defaulted.
    assert result.equity_after == pytest.approx([0.0, 0.0, 1000.0])


def test_known_degenerate_pure_cycle_converges_to_trivial_full_payment() -> None:
    """A documented limitation, not a bug: a pure liability ring with zero
    external assets anywhere has the (economically empty) full-payment
    vector as the greatest fixed point, reached immediately since
    Phi(p_bar) = p_bar already -- Eisenberg & Noe's own acknowledged
    degeneracy for 'Ponzi' cycles."""
    liabilities = np.array(
        [
            [0.0, 100.0, 0.0],
            [0.0, 0.0, 100.0],
            [100.0, 0.0, 0.0],
        ]
    )
    external_assets = np.zeros(3)
    result = eisenberg_noe_clearing(liabilities, external_assets)
    assert result.payments == pytest.approx([100.0, 100.0, 100.0])
    assert result.iterations == 1
    assert not result.defaulted.any()


@pytest.mark.parametrize("seed", range(10))
def test_clearing_vector_is_a_genuine_fixed_point_on_random_networks(seed: int) -> None:
    """A general, non-hand-derived cross-check: for many random networks,
    independently recompute Phi(payments) from the result's own reported
    payments and confirm it reproduces the SAME payments -- the defining
    property of a fixed point, checked directly rather than trusted from
    the iteration's own bookkeeping."""
    rng = np.random.default_rng(seed)
    n = 5
    liabilities = rng.uniform(0, 50, (n, n))
    np.fill_diagonal(liabilities, 0.0)
    external_assets = rng.uniform(0, 100, n)

    result = eisenberg_noe_clearing(liabilities, external_assets)

    p_bar = liabilities.sum(axis=1)
    has_debt = p_bar > 0
    safe_p_bar = np.where(has_debt, p_bar, 1.0)
    relative_liabilities = np.where(has_debt[:, None], liabilities / safe_p_bar[:, None], 0.0)
    recomputed = np.clip(external_assets + relative_liabilities.T @ result.payments, 0.0, p_bar)

    assert recomputed == pytest.approx(result.payments, abs=1e-8)
    assert result.nominal_obligations == pytest.approx(p_bar)
    # limited liability: nobody's post-clearing equity is ever negative
    assert np.all(result.equity_after >= -1e-9)


def test_isolated_bank_with_no_interbank_links_pays_and_receives_nothing() -> None:
    liabilities = np.zeros((3, 3))
    external_assets = np.array([10.0, 20.0, 30.0])
    result = eisenberg_noe_clearing(liabilities, external_assets)
    assert result.payments == pytest.approx([0.0, 0.0, 0.0])
    assert result.equity_after == pytest.approx(external_assets)
    assert not result.defaulted.any()


def test_network_concentration_rejects_non_square_matrix() -> None:
    with pytest.raises(ValueError):
        network_concentration(np.ones((3, 2)))


def test_network_concentration_rejects_negative_liabilities() -> None:
    with pytest.raises(ValueError):
        network_concentration(-np.ones((2, 2)))


def test_network_concentration_single_counterparty_is_fully_concentrated() -> None:
    liabilities = np.array([[0.0, 100.0, 0.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
    result = network_concentration(liabilities)
    assert result.debtor_concentration[0] == pytest.approx(1.0)
    assert result.creditor_concentration[1] == pytest.approx(1.0)


def test_network_concentration_equal_split_matches_one_over_n() -> None:
    liabilities = np.array([[0.0, 50.0, 50.0], [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]])
    result = network_concentration(liabilities)
    assert result.debtor_concentration[0] == pytest.approx(0.5)  # HHI over 2 equal shares


def test_network_concentration_is_zero_for_a_bank_with_no_exposure() -> None:
    liabilities = np.zeros((3, 3))
    result = network_concentration(liabilities)
    assert result.debtor_concentration == pytest.approx([0.0, 0.0, 0.0])
    assert result.creditor_concentration == pytest.approx([0.0, 0.0, 0.0])
