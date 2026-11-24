# Locked data for the confirmatory protocol

Files here are fetched ONCE, by a tool that prints only labels and digests, and are never overwritten.
They are the exact bytes a confirmatory analysis will score, so the digest the protocol records stays the
digest of what is analysed (BLS revises seasonally adjusted indexes every February, so a later download would
differ).

| File | What | Digest (SHA-256 of the CSV) |
| --- | --- | --- |
| `cpi_sa_bls_2026-11-24.csv` | CPI-U all items, seasonally adjusted, BLS series `CUSR0000SA0`, 2022-01 to 2026-10, no value published for 2025-10 | `236a14d4b6ac86d721feb9533e324ab2a411ec8dfcee0edbf15da4de13874951` |

**No code in this repository has parsed the values** (`tests/unit/test_confirmatory_lock.py` checks the digest,
the month labels and that nothing in `src/` refers to this directory). The protocol's freeze guard stops the
analysis commands from reading it before the freeze. See `docs/confirmatory/DATA_USE_AUDIT.md` for why the
window it covers is partly *re-used* data, and for the three values the assistant saw by accident.

To check a copy: `sha256sum cpi_sa_bls_2026-11-24.csv`. To fetch another series the same way:
`python -m prometheus.confirmatory fetch-cpi --start-year Y --end-year Y --out FILE`.
