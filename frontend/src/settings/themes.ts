import { type Rgb, contrastRatio, cssTriplet, hex, mix } from "./contrast";

// Themes in the spirit of the omarchy / Hyprland rices: a few well-known palettes, each reduced to
// the dozen colours the interface actually needs. Everything else (the whole slate text scale, the
// glass overlays, the gradient, the status colours) is derived from them, so a theme cannot forget a
// shade. `themes.test.ts` holds every one of them to WCAG contrast on the surfaces text sits on; a
// theme that fails is not a theme.

export type Scheme = "dark" | "light";

export interface ThemeDef {
  id: string;
  name: string;
  scheme: Scheme;
  /** the page background */
  bg: Rgb;
  /** raised surfaces (sidebar, tooltips) */
  surface: Rgb;
  /** primary text */
  fg: Rgb;
  /** secondary text */
  muted: Rgb;
  /** tertiary text: small labels, axis ticks (still held to 4.5:1) */
  subtle: Rgb;
  /** the three stops of the accent gradient */
  accents: readonly [Rgb, Rgb, Rgb];
  good: Rgb;
  bad: Rgb;
  warn: Rgb;
  /** the colour glass panels are tinted with: white on dark themes, the ink on light ones */
  overlay: Rgb;
}

const WHITE: Rgb = [255, 255, 255];

export const THEMES: readonly ThemeDef[] = [
  {
    id: "aurora",
    name: "Aurora",
    scheme: "dark",
    bg: [10, 11, 16],
    surface: [18, 21, 28],
    fg: [241, 245, 249],
    muted: [148, 163, 184],
    subtle: [129, 144, 167],
    accents: [
      [139, 92, 246],
      [217, 70, 239],
      [34, 211, 238],
    ],
    good: [110, 231, 183],
    bad: [253, 164, 175],
    warn: [252, 211, 77],
    overlay: WHITE,
  },
  {
    id: "tokyo-night",
    name: "Tokyo Night",
    scheme: "dark",
    bg: [26, 27, 38],
    surface: [36, 40, 59],
    fg: [192, 202, 245],
    muted: [154, 165, 206],
    subtle: [147, 158, 202],
    accents: [
      [122, 162, 247],
      [187, 154, 247],
      [125, 207, 255],
    ],
    good: [158, 206, 106],
    bad: [249, 144, 163],
    warn: [224, 175, 104],
    overlay: WHITE,
  },
  {
    id: "catppuccin-mocha",
    name: "Catppuccin Mocha",
    scheme: "dark",
    bg: [30, 30, 46],
    surface: [49, 50, 68],
    fg: [205, 214, 244],
    muted: [166, 173, 200],
    subtle: [156, 162, 187],
    accents: [
      [203, 166, 247],
      [245, 194, 231],
      [116, 199, 236],
    ],
    good: [166, 227, 161],
    bad: [244, 153, 178],
    warn: [249, 226, 175],
    overlay: WHITE,
  },
  {
    id: "catppuccin-latte",
    name: "Catppuccin Latte",
    scheme: "light",
    bg: [239, 241, 245],
    surface: [230, 233, 239],
    fg: [76, 79, 105],
    muted: [92, 95, 119],
    subtle: [93, 96, 120],
    accents: [
      [114, 44, 200],
      [165, 40, 130],
      [4, 100, 130],
    ],
    good: [32, 102, 25],
    bad: [175, 9, 46],
    warn: [130, 74, 0],
    overlay: [76, 79, 105],
  },
  {
    id: "gruvbox",
    name: "Gruvbox",
    scheme: "dark",
    bg: [40, 40, 40],
    surface: [60, 56, 54],
    fg: [235, 219, 178],
    muted: [189, 174, 147],
    subtle: [187, 172, 144],
    accents: [
      [254, 128, 25],
      [250, 189, 47],
      [142, 192, 124],
    ],
    good: [194, 197, 68],
    bad: [249, 172, 154],
    warn: [250, 189, 47],
    overlay: WHITE,
  },
  {
    id: "rose-pine",
    name: "Rosé Pine",
    scheme: "dark",
    bg: [25, 23, 36],
    surface: [31, 29, 46],
    fg: [224, 222, 244],
    muted: [157, 153, 182],
    subtle: [157, 153, 181],
    accents: [
      [196, 167, 231],
      [235, 188, 186],
      [156, 207, 216],
    ],
    good: [156, 207, 216],
    bad: [239, 141, 169],
    warn: [246, 193, 119],
    overlay: WHITE,
  },
  {
    id: "nord",
    name: "Nord",
    scheme: "dark",
    bg: [46, 52, 64],
    surface: [59, 66, 82],
    fg: [236, 239, 244],
    muted: [196, 205, 220],
    subtle: [178, 188, 205],
    accents: [
      [136, 192, 208],
      [129, 161, 193],
      [180, 142, 173],
    ],
    good: [195, 213, 180],
    bad: [239, 197, 203],
    warn: [235, 203, 139],
    overlay: WHITE,
  },
  {
    id: "kanagawa",
    name: "Kanagawa",
    scheme: "dark",
    bg: [31, 31, 40],
    surface: [42, 42, 55],
    fg: [220, 215, 186],
    muted: [182, 178, 152],
    subtle: [167, 163, 140],
    accents: [
      [126, 156, 216],
      [149, 127, 184],
      [127, 180, 202],
    ],
    good: [155, 189, 112],
    bad: [239, 156, 163],
    warn: [230, 195, 132],
    overlay: WHITE,
  },
  {
    id: "everforest",
    name: "Everforest",
    scheme: "dark",
    bg: [39, 46, 51],
    surface: [46, 56, 60],
    fg: [211, 198, 170],
    muted: [174, 182, 162],
    subtle: [180, 181, 160],
    accents: [
      [167, 192, 128],
      [131, 192, 146],
      [127, 187, 179],
    ],
    good: [186, 206, 156],
    bad: [233, 188, 181],
    warn: [222, 194, 139],
    overlay: WHITE,
  },
  {
    id: "matte-black",
    name: "Matte Black",
    scheme: "dark",
    bg: [12, 12, 12],
    surface: [24, 24, 24],
    fg: [235, 235, 235],
    muted: [175, 175, 175],
    subtle: [150, 150, 150],
    accents: [
      [230, 142, 13],
      [255, 193, 7],
      [200, 200, 200],
    ],
    good: [142, 214, 143],
    bad: [241, 119, 119],
    warn: [255, 200, 87],
    overlay: WHITE,
  },
  {
    id: "high-contrast",
    name: "High contrast (dark)",
    scheme: "dark",
    bg: [0, 0, 0],
    surface: [10, 10, 10],
    fg: [255, 255, 255],
    muted: [235, 235, 235],
    subtle: [210, 210, 210],
    accents: [
      [90, 200, 255],
      [255, 235, 59],
      [120, 255, 160],
    ],
    good: [90, 255, 140],
    bad: [255, 120, 120],
    warn: [255, 220, 80],
    overlay: WHITE,
  },
  {
    id: "paper",
    name: "Paper (high contrast, light)",
    scheme: "light",
    bg: [255, 255, 255],
    surface: [245, 245, 245],
    fg: [0, 0, 0],
    muted: [40, 40, 40],
    subtle: [75, 75, 75],
    accents: [
      [0, 51, 204],
      [102, 0, 153],
      [0, 102, 102],
    ],
    good: [0, 100, 0],
    bad: [160, 0, 0],
    warn: [120, 70, 0],
    overlay: [0, 0, 0],
  },
];

export const DEFAULT_THEME = "aurora";

export function themeById(id: string): ThemeDef {
  return THEMES.find((t) => t.id === id) ?? THEMES[0];
}

/** The slate text scale, derived from the theme's three ink colours and its background. */
export function slateScale(t: ThemeDef): Record<number, Rgb> {
  return {
    50: t.fg,
    100: mix(t.fg, t.muted, 0.1),
    200: mix(t.fg, t.muted, 0.3),
    300: mix(t.fg, t.muted, 0.55),
    400: t.muted,
    500: t.subtle,
    600: mix(t.subtle, t.bg, 0.45),
    700: mix(t.subtle, t.bg, 0.7),
    800: mix(t.bg, t.fg, 0.14),
    900: mix(t.bg, t.fg, 0.08),
    950: t.bg,
  };
}

/** The text colour that sits on the accent gradient: of the theme's own bg and fg and pure black and
 * white, whichever reads best on the *worst* of the three gradient stops. */
export function onAccent(t: ThemeDef): Rgb {
  const candidates: Rgb[] = [t.bg, t.fg, [0, 0, 0], [255, 255, 255]];
  const worst = (ink: Rgb) => Math.min(...t.accents.map((a) => contrastRatio(ink, a)));
  return candidates.reduce((best, c) => (worst(c) > worst(best) ? c : best));
}

/** A colour-vision-safe categorical palette (Okabe and Ito), lightness-adjusted for the scheme. */
export const CVD_SAFE: Record<Scheme, readonly Rgb[]> = {
  dark: [
    [86, 180, 233],
    [230, 159, 0],
    [0, 188, 140],
    [204, 121, 167],
  ],
  light: [
    [0, 114, 178],
    [190, 85, 0],
    [0, 115, 85],
    [150, 40, 115],
  ],
};

export interface ChartTheme {
  series: string[];
  axis: string;
  tooltipBackground: string;
  tooltipBorder: string;
  grid: string;
  ink: string;
}

export function chartTheme(t: ThemeDef, cvdSafe: boolean): ChartTheme {
  const series = cvdSafe
    ? CVD_SAFE[t.scheme].map(hex)
    : [t.accents[0], t.accents[2], t.accents[1], t.muted].map(hex);
  return {
    series,
    axis: hex(t.subtle),
    tooltipBackground: hex(t.surface),
    tooltipBorder: `rgba(${t.overlay[0]},${t.overlay[1]},${t.overlay[2]},0.18)`,
    grid: `rgba(${t.overlay[0]},${t.overlay[1]},${t.overlay[2]},0.08)`,
    ink: hex(t.fg),
  };
}

/** Every CSS custom property a theme sets on the document element. */
export function themeVariables(t: ThemeDef): Record<string, string> {
  const vars: Record<string, string> = {
    "--c-base": cssTriplet(t.bg),
    "--c-elevated": cssTriplet(t.surface),
    "--c-panel": cssTriplet(mix(t.bg, t.surface, 0.55)),
    "--overlay": cssTriplet(t.overlay),
    "--accent-a": cssTriplet(t.accents[0]),
    "--accent-b": cssTriplet(t.accents[1]),
    "--accent-c": cssTriplet(t.accents[2]),
    "--on-accent": cssTriplet(onAccent(t)),
    "--good": cssTriplet(t.good),
    "--bad": cssTriplet(t.bad),
    "--warn": cssTriplet(t.warn),
    "--shadow-ink": t.scheme === "dark" ? "0 0 0" : "40 40 60",
    "color-scheme": t.scheme,
  };
  for (const [stop, colour] of Object.entries(slateScale(t))) {
    vars[`--slate-${stop}`] = cssTriplet(colour);
  }
  return vars;
}

/** Pick the theme for the "system" setting from the operating system's preference. */
export function systemTheme(prefersDark: boolean): string {
  return prefersDark ? "tokyo-night" : "catppuccin-latte";
}
