"""The orchestration layer: the one place every other subsystem is called
together rather than standalone. Current scope (PR-011): demo_run.py
implements section 16's "Minimum v0.1 demonstration script" verbatim --
simulate a small closed economy, verify all journals, apply one known
monetary shock, generate GBM/Heston market paths, price one European
option under a separately calibrated Q model, compare delta against a
trained cost-aware MLP hedge, compute P&L and CVaR, and export an
auditable report. "If any invariant, valuation tolerance or data-timing
check fails, the run must be marked invalid rather than silently
published" is implemented literally: DemoRunResult.valid is False and
DemoRunResult.invalid_reasons is non-empty whenever any such check fails,
and the run still returns a result object -- it does not raise past this
module's boundary for a check it itself defines.
"""
