# BCBS 239 risk-data-aggregation profile

CMP-05: map risk data lineage/report quality to BCBS 239 concepts;
acceptance — "reconciliation, completeness and timeliness tests
available."

**Technical self-assessment, not a regulatory determination.** BCBS
239 ("Principles for effective risk data aggregation and risk
reporting") is a supervisory standard for banks; this repository is a
research platform, not a regulated bank, and CMP-04/CMP-06's own
applicability-scoping items are the place a real legal/regulatory
reviewer would decide whether (and to what entity) this standard even
applies — that determination is NOT made here. What follows maps this
repository's REAL, already-tested data-handling behavior onto BCBS
239's own vocabulary for the three sub-principles CMP-05 names by
name: accuracy/integrity, completeness and timeliness. The supervisory
principles (12–14: supervisory review, cooperation, remedial action)
are explicitly out of scope — there is no supervisor here.

| BCBS 239 principle | Current state | Evidence |
|---|---|---|
| **3. Accuracy and integrity** (reconciliation) | In place | `core.ledger`: every transfer is checked double-entry (`test_balanced_transfer_updates_both_balances`, `test_globally_imbalanced_transaction_rejected`, `test_balance_sheet_residual_zero_after_transactions`); `econosim.equity_rollforward` reconciles opening/closing equity across all four agent sectors and detects a tampered closing balance (`test_equity_rollforward_reconciles_across_all_four_agent_sectors`, `test_equity_rollforward_detects_a_tampered_closing_balance`) |
| **4. Completeness** | In place | `econosim.schema_contracts`: a unit or currency mismatch is quarantined, not silently dropped or silently coerced (`test_a_unit_mismatch_is_quarantined_not_dropped_or_raised`, `test_a_currency_mismatch_is_quarantined_separately_from_a_unit_mismatch`) — malformed input remains visible as a quarantined record rather than vanishing from the aggregate |
| **5. Timeliness** | In place | Point-in-time data access rejects data that was not actually available as of the simulated date (`test_point_in_time_data_is_not_visible_before_its_publication_step`, `test_no_lookahead_from_future_policy_shocks`, `test_future_publication_is_rejected_if_a_caller_bypasses_point_in_time_store`), with a dedicated negative control confirming a real point-in-time leak produces a large, detectable gap rather than passing silently (`test_a_real_point_in_time_leak_produces_a_large_positive_gap`) |
| **6. Adaptability** | Partial | `evidence.model_inventory`/`evidence.raci_register` give a structured, queryable inventory rather than a fixed report, but no ad-hoc query interface for a new risk dimension exists | Not attempted |
| **1–2. Governance/infrastructure** | See `NIST_CSF_MAPPING.md`'s **Govern** row and `docs/governance/` | — |
| **7–11. Risk reporting practices** | Partial | `dashboard.views`/`dashboard.export` render accuracy/comprehensiveness-checked views (UIX), but distribution/frequency controls assume a single reader, not a reporting chain | Not attempted |
| **12–14. Supervisory review** | Not applicable | No supervisor; see CMP-04/CMP-06 for the actual applicability determination | — |

## What "current state" means here

Every "in place" cell above traces to a real, named, currently-passing
test — not an unverified self-rating. "Partial" cells name what is
missing rather than leaving it implicit. No cell claims this
repository IS subject to BCBS 239, or that any of the above has been
independently reviewed against the standard's own supervisory text;
both remain open, the same honest gap as every other compliance item
in `CHECKLIST_STATUS.md`.
