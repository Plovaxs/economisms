import { describe, expect, it } from "vitest";

import { type Rgb, contrastRatio, mix } from "./contrast";
import {
  CVD_SAFE,
  THEMES,
  chartTheme,
  onAccent,
  slateScale,
  systemTheme,
  themeById,
  themeVariables,
} from "./themes";

// WCAG 2.x: 4.5:1 for normal text, 3:1 for large text and for non-text marks (chart series, borders).

describe("contrast arithmetic", () => {
  it("is 21:1 for black on white, 1:1 for a colour on itself, and symmetric", () => {
    expect(contrastRatio([0, 0, 0], [255, 255, 255])).toBeCloseTo(21, 5);
    expect(contrastRatio([90, 90, 90], [90, 90, 90])).toBeCloseTo(1, 10);
    expect(contrastRatio([10, 20, 30], [200, 210, 220])).toBeCloseTo(
      contrastRatio([200, 210, 220], [10, 20, 30]),
      10,
    );
  });

  it("mixes linearly in sRGB", () => {
    expect(mix([0, 0, 0], [100, 200, 50], 0.5)).toEqual([50, 100, 25]);
    expect(mix([1, 2, 3], [9, 9, 9], 0)).toEqual([1, 2, 3]);
  });
});

/** `top` painted over `bottom` at `alpha`, the way the browser composites a translucent layer. */
function over(top: Rgb, bottom: Rgb, alpha: number): Rgb {
  return mix(bottom, top, alpha);
}

describe.each(THEMES.map((t) => [t.id, t] as const))("theme %s", (_id, theme) => {
  const scale = slateScale(theme);
  const panel = mix(theme.bg, theme.surface, 0.55);
  // The flat surfaces, then the ones the components actually stack on them. In the default glass mode
  // the page gets the main panel (overlay at 2%), a card is one more layer (5%) and a field or table
  // head inside a card another. In "solid" mode a card is the opaque panel and a field in it 5% above.
  const main = over(theme.overlay, theme.bg, 0.02);
  const card = over(theme.overlay, main, 0.05);
  const nested = over(theme.overlay, card, 0.05);
  const solidCard = over(theme.overlay, panel, 0.05);
  const surfaces = { page: theme.bg, main, panel, raised: theme.surface, card, nested, solidCard };
  // A hovered row (a card with the overlay at 10%) and a neutral chip (10% over the main panel). Text
  // that sits on them is the brighter part of the scale; the dim stops brighten on hover instead
  // (see Atlas.tsx), so they are not asked to read on a hovered surface.
  const transient = { hover: over(theme.overlay, card, 0.1), chip: over(theme.overlay, main, 0.1) };
  // a selected or active option is the card with the accent at 10% (sourceGuards.test.ts holds the
  // markup to that, since a stronger tint takes the contrast away from the text on it)
  const selected = theme.accents.map((a) => over(a, card, 0.1));

  it.each(Object.entries(surfaces))("reads at 4.5:1 or better on the %s surface", (_n, surface) => {
    for (const stop of [50, 100, 200, 300, 400, 500]) {
      expect(contrastRatio(scale[stop], surface), `slate-${stop}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it.each(Object.entries(transient))("reads at 4.5:1 or better on a %s surface, from the brightest stop to slate-200", (_n, surface) => {
    for (const stop of [50, 100, 200]) {
      expect(contrastRatio(scale[stop], surface), `slate-${stop}`).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("keeps the brighter text stops readable on a selected option, whichever accent tints it", () => {
    for (const surface of selected) {
      for (const stop of [50, 100]) {
        expect(contrastRatio(scale[stop], surface), `slate-${stop}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("keeps the status colours readable as text on every surface", () => {
    for (const surface of Object.values(surfaces)) {
      for (const colour of [theme.good, theme.bad, theme.warn]) {
        expect(contrastRatio(colour, surface)).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("keeps the status colours readable on their own 10% tinted chips, on a card, a field in it and a solid card", () => {
    for (const colour of [theme.good, theme.bad, theme.warn]) {
      for (const [base, alpha] of [
        [card, 0.1],
        [nested, 0.1],
        [solidCard, 0.1],
      ] as const) {
        expect(contrastRatio(colour, over(colour, base, alpha)), `${colour} at ${alpha}`).toBeGreaterThanOrEqual(4.5);
      }
    }
  });

  it("puts readable text on all three stops of the accent gradient", () => {
    const ink = onAccent(theme);
    for (const stop of theme.accents) {
      expect(contrastRatio(ink, stop)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("keeps the accent stops visible against the page as non-text marks (3:1)", () => {
    for (const stop of theme.accents) {
      expect(contrastRatio(stop, theme.bg)).toBeGreaterThanOrEqual(3);
    }
  });

  it("orders the text scale from strongest to faintest", () => {
    const against = (stop: number) => contrastRatio(scale[stop], theme.bg);
    expect(against(50)).toBeGreaterThanOrEqual(against(300));
    expect(against(300)).toBeGreaterThanOrEqual(against(500) - 0.001);
  });

  it("sets every variable the stylesheet and Tailwind read", () => {
    const vars = themeVariables(theme);
    for (const key of ["--c-base", "--overlay", "--accent-a", "--on-accent", "--good", "--slate-50", "--slate-950"]) {
      expect(vars[key], key).toMatch(/^\d+ \d+ \d+$/);
    }
    expect(vars["color-scheme"]).toBe(theme.scheme);
  });

  it("gives the charts enough contrast: series as non-text marks, axes as text", () => {
    const chart = chartTheme(theme, false);
    expect(chart.series).toHaveLength(4);
    expect(contrastRatio(scale[500], theme.surface)).toBeGreaterThanOrEqual(4.5);
  });

  it("offers colour-vision-safe series that are still visible on its background", () => {
    for (const colour of CVD_SAFE[theme.scheme]) {
      expect(contrastRatio(colour, theme.bg), `${colour}`).toBeGreaterThanOrEqual(3);
    }
  });
});

describe("theme registry", () => {
  it("has unique ids, both schemes, and a safe fallback", () => {
    const ids = THEMES.map((t) => t.id);
    expect(new Set(ids).size).toBe(ids.length);
    expect(new Set(THEMES.map((t) => t.scheme))).toEqual(new Set(["dark", "light"]));
    expect(themeById("no-such-theme").id).toBe(THEMES[0].id);
  });

  it("follows the operating system for the 'system' setting", () => {
    expect(themeById(systemTheme(true)).scheme).toBe("dark");
    expect(themeById(systemTheme(false)).scheme).toBe("light");
  });
});

describe("the stylesheet's first-paint defaults", () => {
  it("are exactly the Aurora theme the engine would apply, so there is no flash on load", async () => {
    const { default: css } = await import("../styles/tokens.css?raw");
    const root = css.slice(css.indexOf(":root"), css.indexOf("}", css.indexOf(":root")));
    const vars = themeVariables(themeById("aurora"));
    for (const [name, value] of Object.entries(vars)) {
      if (name === "color-scheme") continue;
      expect(root, name).toContain(`${name}: ${value};`);
    }
  });
});
