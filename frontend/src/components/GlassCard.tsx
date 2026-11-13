import { motion } from "framer-motion";
import type { ReactNode } from "react";

interface GlassCardProps {
  children: ReactNode;
  className?: string;
  delay?: number;
}

// The one reusable "glass" surface every page composes -- a translucent,
// blurred panel with a soft border, the Hyprland/omarchy-style look the
// whole frontend is built around. Fades/lifts in on mount; respects
// prefers-reduced-motion globally via styles/tokens.css.
export function GlassCard({ children, className = "", delay = 0 }: GlassCardProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay, ease: "easeOut" }}
      className={`relative rounded-2xl border border-white/10 bg-white/5 backdrop-blur-xl shadow-glass before:pointer-events-none before:absolute before:inset-x-0 before:top-0 before:h-px before:rounded-t-2xl before:bg-gradient-to-r before:from-transparent before:via-white/40 before:to-transparent ${className}`}
    >
      {children}
    </motion.div>
  );
}
