"""Evidence export: model cards, gate decision forms, and a one-command
evidence bundle (section 16, AUD-08, AUD-11, DOC-06, MLO-09).

The validation in model_card.py and gate_report.py is deliberately strict
in the same spirit as core.ledger and core.money: you cannot construct an
ModelCard with approval_status="APPROVED" without naming a reviewer, and
you cannot construct a GateDecisionForm with decision="GO" or
"CONDITIONAL" without naming every required approver and a sunset date.
This mirrors the master specification's own "Checklist completion
protocol" (section 14): a status is not supposed to be settable without
the evidence that justifies it, and here that rule is enforced by the type
rather than left to a human to remember.
"""
