"""Trade execution/settlement event ordering (LED-10: "track execution,
settlement and position event order; trade accounting never anticipates
later settlement states").

Every trade this repository's econosim ledger posts today (`consume`,
`pay_wages`, `market_settlement.settle_market`) is ATOMIC: execution and
settlement happen in the same instant, the same `ledger.post()` call --
there is no gap in which a trade has been agreed but not yet settled.
Real trade accounting (anything with T+1/T+2 settlement, or even same-
day trades that clear later) has exactly that gap, and the risk LED-10
names is specific: reporting an agent's POSITION as if an executed-but-
unsettled trade had already settled is "anticipating a later settlement
state" -- a real accounting error, not a hypothetical one (it is exactly
how a position report can show cash/securities an agent does not
actually have possession of yet).

`TradeLedger` is a standalone, pure in-memory tracker (no `core.ledger`
side effects -- composing with the real Money-based ledger, the way
`econosim.insolvency.allocate_recovery` and `econosim.liquidity` already
compose with it rather than modifying its existing, already-tested
posting code, is left to a future caller) that keeps executed trades
PENDING until their own `settles_at_step` is reached, and answers
position queries using ONLY settled trades as of the queried step --
never a pending one, no matter how long ago it executed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Trade:
    trade_id: str
    buyer_id: str
    seller_id: str
    quantity: float
    executed_at_step: int
    settles_at_step: int

    def __post_init__(self) -> None:
        if not self.trade_id:
            raise ValueError("trade_id must be non-empty")
        if self.buyer_id == self.seller_id:
            raise ValueError("buyer_id and seller_id must differ")
        if self.quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.executed_at_step < 0:
            raise ValueError("executed_at_step must be non-negative")
        if self.settles_at_step < self.executed_at_step:
            raise ValueError(
                f"settles_at_step ({self.settles_at_step}) cannot precede "
                f"executed_at_step ({self.executed_at_step}) -- settlement cannot "
                "happen before execution"
            )


class TradeLedger:
    """Tracks every trade's execution and settlement step, and reports
    net positions using ONLY trades settled as of the queried step."""

    def __init__(self) -> None:
        self._trades: list[Trade] = []
        self._trade_ids: set[str] = set()
        self._last_executed_step: int = -1

    def execute(self, trade: Trade) -> None:
        """Records a trade as executed. `trade.executed_at_step` must be
        >= every previously executed trade's own step -- executions must
        be recorded in non-decreasing step order, the "track execution...
        event order" half of LED-10, checked directly rather than left
        to caller discipline."""
        if trade.trade_id in self._trade_ids:
            raise ValueError(f"trade_id {trade.trade_id!r} has already been executed")
        if trade.executed_at_step < self._last_executed_step:
            raise ValueError(
                f"trade {trade.trade_id!r} executed_at_step={trade.executed_at_step} "
                f"precedes the last recorded execution step {self._last_executed_step} -- "
                "executions must be recorded in non-decreasing step order"
            )
        self._trades.append(trade)
        self._trade_ids.add(trade.trade_id)
        self._last_executed_step = trade.executed_at_step

    def settled_trades_as_of(self, as_of_step: int) -> tuple[Trade, ...]:
        """Every trade whose `settles_at_step <= as_of_step` -- a trade
        executed at step 5 but settling at step 10 is NOT included for
        `as_of_step=7`, even though it has already executed."""
        return tuple(t for t in self._trades if t.settles_at_step <= as_of_step)

    def pending_trades_as_of(self, as_of_step: int) -> tuple[Trade, ...]:
        """Every EXECUTED trade not yet settled as of `as_of_step` --
        `settles_at_step > as_of_step`. A trade not yet executed at all
        (its own `executed_at_step > as_of_step`) is in neither this nor
        `settled_trades_as_of`; it has not entered the ledger's view of
        the world yet."""
        return tuple(
            t
            for t in self._trades
            if t.executed_at_step <= as_of_step < t.settles_at_step
        )

    def net_position_as_of(self, agent_id: str, as_of_step: int) -> float:
        """Net quantity `agent_id` holds from SETTLED trades only, as of
        `as_of_step` -- the literal "never anticipates later settlement
        states" guarantee: an executed-but-pending trade contributes
        nothing here, no matter how long ago it executed."""
        position = 0.0
        for trade in self.settled_trades_as_of(as_of_step):
            if trade.buyer_id == agent_id:
                position += trade.quantity
            elif trade.seller_id == agent_id:
                position -= trade.quantity
        return position
