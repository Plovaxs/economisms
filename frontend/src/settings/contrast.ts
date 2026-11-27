// Colour arithmetic shared by the theme engine and the tests that hold every theme to WCAG.
// Colours are `[r, g, b]` triplets in 0..255, the same shape the CSS variables carry.

export type Rgb = readonly [number, number, number];

export function toLinear(channel: number): number {
  const c = channel / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance([r, g, b]: Rgb): number {
  return 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
}

/** WCAG 2.x contrast ratio, 1 to 21. */
export function contrastRatio(a: Rgb, b: Rgb): number {
  const la = luminance(a);
  const lb = luminance(b);
  const [hi, lo] = la >= lb ? [la, lb] : [lb, la];
  return (hi + 0.05) / (lo + 0.05);
}

/** Linear mix in sRGB: t = 0 gives `from`, t = 1 gives `to`. */
export function mix(from: Rgb, to: Rgb, t: number): Rgb {
  const m = (x: number, y: number) => Math.round(x + (y - x) * t);
  return [m(from[0], to[0]), m(from[1], to[1]), m(from[2], to[2])];
}

export function cssTriplet(c: Rgb): string {
  return `${c[0]} ${c[1]} ${c[2]}`;
}

export function hex(c: Rgb): string {
  return `#${c.map((x) => Math.max(0, Math.min(255, x)).toString(16).padStart(2, "0")).join("")}`;
}

/** The colour (of the two candidates) with the higher contrast against `background`. */
export function bestInk(background: Rgb, light: Rgb, dark: Rgb): Rgb {
  return contrastRatio(background, light) >= contrastRatio(background, dark) ? light : dark;
}
