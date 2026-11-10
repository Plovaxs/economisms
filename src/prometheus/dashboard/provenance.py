"""UIX-08: "Display synthetic-vs-historical labels on every
visualization -- Export and screenshots preserve provenance labels."

Reuses this repository's EXISTING disclosure convention
(`evidence.constants.SIMULATION_DISCLAIMER`/`SOURCE_TAG`, AUD-08)
rather than inventing a second, parallel labeling scheme: every
dashboard view's provenance badge is built from the SAME disclaimer
string every evidence-bundle export already carries, so a screenshot
or copy-pasted export carries the identical, already-evidenced wording
-- not a dashboard-only label that could drift from what the rest of
this repository says.

`synthetic_badge()` and `real_data_badge(source)` are deliberately
different functions returning deliberately different text (a real test
confirms the two strings differ) -- a reader must not be able to
mistake one for the other at a glance, the entire point of this item.
"""

from __future__ import annotations

from prometheus.dashboard.html import escape
from prometheus.evidence.constants import SIMULATION_DISCLAIMER, SOURCE_TAG


def synthetic_badge() -> str:
    return (
        f'<span class="provenance synthetic" data-source-tag="{escape(SOURCE_TAG)}">'
        f"SYNTHETIC &mdash; {escape(SIMULATION_DISCLAIMER)}</span>"
    )


def real_data_badge(source: str) -> str:
    if not source or not source.strip():
        raise ValueError("source must not be empty -- a real-data badge names its source")
    return (
        f'<span class="provenance real" data-source-tag="{escape(SOURCE_TAG)}">'
        f"REAL DATA (source: {escape(source)})</span>"
    )
