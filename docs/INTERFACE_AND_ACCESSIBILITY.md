# Interface, themes and accessibility

What the two front doors let you change, how it is held to account, and, as importantly, what has **not**
been checked. "Accessible" is a claim about people; this page only claims what a test or a real-browser run
here can back.

## Web app

**Open the command palette with `Ctrl K` (or `Cmd K`, or `/`).** It searches every page, every theme, every
accessibility switch and every model of the Atlas. `?` lists all shortcuts. `Alt 1` to `Alt 5` switch
workspace (Overview, Dashboard, Labs, Model zoo, Settings), `Alt T` cycles the theme, `Alt M` reduces or allows
motion, `Alt B` hides the sidebar.

**Settings** (`/settings`, or the palette) apply at once and are kept in this browser (one JSON object under
the key `econosim.settings.v1`, read and written inside `try/catch`, so blocked storage costs only persistence).
They can be exported, imported and reset on the page. A value that is not one of the listed choices is never
accepted, whatever a stored or imported object says.

| Group | What can be set |
|---|---|
| Theme | twelve palettes (Aurora, Tokyo Night, Catppuccin Mocha and Latte, Gruvbox, Rosé Pine, Nord, Kanagawa, Everforest, Matte Black, and two high-contrast sets, dark and light), or follow the operating system |
| Text | size 85% to 150%, typeface (Inter, JetBrains Mono, the system's), line spacing |
| Motion and effects | motion (follow the system, full, reduced), panels (glass, less blur, solid), the ambient glow, cards that lean toward the pointer |
| Accessibility | contrast (standard or high, or follow the system), colour-blind-safe chart colours, underline every link, a strong focus ring, 44 px click targets |
| Layout | corner radius, gaps between panels, density, sidebar left, right or hidden, the status bar and its clock |
| 3D model web | quality (automatic, low, off), labels, auto-rotation |

"Follow the system" means the operating system's own preference (`prefers-color-scheme`,
`prefers-reduced-motion`, `prefers-contrast`, `prefers-reduced-transparency`), re-read live when it changes.

**The 3D model web** (Atlas page) draws the model zoo's graph on spheres: families are clusters on the outer
shell, the baselines each model was judged against sit on an inner shell near them, pipelines at the core.
Drag to orbit (it coasts when you let go), wheel or pinch to zoom, click to select. Keyboard: arrows rotate, `+`
and `-` zoom, `0` resets, `[` and `]` choose the previous or next model. Lines for judged-against, model
relations and pipeline flows can be switched off, families hidden, labels set to selected, all or none. It is
a hand-written canvas engine with no dependency (`frontend/src/three/engine.ts`), so it adds no third-party
origin to the Content-Security-Policy. With motion reduced it never moves by itself and the flowing dots along
pipelines are not drawn; with 3D set to off, or in a browser without canvas, the 2D web shows the same graph.

## Desktop application

A **Settings** page (the eighth, `Ctrl 8`) with the colour theme (follow the system, dark, light), a
high-contrast variant of either, text size 85% to 150% (the whole application, charts included), reduced
motion, and how the Atlas opens (3D or 2D, turning or still, which labels). Settings are saved to
`settings.json` in the state directory (mode `0600`, in a `0700` directory, written atomically); a
`--theme` given on the command line wins for that run and is not saved over them. The Atlas has the same 3D
web as the browser, in the same engine ported to Python (`desktop/orbit3d.py`).

## What is held to account

* **Contrast is computed, not eyeballed.** For each of the twelve web themes the tests check WCAG 2.x contrast:
  every text colour at least 4.5:1 on the page, panel and raised surfaces; the status colours as text on all
  three; the text that sits on the accent gradient at 4.5:1 on *all three* gradient stops; the accent stops
  3:1 against the page as non-text marks; and that the colour-vision-safe chart series are 3:1 visible. The
  stylesheet's first-paint defaults are compared with the engine's Aurora theme so there is no flash. The
  desktop's two high-contrast palettes are held to 7:1 for text, 7:1 for text on the accent, 4.5:1 for the
  accent and the status text, and strong hairlines.
* **Keyboard and structure.** Tests drive the settings controls (radio groups with one tab stop and arrow keys,
  switches), the palette (a modal combobox with `aria-activedescendant`, Escape, focus returned, Tab kept inside)
  and the shell (skip link, landmarks, a named main region, the page announced after navigation) through
  Testing Library by role and name.
* **A real browser, with the real Content-Security-Policy.** The demo edition was served by this project's own
  gateway (`style-src 'self'`, `script-src 'self'`) and driven in headless Firefox: the palette changed the
  theme, the choice survived a reload, the 3D canvas was painted, a drag rotated it, large text and the
  high-contrast palette applied. Themes are applied through the CSS object model, which that policy allows;
  nothing is inline style or inline script.
* **The 3D maths** (vectors, rotation, projection, depth order, picking, inertia, the layout) is pure code with
  its own tests, in TypeScript and again in Python.

## What has not been checked

* **No assistive technology.** Nothing here was tried with a screen reader (NVDA, VoiceOver, Orca) or a
  switch device. The roles and names are right by the tests; whether they are *good* to listen to is unknown.
* **No formal audit.** This is not a WCAG conformance claim and no one independent has reviewed it.
* **The 3D canvas is not itself readable by assistive technology.** What it offers instead is a live
  announcement of the selected model, keyboard stepping through models, the model card beside it, and the 2D
  web and the Settings switch that replaces it.
* **Colour-blind simulation.** The colour-vision-safe palette is the published Okabe and Ito set, lightness-adjusted
  per scheme and tested for visibility, but it was not run through a colour-vision-deficiency simulator here.
* **Every page at 150% text, on touch devices, on small screens.** The layout is responsive in the usual way
  and checked at a few sizes in a screenshot, not exhaustively.
* **The desktop's high-contrast palettes** are checked by contrast ratios and by rendering, not on Windows or
  macOS, which are untested for this application as a whole.

To regenerate every picture in the README from a running build: `tools/capture_web_screenshots.py --extras`
for the web app and `econosim desktop --screenshots DIR` for the desktop application.
