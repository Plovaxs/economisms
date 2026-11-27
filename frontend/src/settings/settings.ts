import { DEFAULT_THEME, THEMES, chartTheme, systemTheme, themeById, themeVariables } from "./themes";
import type { ChartTheme, ThemeDef } from "./themes";

// Every user-adjustable setting, in one place. The rules, which the tests hold the code to:
//  * a value that is not one of the listed choices is never accepted (a hand-edited or old stored
//    object cannot put the interface into a state nobody designed);
//  * the stored form is a single JSON object under one key, read and written inside try/catch (private
//    windows and blocked storage must not break the page);
//  * "system" means: follow the operating system's own accessibility preference, live.

export const STORAGE_KEY = "econosim.settings.v1";

export const FONT_SCALES = [0.85, 1, 1.15, 1.3, 1.5] as const;
export const FONT_FAMILIES = ["inter", "mono", "system"] as const;
export const LINE_SPACINGS = ["normal", "relaxed", "loose"] as const;
export const MOTIONS = ["system", "full", "reduced"] as const;
export const GLASSES = ["system", "full", "reduced", "solid"] as const;
export const CONTRASTS = ["system", "standard", "high"] as const;
export const FOCUS_RINGS = ["standard", "strong"] as const;
export const TARGET_SIZES = ["standard", "large"] as const;
export const RADII = ["sharp", "soft", "round"] as const;
export const GAPS = ["tight", "normal", "wide"] as const;
export const DENSITIES = ["comfortable", "compact"] as const;
export const SIDEBARS = ["left", "right", "hidden"] as const;
export const DEPTHS = ["auto", "low", "off"] as const;
export const LABELS_3D = ["selected", "all", "none"] as const;

export interface Settings {
  /** a theme id, or "system" */
  theme: string;
  fontScale: (typeof FONT_SCALES)[number];
  fontFamily: (typeof FONT_FAMILIES)[number];
  lineSpacing: (typeof LINE_SPACINGS)[number];
  motion: (typeof MOTIONS)[number];
  glass: (typeof GLASSES)[number];
  contrast: (typeof CONTRASTS)[number];
  cvdSafeCharts: boolean;
  underlineLinks: boolean;
  focusRing: (typeof FOCUS_RINGS)[number];
  targetSize: (typeof TARGET_SIZES)[number];
  radius: (typeof RADII)[number];
  gaps: (typeof GAPS)[number];
  density: (typeof DENSITIES)[number];
  ambient: boolean;
  sidebar: (typeof SIDEBARS)[number];
  topBar: boolean;
  clock: boolean;
  depth: (typeof DEPTHS)[number];
  autoRotate: boolean;
  cardTilt: boolean;
  labels3d: (typeof LABELS_3D)[number];
}

export const DEFAULT_SETTINGS: Settings = {
  theme: DEFAULT_THEME,
  fontScale: 1,
  fontFamily: "inter",
  lineSpacing: "normal",
  motion: "system",
  glass: "system",
  contrast: "system",
  cvdSafeCharts: false,
  underlineLinks: false,
  focusRing: "standard",
  targetSize: "standard",
  radius: "soft",
  gaps: "normal",
  density: "comfortable",
  ambient: true,
  sidebar: "left",
  topBar: true,
  clock: true,
  depth: "auto",
  autoRotate: true,
  cardTilt: false,
  labels3d: "selected",
};

const CHOICES: { [K in keyof Settings]?: readonly Settings[K][] } = {
  fontScale: FONT_SCALES,
  fontFamily: FONT_FAMILIES,
  lineSpacing: LINE_SPACINGS,
  motion: MOTIONS,
  glass: GLASSES,
  contrast: CONTRASTS,
  focusRing: FOCUS_RINGS,
  targetSize: TARGET_SIZES,
  radius: RADII,
  gaps: GAPS,
  density: DENSITIES,
  sidebar: SIDEBARS,
  depth: DEPTHS,
  labels3d: LABELS_3D,
};

const BOOLEANS: (keyof Settings)[] = [
  "cvdSafeCharts",
  "underlineLinks",
  "ambient",
  "topBar",
  "clock",
  "autoRotate",
  "cardTilt",
];

export function isThemeSetting(value: unknown): value is string {
  return typeof value === "string" && (value === "system" || THEMES.some((t) => t.id === value));
}

/** Accept only values this version knows; anything else falls back to the default for that field. */
export function sanitizeSettings(raw: unknown): Settings {
  const out: Settings = { ...DEFAULT_SETTINGS };
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) return out;
  const source = raw as Record<string, unknown>;
  if (isThemeSetting(source.theme)) out.theme = source.theme;
  const target = out as unknown as Record<string, unknown>;
  for (const [key, choices] of Object.entries(CHOICES)) {
    const value = source[key];
    if ((choices as readonly unknown[]).includes(value)) target[key] = value;
  }
  for (const key of BOOLEANS) {
    if (typeof source[key] === "boolean") target[key] = source[key];
  }
  return out;
}

// ----- storage ------------------------------------------------------------------------------

type StorageLike = Pick<Storage, "getItem" | "setItem" | "removeItem">;

function defaultStorage(): StorageLike | null {
  try {
    return typeof window !== "undefined" ? window.localStorage : null;
  } catch {
    return null; // accessing localStorage can itself throw (blocked site data)
  }
}

export function loadSettings(storage: StorageLike | null = defaultStorage()): Settings {
  if (!storage) return { ...DEFAULT_SETTINGS };
  try {
    const text = storage.getItem(STORAGE_KEY);
    return text ? sanitizeSettings(JSON.parse(text)) : { ...DEFAULT_SETTINGS };
  } catch {
    return { ...DEFAULT_SETTINGS };
  }
}

/** True if the settings were written; the page works either way. */
export function saveSettings(settings: Settings, storage: StorageLike | null = defaultStorage()): boolean {
  if (!storage) return false;
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify(settings));
    return true;
  } catch {
    return false;
  }
}

export function exportSettings(settings: Settings): string {
  return JSON.stringify({ format: "econosim-settings", version: 1, settings }, null, 2);
}

export type ImportResult = { ok: true; settings: Settings } | { ok: false; error: string };

export function importSettings(text: string): ImportResult {
  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ok: false, error: "That is not valid JSON." };
  }
  if (typeof parsed !== "object" || parsed === null) return { ok: false, error: "Expected a JSON object." };
  const wrapper = parsed as { format?: unknown; settings?: unknown };
  const body = wrapper.format === "econosim-settings" ? wrapper.settings : parsed;
  if (typeof body !== "object" || body === null) return { ok: false, error: "No settings were found in it." };
  return { ok: true, settings: sanitizeSettings(body) };
}

// ----- resolving "system" -------------------------------------------------------------------

export interface Environment {
  prefersDark: boolean;
  prefersReducedMotion: boolean;
  prefersMoreContrast: boolean;
  prefersReducedTransparency: boolean;
}

export const DEFAULT_ENVIRONMENT: Environment = {
  prefersDark: true,
  prefersReducedMotion: false,
  prefersMoreContrast: false,
  prefersReducedTransparency: false,
};

export interface Resolved {
  theme: ThemeDef;
  reducedMotion: boolean;
  highContrast: boolean;
  glass: "full" | "reduced" | "solid";
  attributes: Record<string, string>;
  chart: ChartTheme;
}

export function resolve(settings: Settings, env: Environment = DEFAULT_ENVIRONMENT): Resolved {
  const themeId = settings.theme === "system" ? systemTheme(env.prefersDark) : settings.theme;
  const highContrast =
    settings.contrast === "high" || (settings.contrast === "system" && env.prefersMoreContrast);
  const chosen = themeById(themeId);
  // High contrast swaps in the high-contrast palette of the same scheme (unless one is already chosen).
  const theme =
    highContrast && chosen.id !== "high-contrast" && chosen.id !== "paper"
      ? themeById(chosen.scheme === "dark" ? "high-contrast" : "paper")
      : chosen;
  const reducedMotion = settings.motion === "reduced" || (settings.motion === "system" && env.prefersReducedMotion);
  const glass: Resolved["glass"] =
    settings.glass === "system" ? (env.prefersReducedTransparency ? "solid" : "full") : settings.glass;
  const depthOff = settings.depth === "off";
  const attributes: Record<string, string> = {
    "data-theme": theme.id,
    "data-scheme": theme.scheme,
    "data-font-scale": String(settings.fontScale),
    "data-font": settings.fontFamily,
    "data-spacing": settings.lineSpacing,
    "data-motion": reducedMotion ? "reduced" : "full",
    "data-glass": highContrast && glass === "full" ? "solid" : glass,
    "data-contrast": highContrast ? "high" : "standard",
    "data-links": settings.underlineLinks ? "underline" : "plain",
    "data-focus": settings.focusRing,
    "data-targets": settings.targetSize,
    "data-radius": settings.radius,
    "data-gaps": settings.gaps,
    "data-density": settings.density,
    "data-ambient": settings.ambient && !highContrast && !reducedMotion ? "on" : "off",
    "data-sidebar": settings.sidebar,
    "data-tilt": settings.cardTilt && !reducedMotion ? "on" : "off",
    "data-depth": depthOff ? "off" : settings.depth,
  };
  return { theme, reducedMotion, highContrast, glass: attributes["data-glass"] as Resolved["glass"], attributes, chart: chartTheme(theme, settings.cvdSafeCharts) };
}

/** Write a resolved configuration onto the document element (attributes for the stylesheet, CSS
 * custom properties for the colours). Uses the CSSOM, which the gateway's CSP allows. */
export function applyToElement(root: HTMLElement, resolved: Resolved): void {
  for (const [name, value] of Object.entries(resolved.attributes)) root.setAttribute(name, value);
  for (const [name, value] of Object.entries(themeVariables(resolved.theme))) {
    if (name === "color-scheme") root.style.colorScheme = value;
    else root.style.setProperty(name, value);
  }
}

export function readEnvironment(win: Pick<Window, "matchMedia"> | undefined = typeof window === "undefined" ? undefined : window): Environment {
  const query = (q: string, fallback: boolean): boolean => {
    try {
      return win && typeof win.matchMedia === "function" ? win.matchMedia(q).matches : fallback;
    } catch {
      return fallback;
    }
  };
  return {
    prefersDark: query("(prefers-color-scheme: dark)", true),
    prefersReducedMotion: query("(prefers-reduced-motion: reduce)", false),
    prefersMoreContrast: query("(prefers-contrast: more)", false),
    prefersReducedTransparency: query("(prefers-reduced-transparency: reduce)", false),
  };
}

export const ENVIRONMENT_QUERIES = [
  "(prefers-color-scheme: dark)",
  "(prefers-reduced-motion: reduce)",
  "(prefers-contrast: more)",
  "(prefers-reduced-transparency: reduce)",
] as const;
