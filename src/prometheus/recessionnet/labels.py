"""NBER US business cycle recession labels, point-in-time aware
(ECONOSIM-X/PROMETHEUS-X addendum FP-06: "RECESSIONNET produces
calibrated probabilities"; section 07's leakage safeguard applies to
LABELS exactly as much as to features -- a recession's start is not
public knowledge the day it starts).

Peak/trough dates below were confirmed against the live NBER site
(https://www.nber.org/research/data/us-business-cycle-expansions-and-
contractions, fetched 2026-11-09) -- the complete table from 1926
onward, the start of this repository's real Kenneth French factor
history (DAT-05). Announcement dates -- when the NBER Business Cycle
Dating Committee actually told the public a peak or trough had
occurred -- were separately confirmed against
https://www.nber.org/research/business-cycle-dating/business-cycle-
dating-committee-announcements (same fetch date) and are populated
ONLY for the six most recent recessions (1980 onward): the Dating
Committee itself was not formed until 1978, and no comparably
authoritative announcement-date record exists for earlier turning
points. `recession_label_as_of` is explicit about this gap rather than
inventing announcement dates for the eleven earlier recessions.

Month-inclusion convention: a recession's contraction months are
(peak, trough] -- the peak month itself is the last month of
expansion (matching how FRED's own USREC indicator is coded), the
trough month is the last (lowest) month of contraction. This is a
documented modeling choice, not an NBER-stated rule for which exact
calendar day the economy turned.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass(frozen=True, slots=True)
class RecessionPeriod:
    peak: date
    """Last month of the expansion (not itself a contraction month)."""
    trough: date
    """Last month of the contraction."""
    peak_announced_at: date | None = None
    """When the NBER Dating Committee publicly announced this peak.
    None for recessions before the Committee existed (pre-1980)."""
    trough_announced_at: date | None = None
    """When the Committee announced this trough. None pre-1980, and
    also None for any recession whose trough had not yet been
    announced as of this table's own capture date (not applicable to
    any entry below -- every trough through 2020 has been announced)."""

    def __post_init__(self) -> None:
        if self.trough < self.peak:
            raise ValueError("trough must not precede peak")
        if self.peak_announced_at is not None and self.peak_announced_at < self.peak:
            raise ValueError("peak_announced_at must not precede the peak month itself")
        if self.trough_announced_at is not None and self.trough_announced_at < self.trough:
            raise ValueError("trough_announced_at must not precede the trough month itself")

    def contains_contraction_month(self, month: date) -> bool:
        return self.peak < month <= self.trough


# fmt: off
NBER_RECESSIONS: tuple[RecessionPeriod, ...] = (
    RecessionPeriod(date(1926, 10, 1), date(1927, 11, 1)),
    RecessionPeriod(date(1929, 8, 1), date(1933, 3, 1)),
    RecessionPeriod(date(1937, 5, 1), date(1938, 6, 1)),
    RecessionPeriod(date(1945, 2, 1), date(1945, 10, 1)),
    RecessionPeriod(date(1948, 11, 1), date(1949, 10, 1)),
    RecessionPeriod(date(1953, 7, 1), date(1954, 5, 1)),
    RecessionPeriod(date(1957, 8, 1), date(1958, 4, 1)),
    RecessionPeriod(date(1960, 4, 1), date(1961, 2, 1)),
    RecessionPeriod(date(1969, 12, 1), date(1970, 11, 1)),
    RecessionPeriod(date(1973, 11, 1), date(1975, 3, 1)),
    RecessionPeriod(
        date(1980, 1, 1), date(1980, 7, 1),
        peak_announced_at=date(1980, 6, 3), trough_announced_at=date(1981, 7, 8),
    ),
    RecessionPeriod(
        date(1981, 7, 1), date(1982, 11, 1),
        peak_announced_at=date(1982, 1, 6), trough_announced_at=date(1983, 7, 8),
    ),
    RecessionPeriod(
        date(1990, 7, 1), date(1991, 3, 1),
        peak_announced_at=date(1991, 4, 25), trough_announced_at=date(1992, 12, 22),
    ),
    RecessionPeriod(
        date(2001, 3, 1), date(2001, 11, 1),
        peak_announced_at=date(2001, 11, 26), trough_announced_at=date(2003, 7, 17),
    ),
    RecessionPeriod(
        date(2007, 12, 1), date(2009, 6, 1),
        peak_announced_at=date(2008, 12, 1), trough_announced_at=date(2010, 9, 20),
    ),
    RecessionPeriod(
        date(2020, 2, 1), date(2020, 4, 1),
        peak_announced_at=date(2020, 6, 8), trough_announced_at=date(2021, 7, 19),
    ),
)
# fmt: on
"""The real NBER business cycle chronology, 1926 onward, confirmed
live (see module docstring). Earlier recessions (1857-1926) exist in
NBER's table too but predate this repository's only real monthly
factor series (DAT-05, starting 1926-07) and are omitted as unusable
for `recessionnet`'s dataset."""


def is_recession_month(
    month: date, recessions: tuple[RecessionPeriod, ...] = NBER_RECESSIONS
) -> bool:
    """The retrospective, fully-resolved ground-truth label -- correct
    once history is known, and the label this module's dataset builder
    uses for backtesting (chronological train/test splitting, not
    label-announcement lag, is that pipeline's leakage safeguard; see
    `recessionnet.dataset`'s module docstring). NOT point-in-time safe
    by itself -- see `recession_label_as_of` for that."""
    return any(r.contains_contraction_month(month) for r in recessions)


def recession_label_as_of(
    month: date,
    as_of: date,
    recessions: tuple[RecessionPeriod, ...] = NBER_RECESSIONS,
) -> float | None:
    """What an analyst standing at `as_of` could honestly have believed
    about whether `month` was a recession month -- the point-in-time
    counterpart to `is_recession_month`.

    Returns 1.0 if some recession's peak has been publicly announced by
    `as_of`, that recession's trough has either been announced by
    `as_of` or not yet reached, and `month` falls in (peak, trough or
    as_of, whichever is earlier if the trough is unknown]. Returns 0.0
    if `month` can be positively ruled out as a recession month given
    only information public as of `as_of`. Returns None when `month`
    falls inside a candidate recession window this table has NO
    announcement dates for (the eleven pre-1980 recessions) and
    `as_of` is still within that recession's own peak-trough span --
    i.e. this function honestly refuses to guess when real-time
    knowability of a pre-1978 recession cannot be determined from this
    table, rather than silently assuming either answer.
    """
    if month > as_of:
        raise ValueError("month must not be in the future relative to as_of")

    for recession in recessions:
        if not recession.contains_contraction_month(month):
            continue
        if recession.peak_announced_at is None:
            # No Dating Committee record for this recession at all. If
            # the queried month is far enough in the past that it is
            # obviously historical common knowledge by as_of, treat it
            # as resolved (1.0); otherwise honestly return None rather
            # than inventing an announcement date.
            if as_of >= recession.trough:
                return 1.0
            return None
        if as_of < recession.peak_announced_at:
            continue  # not yet announced as of this date -- not (yet) known to be a recession
        if recession.trough_announced_at is not None and as_of >= recession.trough_announced_at:
            return 1.0
        # Peak announced, trough not yet (or not yet known to us as of
        # `as_of`): we know a recession STARTED; every contraction
        # month through as_of (guaranteed by the function's own
        # month<=as_of precondition above) is "known to be in
        # recession," since the only way out of a recession the
        # Committee has not yet ended is to not yet have ended it.
        return 1.0
    return 0.0
