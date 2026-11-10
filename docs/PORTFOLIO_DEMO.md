# A 10-minute evaluation guide

Written for someone deciding whether this repository is worth more of
their time — a professor, a researcher, a technical recruiter. Every
step below is a real command against real code; nothing here is a
screenshot or a claim to take on faith.

## 1. Install and run the real test suite (≈2 minutes to start, ≈4 to finish)

```bash
python3 -m pip install --require-hashes --only-binary=:all: -r requirements/bootstrap.txt
uv sync --locked --all-extras
uv run --locked --all-extras pytest -q
```

Expect **2,738 passed, 0 failed** (see the live badge in `README.md`
for the current count — this document will drift slightly behind it,
the test count never does, since CI regenerates it on every push).

## 2. Run the one-command deterministic smoke test (≈10 seconds)

```bash
uv run --locked --all-extras python -m prometheus.orchestration.replay \
  evidence/api_reference.json --require-integrity --output dist/reference-replay.json
```

This replays a recorded reference run and checks its result hash
matches exactly — the fastest real confirmation that the environment
reproduces this project's own numbers bit-for-bit.

## 3. Start the real research dashboard and click through real output (≈1 minute)

```bash
uv run --locked --all-extras python -m prometheus.dashboard init-auth \
  --credentials /tmp/econosim-demo/auth.json --token-file /tmp/econosim-demo/token --owner alice
uv run --locked --all-extras python -m prometheus.dashboard serve \
  --credentials /tmp/econosim-demo/auth.json --port 8766 --demo
```

Open `http://127.0.0.1:8766/dashboard` with the token from
`/tmp/econosim-demo/token` as a `Bearer` header (or any API client —
curl, Postman, a browser extension). Because credentials were
provisioned with `--owner alice`, this same token also unlocks
`/dashboard/portfolio/alice`, the one owner-scoped view — try
requesting it WITHOUT that token (or with a token for a different
owner) and confirm it's refused with a real HTTP 403, not merely
documented as refused.

Every page on this dashboard renders **real computed output** from the
subsystem it names — a real simulated economy with real posted ledger
transactions, a real Black-Scholes price/Greeks calculation, a real
historical VaR/Expected Shortfall, a real delta-hedge schedule, and —
the page most worth a skeptical look — `/dashboard/experiments`, which
renders this project's own real comparison results **including the
ones where the fancier approach lost**, not a curated highlight reel.

## 4. Read the actual research findings (≈3 minutes)

- [`docs/RESEARCH_CONTRIBUTIONS.md`](./RESEARCH_CONTRIBUTIONS.md) — five
  specific research questions, what was tested, and what was found
  (three "not supported," one "partially supported," one "supported" —
  deliberately not five wins).
- [`docs/RESULTS_AND_LIMITATIONS.md`](./RESULTS_AND_LIMITATIONS.md) —
  the same findings with full numbers and explicit sample-size caveats.

## 5. Spot-check one claim yourself (≈2 minutes)

Pick any row in [`CHECKLIST_STATUS.md`](../CHECKLIST_STATUS.md) marked
"evidenced," open the exact test file it cites, and run just that test:

```bash
uv run --locked --all-extras pytest -q tests/unit/test_neural_sde_ood.py -v
```

That one file independently re-derives the real 2020 COVID extrema
directly from the committed CSV (not from a docstring's claim about
them) before using them as an out-of-distribution test window — a
representative example of this project's evidence discipline, not a
cherry-picked best case.

## What to look for if you're specifically evaluating engineering quality

- `ruff check` and `mypy --strict` clean on every source file, every
  commit (`.github/workflows/ci.yml`).
- Deterministic, seeded, CPU-only models throughout — rerun any test
  twice and get bit-identical results.
- `docs/PR_LEDGER.md` — 160 PRs, each with a stated scope and an
  explicit statement of what it does **not** cover.
- `docs/governance/` and `docs/compliance/` — this project's honest
  accounting of what a single-maintainer research repository genuinely
  cannot self-certify (a second independent reviewer, legal/regulatory
  sign-off, a real penetration test) rather than silently glossing over
  those gaps.
