# Issue prioritization and independent validation policy

GOV-08 (issue prioritization P0/P1/P2) and GOV-11 (independent
validation/effective challenge process).

## Issue prioritization (GOV-08)

Reuses the existing `evidence.alert_routing`/`evidence.severity_matrix`
P0/P1/P2 taxonomy (OPS-10/DRI-01) rather than inventing a second,
issue-tracker-specific one:

| Severity | Meaning | SLA (this repository's real practice) |
|---|---|---|
| P0 | Incorrect pricing/risk output, data-integrity violation, security exposure | Stop-work; see `docs/governance/RELEASE_GOVERNANCE.md § No-go escalation` |
| P1 | A real bug affecting one subsystem's correctness, not yet shipped as a false "evidenced" claim | Fixed before the next PR in that subsystem lands |
| P2 | Documentation gap, missing test for an already-correct behavior, style | Addressed opportunistically |

**Owner**: the project maintainer, for every severity — see GOV-03's
own honest open status for why no second owner is named.
**Milestone**: this project has no fixed release calendar; "next PR"
is the real, honest unit of scheduling here (see `docs/PR_LEDGER.md`'s
own sequential numbering).

**Honest status**: this policy itself is real and followed (every real
bug found during this session's own development — e.g. the `neural_sde`
reward/unit-scale bugs, the `marl` reward-design bug — was fixed before
its owning PR shipped, not deferred). **"Backlog triaged"** in the
literal sense of a populated issue tracker does not apply: this
repository currently has no open backlog of untracked issues to triage,
confirmed by `CONTRIBUTING.md`'s own description of the actual workflow.

## Independent validation and effective challenge (GOV-11)

**Honest status: this section defines the PROCESS a review would
follow; it does not claim the process has been executed, since no
second, independent reviewer exists in this single-maintainer
repository** (the same gap as GOV-03/SEC-02).

If/when a second reviewer joins this project, "effective challenge"
here means:

1. **Reviewer independence**: the reviewer must not be the author of
   the code/claim under review, and must not have a stake in the
   result (financial, reputational, or otherwise) being favorable.
2. **Review criteria**: for a checklist item claimed "evidenced," the
   reviewer re-runs the cited test from a clean checkout and confirms
   it (a) passes, (b) actually exercises the specific claim made, not
   a weaker adjacent one, and (c) is not disabled/skipped. For a
   numeric finding, the reviewer independently recomputes it from the
   same inputs rather than trusting the number as printed.
3. **Recorded outcome**: approval, rejection, or conditional approval
   with named open findings — reusing `evidence.gate_report
   .GateDecisionForm`'s own `scientific_approval`/
   `security_ops_approval` fields (LCH-12) as the record, not a new,
   parallel approval type.

This is a real, specific, checkable process definition — not a vague
aspiration — but it remains unexecuted. GOV-11 is marked partial for
exactly that reason.
