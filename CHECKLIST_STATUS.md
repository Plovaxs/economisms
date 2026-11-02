# Checklist status

This tracks real status against the blueprint's own checklist IDs
(`docs/PROMETHEUS_Quantitative_Economics_Full_Master_Blueprint.pdf`, section
14 — 374 items across 29 categories, all of which the document itself marks
`[ ] NOT VERIFIED`). Per the blueprint's own protocol: "To set [x], link an
immutable artifact (PR, commit, report, ...) and obtain appropriate review."
No independent review has happened here yet, so nothing below is marked
`[x]` — evidence is linked to a test, which is the strongest claim a single
contributor can honestly make before review.

Everything not listed below is unimplemented. This file will grow, item by
item, alongside the code — it is not a target to backfill in one pass.

## Evidenced today (PR-001 + PR-002)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| GOV-01 (partial) | mission, personas, non-goals published | README.md |
| ECO-01 | typed economic state, immutable transitions | `core.ledger.EconomicState` is a frozen dataclass; `tests/unit/test_ledger.py::test_journal_is_append_only_and_postings_immutable` |
| ECO-02 | household budget feasibility | `tests/unit/test_agents.py::test_consume_more_than_cash_balance_raises_and_does_not_mutate` |
| ECO-03 | firm deposits, output revenue recognition | `tests/unit/test_agents.py::test_firm_pays_wages`, `test_household_receive_income_and_consume` |
| ECO-04 | bank loans/deposits/equity, double-entry | `tests/unit/test_agents.py::test_bank_capitalize_then_originate_loan` |
| ECO-09 | loan underwriting / bank capital limit | `tests/unit/test_agents.py::test_loan_origination_blocked_beyond_leverage_cap` |
| ECO-12 (partial) | deterministic config -> equivalent state/journal hash | `tests/unit/test_ledger.py::test_state_hash_is_deterministic_for_identical_histories`; only covered for the ledger primitive, not a full agent-config -> simulation replay |
| ECO-16 | fail-closed halt on broken accounting identity | `tests/unit/test_ledger.py::test_check_identities_detects_bypassed_mutation`; enforced structurally by `Ledger.post()`'s precondition check, not just detected after the fact |
| LED-01 | every transaction is balanced journal entries | `core.ledger.Ledger.post()`; `tests/unit/test_ledger.py::test_globally_imbalanced_transaction_rejected`, `test_cross_sector_transaction_with_missing_counterpart_rejected` |
| LED-02 | deterministic integer minor units, no float drift | `core.money.Money` rejects non-int/bool input; `tests/unit/test_money.py::test_float_rejected_no_cent_drift` |
| LED-06 (partial) | loan repayment reduces receivable/payable/deposits | `tests/unit/test_agents.py::test_loan_repayment_reduces_debt_and_bank_assets`; no write-off/recovery path |
| LED-12 | global conservation under randomized transaction sequences | `tests/property/test_ledger_invariants.py::test_random_action_sequences_preserve_identities_and_total_equity` (Hypothesis, 100 random examples per run) |
| VAL-07 | economic conservation under randomized transitions | same property test as LED-12 |
| VAL-09 (partial) | deterministic CPU test mode, reference hashes | `EconomicState.state_hash()`; not yet wired to a pinned CI reference-hash fixture |

## Evidenced today (PR-003)

| ID | Requirement (abridged) | Evidence |
|----|-------------------------|----------|
| LED-11 (partial) | time-zone/holiday/business-day calendars | `core.calendar.BusinessDayCalendar`; `tests/unit/test_calendar.py`. Time-zone handling itself (not just business-day stepping) is explicitly out of scope. |
| EXP-03 | random seed hierarchy across agent/market/training, order-independent replay | `core.seeds.SeedHierarchy`; `tests/unit/test_seeds.py::test_stream_identity_is_independent_of_request_order` |
| ECO-13 | no hidden future variables in policy feature vector | `econosim.pit.PointInTimeStore.as_of` / `all_eligible_as_of` only ever expose `published_at <= t`; `tests/unit/test_pit.py`, `tests/unit/test_time_engine.py::test_point_in_time_data_is_not_visible_before_its_publication_step` |
| ECO-14 | shocks to productivity/prices/policy, impulse-response reproducibility | `econosim.shocks.ShockGenerator`; `tests/unit/test_shocks.py::test_same_seed_reproduces_identical_shocks` |
| DAT-07 (partial) | observation/publication timestamp tracking, point-in-time inclusion predicate | `econosim.pit.MacroObservation`/`PointInTimeStore`; full DAT ingestion (FRED-MD/QD, ALFRED, hashing) is not implemented |
| R-03 mitigation (risk register) | release-time data view prevents lookahead leakage | same point-in-time tests as above, exercised across a multi-step replay in `test_time_engine.py` |

## Explicitly NOT done (do not infer otherwise)

- No interest accrual/amortization (LED-05), no default/write-off path beyond a bare repayment reducer (LED-07, LED-10).
- No deposit-instrument reconciliation across the household population (ECO-06, LED-08): household/firm deposit balances are not bank-custodied for non-loan flows in this model, so that check would not be a true invariant yet.
- No government or central-bank agents, no labor or goods-market clearing beyond direct bilateral consume/wages transfers.
- Shocks are drawn deterministically but are not yet *applied* to any agent state (no production function, no policy-rate transmission) -- they are logged and timestamped only; wiring a shock's magnitude into an actual economic effect is future work.
- No stochastic finance, pricing, hedging, risk, optimization, data ingestion (beyond the minimal point-in-time store above), API, MLOps, security, or any governance/compliance item (every category in sections 04-14 beyond ECO/LED/VAL/EXP-03/DAT-07(partial) above).
- No independent review of any item above — "evidenced" here means "covered by a passing automated test in this repository," not peer- or reviewer-approved per the blueprint's own evidence standard.

## How to verify the evidence above yourself

```bash
pip install -e ".[dev]"
pytest -q                # 35 passed
pytest -q --cov=prometheus --cov-report=term-missing
ruff check src tests
mypy src
```
