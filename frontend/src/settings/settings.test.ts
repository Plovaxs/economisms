import { describe, expect, it, vi } from "vitest";

import {
  DEFAULT_ENVIRONMENT,
  DEFAULT_SETTINGS,
  STORAGE_KEY,
  applyToElement,
  exportSettings,
  importSettings,
  loadSettings,
  readEnvironment,
  resolve,
  sanitizeSettings,
  saveSettings,
} from "./settings";

function memoryStorage(initial: Record<string, string> = {}) {
  const data = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => void data.set(k, v),
    removeItem: (k: string) => void data.delete(k),
    data,
  };
}

describe("sanitising", () => {
  it("returns the defaults for anything that is not an object", () => {
    for (const bad of [null, undefined, 5, "x", [], true]) expect(sanitizeSettings(bad)).toEqual(DEFAULT_SETTINGS);
  });

  it("keeps valid values and drops invalid ones field by field", () => {
    const s = sanitizeSettings({
      theme: "nord",
      fontScale: 1.3,
      fontFamily: "comic-sans",
      motion: "reduced",
      cvdSafeCharts: "yes",
      autoRotate: false,
      sidebar: "right",
      unknownField: 1,
    });
    expect(s.theme).toBe("nord");
    expect(s.fontScale).toBe(1.3);
    expect(s.fontFamily).toBe(DEFAULT_SETTINGS.fontFamily);
    expect(s.motion).toBe("reduced");
    expect(s.cvdSafeCharts).toBe(false);
    expect(s.autoRotate).toBe(false);
    expect(s.sidebar).toBe("right");
    expect("unknownField" in s).toBe(false);
  });

  it("refuses an unknown theme and a font scale that is not offered", () => {
    expect(sanitizeSettings({ theme: "hotdog-stand" }).theme).toBe(DEFAULT_SETTINGS.theme);
    expect(sanitizeSettings({ fontScale: 7 }).fontScale).toBe(1);
    expect(sanitizeSettings({ theme: "system" }).theme).toBe("system");
  });
});

describe("storage", () => {
  it("round-trips through storage", () => {
    const storage = memoryStorage();
    const mine = { ...DEFAULT_SETTINGS, theme: "gruvbox", fontScale: 1.15 as const, depth: "low" as const };
    expect(saveSettings(mine, storage)).toBe(true);
    expect(loadSettings(storage)).toEqual(mine);
    expect(JSON.parse(storage.data.get(STORAGE_KEY) ?? "{}").theme).toBe("gruvbox");
  });

  it("survives corrupt data, a missing store and a store that throws", () => {
    expect(loadSettings(memoryStorage({ [STORAGE_KEY]: "{not json" }))).toEqual(DEFAULT_SETTINGS);
    expect(loadSettings(null)).toEqual(DEFAULT_SETTINGS);
    expect(saveSettings(DEFAULT_SETTINGS, null)).toBe(false);
    const hostile = {
      getItem: () => {
        throw new Error("blocked");
      },
      setItem: () => {
        throw new Error("quota");
      },
      removeItem: () => {},
    };
    expect(loadSettings(hostile)).toEqual(DEFAULT_SETTINGS);
    expect(saveSettings(DEFAULT_SETTINGS, hostile)).toBe(false);
  });

  it("exports and imports, and rejects what is not settings", () => {
    const mine = { ...DEFAULT_SETTINGS, theme: "rose-pine", glass: "solid" as const };
    const back = importSettings(exportSettings(mine));
    expect(back.ok && back.settings).toEqual(mine);
    const bare = importSettings(JSON.stringify({ theme: "nord" }));
    expect(bare.ok && bare.settings.theme).toBe("nord");
    expect(importSettings("not json").ok).toBe(false);
    expect(importSettings("5").ok).toBe(false);
    expect(importSettings(JSON.stringify({ format: "econosim-settings", settings: 3 })).ok).toBe(false);
  });
});

describe("resolving the system preferences", () => {
  const env = { ...DEFAULT_ENVIRONMENT };

  it("follows the operating system's colour scheme for theme 'system'", () => {
    const s = { ...DEFAULT_SETTINGS, theme: "system" };
    expect(resolve(s, { ...env, prefersDark: true }).theme.scheme).toBe("dark");
    expect(resolve(s, { ...env, prefersDark: false }).theme.scheme).toBe("light");
  });

  it("honours prefers-reduced-motion unless the person chose otherwise", () => {
    const asked = { ...env, prefersReducedMotion: true };
    expect(resolve(DEFAULT_SETTINGS, asked).reducedMotion).toBe(true);
    expect(resolve({ ...DEFAULT_SETTINGS, motion: "full" }, asked).reducedMotion).toBe(false);
    expect(resolve({ ...DEFAULT_SETTINGS, motion: "reduced" }, env).reducedMotion).toBe(true);
  });

  it("switches to the high-contrast palette of the same scheme, with solid panels and no glow", () => {
    const dark = resolve({ ...DEFAULT_SETTINGS, theme: "nord", contrast: "high" }, env);
    expect(dark.theme.id).toBe("high-contrast");
    expect(dark.attributes["data-glass"]).toBe("solid");
    expect(dark.attributes["data-ambient"]).toBe("off");
    const light = resolve({ ...DEFAULT_SETTINGS, theme: "catppuccin-latte", contrast: "high" }, env);
    expect(light.theme.id).toBe("paper");
    expect(resolve({ ...DEFAULT_SETTINGS, contrast: "system" }, { ...env, prefersMoreContrast: true }).highContrast).toBe(true);
  });

  it("turns the ambient glow and card tilt off when motion is reduced", () => {
    const r = resolve({ ...DEFAULT_SETTINGS, cardTilt: true, motion: "reduced" }, env);
    expect(r.attributes["data-ambient"]).toBe("off");
    expect(r.attributes["data-tilt"]).toBe("off");
    expect(resolve({ ...DEFAULT_SETTINGS, cardTilt: true, motion: "full" }, env).attributes["data-tilt"]).toBe("on");
  });

  it("uses the colour-vision-safe palette for charts when asked", () => {
    const plain = resolve(DEFAULT_SETTINGS, env).chart.series;
    const safe = resolve({ ...DEFAULT_SETTINGS, cvdSafeCharts: true }, env).chart.series;
    expect(safe).not.toEqual(plain);
    expect(new Set(safe).size).toBe(4);
  });
});

describe("applying to the document", () => {
  it("sets data attributes and CSS variables on the element", () => {
    const root = document.createElement("html");
    applyToElement(root, resolve({ ...DEFAULT_SETTINGS, theme: "tokyo-night", fontScale: 1.3 }));
    expect(root.getAttribute("data-theme")).toBe("tokyo-night");
    expect(root.getAttribute("data-font-scale")).toBe("1.3");
    expect(root.style.getPropertyValue("--accent-a")).toBe("122 162 247");
    expect(root.style.getPropertyValue("--slate-950")).toBe("26 27 38");
  });

  it("reads the environment safely when matchMedia is missing or throws", () => {
    expect(readEnvironment(undefined)).toEqual(DEFAULT_ENVIRONMENT);
    expect(readEnvironment({} as Window)).toEqual(DEFAULT_ENVIRONMENT);
    const boom = { matchMedia: vi.fn(() => { throw new Error("x"); }) } as unknown as Window;
    expect(readEnvironment(boom)).toEqual(DEFAULT_ENVIRONMENT);
    const reduce = { matchMedia: (q: string) => ({ matches: q.includes("reduced-motion") }) } as unknown as Window;
    expect(readEnvironment(reduce).prefersReducedMotion).toBe(true);
    expect(readEnvironment(reduce).prefersDark).toBe(false);
  });
});
