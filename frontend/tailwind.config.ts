import type { Config } from "tailwindcss";

// Hyprland/omarchy-style dark glass aesthetic: a near-black base, a
// violet-to-cyan accent gradient, and one reusable translucent "glass"
// surface token every card/panel composes (see components/GlassCard.tsx).
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "system-ui", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "monospace"],
      },
      colors: {
        base: {
          DEFAULT: "#0a0b10",
          elevated: "#12151c",
          panel: "#171b24",
        },
        accent: {
          violet: "#8b5cf6",
          fuchsia: "#d946ef",
          cyan: "#22d3ee",
        },
      },
      backgroundImage: {
        "accent-gradient": "linear-gradient(135deg, #8b5cf6 0%, #d946ef 55%, #22d3ee 100%)",
        "accent-gradient-soft": "linear-gradient(135deg, rgba(139,92,246,0.18) 0%, rgba(217,70,239,0.14) 50%, rgba(34,211,238,0.18) 100%)",
      },
      boxShadow: {
        glass: "0 8px 32px 0 rgba(0, 0, 0, 0.45)",
        glow: "0 0 24px 0 rgba(139, 92, 246, 0.25)",
      },
      borderRadius: {
        "2xl": "1.1rem",
        "3xl": "1.6rem",
      },
    },
  },
  plugins: [],
} satisfies Config;
