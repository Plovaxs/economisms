import pytest

from prometheus.econosim.trade_lifecycle import Trade, TradeLedger


def _trade(**overrides: object) -> Trade:
    defaults: dict = dict(
        trade_id="t1",
        buyer_id="buyer",
        seller_id="seller",
        quantity=10.0,
        executed_at_step=5,
        settles_at_step=10,
    )
    defaults.update(overrides)
    return Trade(**defaults)  # type: ignore[arg-type]


def test_rejects_empty_trade_id() -> None:
    with pytest.raises(ValueError, match="trade_id"):
        _trade(trade_id="")


def test_rejects_buyer_equal_to_seller() -> None:
    with pytest.raises(ValueError, match="differ"):
        _trade(buyer_id="same", seller_id="same")


def test_rejects_non_positive_quantity() -> None:
    with pytest.raises(ValueError, match="quantity"):
        _trade(quantity=0.0)
    with pytest.raises(ValueError, match="quantity"):
        _trade(quantity=-5.0)


def test_rejects_negative_executed_at_step() -> None:
    with pytest.raises(ValueError, match="executed_at_step"):
        _trade(executed_at_step=-1)


def test_rejects_settlement_preceding_execution() -> None:
    """Settlement cannot happen before execution -- the basic causal
    ordering LED-10 names."""
    with pytest.raises(ValueError, match="cannot happen before execution"):
        _trade(executed_at_step=10, settles_at_step=5)


def test_same_step_execution_and_settlement_is_allowed() -> None:
    """An instantaneous trade (the only kind this repository's existing
    atomic ledger postings support) is still a valid special case, not
    rejected as degenerate."""
    trade = _trade(executed_at_step=5, settles_at_step=5)
    ledger = TradeLedger()
    ledger.execute(trade)
    assert ledger.net_position_as_of("buyer", 5) == 10.0


def test_rejects_duplicate_trade_id() -> None:
    ledger = TradeLedger()
    ledger.execute(_trade(trade_id="t1"))
    with pytest.raises(ValueError, match="already been executed"):
        ledger.execute(_trade(trade_id="t1", executed_at_step=6, settles_at_step=11))


def test_rejects_out_of_order_execution_recording() -> None:
    """"Track execution... event order": executions must be recorded in
    non-decreasing step order, not accepted in arbitrary order."""
    ledger = TradeLedger()
    ledger.execute(_trade(trade_id="t1", executed_at_step=5, settles_at_step=10))
    with pytest.raises(ValueError, match="non-decreasing step order"):
        ledger.execute(_trade(trade_id="t2", executed_at_step=3, settles_at_step=8))


def test_pending_trade_never_anticipates_its_own_later_settlement() -> None:
    """The literal LED-10 guarantee: a trade executed at step 5 but
    settling at step 10 must NOT be reflected in the buyer's or
    seller's position at any step before 10, even though it has
    already executed and is "known" to the ledger."""
    ledger = TradeLedger()
    ledger.execute(_trade(executed_at_step=5, settles_at_step=10))

    # Before execution: trade doesn't exist in this ledger's view at all.
    assert ledger.net_position_as_of("buyer", 4) == 0.0
    # Executed but not yet settled: position must NOT anticipate it.
    for step in (5, 6, 7, 8, 9):
        assert ledger.net_position_as_of("buyer", step) == 0.0
        assert ledger.net_position_as_of("seller", step) == 0.0
    # Settled: now, and only now, does the position reflect the trade.
    assert ledger.net_position_as_of("buyer", 10) == 10.0
    assert ledger.net_position_as_of("seller", 10) == -10.0
    assert ledger.net_position_as_of("buyer", 11) == 10.0


def test_settled_and_pending_partition_correctly() -> None:
    ledger = TradeLedger()
    ledger.execute(_trade(trade_id="t1", executed_at_step=5, settles_at_step=10))
    ledger.execute(_trade(trade_id="t2", executed_at_step=6, settles_at_step=6))

    pending_at_7 = ledger.pending_trades_as_of(7)
    settled_at_7 = ledger.settled_trades_as_of(7)
    assert {t.trade_id for t in pending_at_7} == {"t1"}
    assert {t.trade_id for t in settled_at_7} == {"t2"}

    pending_at_10 = ledger.pending_trades_as_of(10)
    settled_at_10 = ledger.settled_trades_as_of(10)
    assert pending_at_10 == ()
    assert {t.trade_id for t in settled_at_10} == {"t1", "t2"}


def test_a_trade_not_yet_executed_is_in_neither_settled_nor_pending() -> None:
    ledger = TradeLedger()
    ledger.execute(_trade(trade_id="t1", executed_at_step=5, settles_at_step=10))
    assert ledger.pending_trades_as_of(4) == ()
    assert ledger.settled_trades_as_of(4) == ()


def test_net_position_correctly_nets_multiple_settled_trades() -> None:
    ledger = TradeLedger()
    ledger.execute(
        _trade(
            trade_id="t1",
            buyer_id="a",
            seller_id="b",
            quantity=10.0,
            executed_at_step=1,
            settles_at_step=1,
        )
    )
    ledger.execute(
        _trade(
            trade_id="t2",
            buyer_id="b",
            seller_id="a",
            quantity=4.0,
            executed_at_step=2,
            settles_at_step=2,
        )
    )
    assert ledger.net_position_as_of("a", 2) == 10.0 - 4.0
    assert ledger.net_position_as_of("b", 2) == -10.0 + 4.0
