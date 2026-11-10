# UIX-11: accessibility and responsive-layout test plan

Acceptance wording: "Keyboard navigation and contrast review passes."

This sandboxed environment has no real browser, no screen reader, and
no visual rendering tool. What follows is split explicitly into what
is already checked automatically (real code, real tests, run on every
change) and what still requires a human in a real browser — the
second half is **NOT COVERED** by this repository today, named
plainly rather than implied done.

## Automated today (`prometheus.dashboard.accessibility.check_accessibility`)

Run against every rendered dashboard page in
`tests/unit/test_dashboard_*.py`:

- [x] `<html lang="...">` is present (screen readers mispronounce
  content without a declared language).
- [x] Exactly one `<h1>` exists (a single, correct heading-hierarchy
  root).
- [x] A `<main>` landmark exists (assistive tech can skip to content).
- [x] Every `<img>` carries non-empty `alt` text.
- [x] The page's stylesheet defines a `:focus-visible` rule (a
  keyboard-focused interactive element is not invisible).

## NOT COVERED — requires a human in a real browser

- [ ] **Keyboard-only navigation walkthrough**: tab through every
  interactive element on each view in visual (DOM) order, with no
  keyboard trap, and confirm every action reachable with a mouse is
  also reachable from the keyboard alone.
- [ ] **Screen-reader pass**: at least one full page read with a real
  screen reader (VoiceOver/NVDA/JAWS), confirming table headers,
  landmark announcements, and the provenance badges
  (`dashboard.provenance`) are announced clearly, not just visually
  distinguishable by color.
- [ ] **Color contrast review**: a real contrast-ratio check (e.g.
  WCAG 2.1 AA's 4.5:1 for body text) against the actual rendered
  colors in `dashboard/html.py`'s `_BASE_STYLE` — the tokens were
  chosen to look reasonable, not measured against a contrast formula.
- [ ] **Responsive layout review**: resize a real browser viewport
  (phone width through desktop) and confirm tables/content reflow
  without horizontal scrolling or clipped content; the CSS has no
  explicit breakpoints today.
- [ ] **Full heading hierarchy review**: the automated check confirms
  exactly one `<h1>`, but does not check that `<h2>`/`<h3>` (where
  used) nest correctly without skipped levels.

## Who should run the human half, and when

Before any future UI change that adds a new page or control, and
before this project's own gate (`evidence.gate_report`) is ever asked
to consider a decision stronger than NO-GO — consistent with this
repository's standing position that no independent review of any
claim here has happened yet (see `README.md` § Status & disclaimers).
