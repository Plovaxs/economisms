import numpy as np
import pytest

from prometheus.core.ledger import Ledger
from prometheus.core.money import Money
from prometheus.econosim.agents import Bank, Government
from prometheus.econosim.central_bank_ledger import CentralBankLedger, UnregisteredBankError
from prometheus.econosim.interbank_market import InterbankMarket
from prometheus.econosim.network_risk import build_contagion_network, run_contagion_analysis


def usd(major_units: float) -> Money:
    return Money(int(round(major_units * 100)), "USD")


def _setup() -> tuple[Ledger, Bank, Bank, Government, CentralBankLedger]:
    ledger = Ledger()
    bank_a = Bank(ledger, "bank_a", max_leverage=50.0)
    bank_b = Bank(ledger, "bank_b", max_leverage=50.0)
    gov = Government(ledger, "gov")
    cb = CentralBankLedger(ledger, "cb")
    bank_a.capitalize(usd(1000))
    bank_b.capitalize(usd(1000))
    cb.register_bank(bank_a)
    cb.register_bank(bank_b)
    return ledger, bank_a, bank_b, gov, cb


def test_rejects_empty_bank_list() -> None:
    _, _, _, _, cb = _setup()
    with pytest.raises(ValueError):
        build_contagion_network([], cb)


def test_rejects_duplicate_agent_ids() -> None:
    _, bank_a, _, _, cb = _setup()
    with pytest.raises(ValueError):
        build_contagion_network([bank_a, bank_a], cb)


def test_rejects_unregistered_bank() -> None:
    ledger, bank_a, _, _, _ = _setup()
    other_cb = CentralBankLedger(ledger, "other_cb")
    with pytest.raises(UnregisteredBankError):
        build_contagion_network([bank_a], other_cb)


def test_network_matches_hand_computed_values_for_a_well_capitalized_scenario() -> None:
    _, bank_a, bank_b, gov, cb = _setup()
    gov.issue_bonds(bank_a, usd(500))
    cb.purchase_government_bonds(bank_a, usd(300))
    cb.lend_to_bank(bank_b, usd(100))

    network = build_contagion_network([bank_a, bank_b], cb)

    assert network.node_ids == ("bank_a", "bank_b", "cb")
    expected_liabilities = np.array(
        [
            [0.0, 0.0, 0.0],
            [0.0, 0.0, 10_000.0],
            [30_000.0, 10_000.0, 0.0],
        ]
    )
    assert network.liabilities == pytest.approx(expected_liabilities)
    # bank_a: (loans_outstanding=20000 + reserves=100000) = 120000
    # bank_b: (loans_outstanding=0 + reserves=100000) = 100000
    # cb: securities_holdings=30000
    assert network.external_assets == pytest.approx([120_000.0, 100_000.0, 30_000.0])


def test_run_contagion_analysis_reports_no_default_when_well_capitalized() -> None:
    _, bank_a, bank_b, gov, cb = _setup()
    gov.issue_bonds(bank_a, usd(500))
    cb.purchase_government_bonds(bank_a, usd(300))
    cb.lend_to_bank(bank_b, usd(100))

    network, result = run_contagion_analysis([bank_a, bank_b], cb)

    assert not result.defaulted.any()
    assert result.payments == pytest.approx(result.nominal_obligations)
    assert network.liabilities.shape == (3, 3)


def test_central_bank_itself_can_default_when_undercapitalized() -> None:
    """A real systemic-risk scenario built from live ledger state: the
    central bank issues reserves to bank_a via the discount window with no
    securities backing them, bank_a drains the reserves to bank_b via
    interbank settlement, and the central bank itself cannot cover the
    resulting reserve liability to bank_b -- it defaults, exactly like a
    real undercapitalized central bank would."""
    ledger = Ledger()
    bank_a = Bank(ledger, "bank_a", max_leverage=50.0)
    bank_b = Bank(ledger, "bank_b", max_leverage=50.0)
    bank_a.capitalize(usd(10))
    bank_b.capitalize(usd(10))
    cb = CentralBankLedger(ledger, "cb")
    cb.register_bank(bank_a)
    cb.register_bank(bank_b)

    cb.lend_to_bank(bank_a, usd(1000))
    cb.settle_interbank_transfer(bank_a, bank_b, usd(1000))

    network, result = run_contagion_analysis([bank_a, bank_b], cb)
    cb_index = network.node_ids.index("cb")
    bank_a_index = network.node_ids.index("bank_a")
    bank_b_index = network.node_ids.index("bank_b")

    assert result.defaulted[bank_a_index]  # bank_a owes the CB 1000 but has only its capital
    assert result.defaulted[cb_index]  # the CB itself cannot cover its reserve liability
    assert not result.defaulted[bank_b_index]  # bank_b owed nothing itself
    assert result.creditor_loss[bank_b_index] > 0  # but it suffers a real creditor loss


def test_connects_to_a_full_monetary_operations_scenario() -> None:
    """End-to-end integration: run PR-028's real StepHooks-driven monetary
    scenario for many steps, then build a contagion network from the
    resulting live ledger state and clear it -- the first test anywhere in
    this repository connecting ECONOSIM-X's simulated banking system to
    TITAN's systemic-risk analytics."""
    from prometheus.core.calendar import BusinessDayCalendar
    from prometheus.econosim.monetary_operations import (
        MonetaryOperationsConfig,
        MonetaryOperationsProcess,
    )
    from prometheus.econosim.shocks import ShockGenerator, ShockSpec
    from prometheus.econosim.step_hooks import StepHooks
    from prometheus.econosim.time_engine import MacroTimeEngine

    config = MonetaryOperationsConfig(n_steps=24)
    process = MonetaryOperationsProcess(config)
    rng = np.random.default_rng(2)
    shock_generator = ShockGenerator(rng, [ShockSpec(kind="policy_rate", std=0.015)])
    engine = MacroTimeEngine(
        process.economy,
        BusinessDayCalendar(),
        config.start_date,
        shock_generator=shock_generator,
        hooks=StepHooks(
            compute_actions=process.compute_actions, clear_and_settle=process.clear_and_settle
        ),
    )
    for _ in range(config.n_steps):
        engine.advance_step()

    network, result = run_contagion_analysis(
        [process.bank_a, process.bank_b], process.central_bank_ledger
    )

    assert network.liabilities.shape == (3, 3)
    assert np.all(network.external_assets >= 0.0)
    assert np.all(result.equity_after >= -1e-9)
    # the central bank's total obligations must equal exactly the sum of
    # its two reserve liabilities (the only liabilities it has)
    cb_index = network.node_ids.index(process.central_bank_ledger.agent_id)
    assert result.nominal_obligations[cb_index] == pytest.approx(
        network.liabilities[cb_index, :].sum()
    )


def test_without_an_interbank_market_bank_to_bank_edges_stay_zero() -> None:
    """The documented limitation before this feature existed: with no
    InterbankMarket supplied, every off-diagonal bank<->bank entry is
    exactly zero, regardless of real direct lending elsewhere."""
    _, bank_a, bank_b, gov, cb = _setup()
    network = build_contagion_network([bank_a, bank_b], cb)
    assert network.liabilities[0, 1] == 0.0
    assert network.liabilities[1, 0] == 0.0


def test_interbank_market_populates_genuine_bilateral_bank_edges() -> None:
    ledger, bank_a, bank_b, gov, cb = _setup()
    market = InterbankMarket(ledger)
    market.lend(bank_b, bank_a, usd(300))

    network = build_contagion_network([bank_a, bank_b], cb, interbank_market=market)

    assert network.node_ids == ("bank_a", "bank_b", "cb")
    assert network.liabilities[0, 1] == pytest.approx(30_000.0)  # bank_a owes bank_b
    assert network.liabilities[1, 0] == pytest.approx(0.0)  # bank_b owes bank_a nothing


def test_restricted_sample_network_can_miss_a_bank_s_true_resources() -> None:
    """A genuine, real-world-relevant limitation of any partial-sample
    stress test, demonstrated end to end from real ledger mechanics: bank_a
    borrows $1000 from bank_b, then relends it ALL to bank_d -- a bank
    excluded from the analyzed network. Because bank_d is outside the
    sample, the adapter cannot see bank_a's (legitimate) receivable from
    it, so bank_a appears to default on its debt to bank_b even though, in
    the FULL (unobserved) network, it holds an asset that could cover it.
    """
    ledger = Ledger()
    bank_a = Bank(ledger, "bank_a", max_leverage=50.0)
    bank_b = Bank(ledger, "bank_b", max_leverage=50.0)
    bank_d = Bank(ledger, "bank_d", max_leverage=50.0)
    bank_a.capitalize(usd(50))
    bank_b.capitalize(usd(1000))
    bank_d.capitalize(usd(10))
    cb = CentralBankLedger(ledger, "cb")
    for bank in (bank_a, bank_b, bank_d):
        cb.register_bank(bank)
    market = InterbankMarket(ledger)
    market.lend(bank_b, bank_a, usd(1000))
    market.lend(bank_a, bank_d, usd(1000))  # bank_d is NOT included below

    network, result = run_contagion_analysis([bank_a, bank_b], cb, interbank_market=market)
    bank_a_index = network.node_ids.index("bank_a")
    bank_b_index = network.node_ids.index("bank_b")

    assert network.external_assets[bank_a_index] == pytest.approx(5_000.0)  # just its own capital
    assert result.defaulted[bank_a_index]
    assert result.creditor_loss[bank_b_index] > 0
