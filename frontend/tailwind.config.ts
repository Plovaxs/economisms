import type { Config } from "tailwindcss";

// Hyprland/omarchy-style glass aesthetic. Every colour is a CSS variable holding an "r g b"
// triplet, set on the document element by the theme engine (src/settings), so one class such as
// `text-slate-300` or `bg-white/5` re-colours itself under all twelve themes -- and, in the
// light ones, "white" is the ink and the slate scale runs dark to light. The defaults in
// styles/tokens.css are the Aurora theme, so the first paint is right before any script runs.
const v = (name: string) => `rgb(var(${name}) / <alpha-value>)`;

const scale = (n: number, unit: string, variable: string) =>
  `calc(${n * 0.25}${unit} * var(${variable}))`;

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        white: v("--overlay"),
        slate: {
          50: v("--slate-50"),
          100: v("--slate-100"),
          200: v("--slate-200"),
          300: v("--slate-300"),
          400: v("--slate-400"),
          500: v("--slate-500"),
          600: v("--slate-600"),
          700: v("--slate-700"),
          800: v("--slate-800"),
          900: v("--slate-900"),
          950: v("--slate-950"),
        },
        base: {
          DEFAULT: v("--c-base"),
          elevated: v("--c-elevated"),
          panel: v("--c-panel"),
        },
        accent: {
          a: v("--accent-a"),
          b: v("--accent-b"),
          c: v("--accent-c"),
        },
        good: v("--good"),
        bad: v("--bad"),
        warn: v("--warn"),
        "on-accent": v("--on-accent"),
      },
      backgroundImage: {
        "accent-gradient":
          "linear-gradient(135deg, rgb(var(--accent-a)) 0%, rgb(var(--accent-b)) 55%, rgb(var(--accent-c)) 100%)",
        "accent-gradient-soft":
          "linear-gradient(135deg, rgb(var(--accent-a) / 0.18) 0%, rgb(var(--accent-b) / 0.14) 50%, rgb(var(--accent-c) / 0.18) 100%)",
      },
      boxShadow: {
        glass: "0 8px 32px 0 rgb(var(--shadow-ink) / 0.45)",
        glow: "0 0 24px 0 rgb(var(--accent-a) / 0.25)",
      },
      // The "radius" setting scales every rounded corner (sharp 0, soft 1, round 1.6).
      borderRadius: {
        md: "calc(0.375rem * var(--r, 1))",
        lg: "calc(0.5rem * var(--r, 1))",
        xl: "calc(0.75rem * var(--r, 1))",
        "2xl": "calc(1.1rem * var(--r, 1))",
        "3xl": "calc(1.6rem * var(--r, 1))",
      },
      // The "gaps" setting scales the gaps between panels; "density" scales their padding.
      gap: Object.fromEntries([1, 2, 3, 4, 5, 6, 8].map((n) => [n, scale(n, "rem", "--gs")])),
      padding: Object.fromEntries([2, 3, 4, 5, 6, 8].map((n) => [n, scale(n, "rem", "--ds")])),
    },
  },
  plugins: [],
} satisfies Config;
