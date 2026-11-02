"""TITAN: institutional-style risk analytics.

Current scope (PR-006): historical and parametric Value-at-Risk, a tie/atom-
safe Expected Shortfall estimator, maximum drawdown, and a VaR-exception
coverage test. Not yet wired to any portfolio, position book or the
ledger/economy -- these functions take plain arrays of P&L or losses, not
PositionBook/RiskReport objects from the integration contract (section 02);
that wiring, along with factor risk, stress testing and portfolio
optimization, is future work.
"""
