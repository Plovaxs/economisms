"""EXT-* live-trading-readiness mechanisms (blueprint track
"separately_gated_live_extension", category EXT, all 12 items).

This package makes zero real network calls, imports zero real
broker/exchange SDKs (there are none in this project's dependencies),
and is never imported by `prometheus.service`, `prometheus.dashboard`,
`prometheus.jobs`, or `prometheus.orchestration` -- see
`charter_guard.py` for a test that enforces this import-graph isolation
directly, not just a docstring claim. Every mechanism here is tested
only against `mock_broker.InMemoryMockBroker`, an obviously-fake
in-memory broker built for this purpose.

What this package IS: a real, tested set of safety mechanisms
(pre-trade limits, a kill switch, reconciliation, multi-party arming,
fault-injection response, an audit log, a shadow-trading harness) that
a real live-trading deployment would need, built and proven against
the mock broker so the mechanism itself is honest engineering, not
theater.

What this package is NOT, and cannot be: a substitute for EXT-02's
regulatory/legal applicability opinion or EXT-09's independent
financial-model validation -- both require a one-time external
deliverable (a named entity's licensed legal opinion; an independent
reviewer's sign-off) that no code can produce or simulate, and neither
is attempted here. See `CHECKLIST_STATUS.md`'s EXT-* rows for exactly
which half of each acceptance criterion is, and is not, met.

The repository's gate decision
(`evidence.repository_status.current_repository_gate_report`) stays
`NO-GO` regardless of anything in this package.
"""
