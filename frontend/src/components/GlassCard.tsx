import { motion } from "framer-motion";
import type { PointerEvent, ReactNode } from "react";

import { tiltFor } from "../three/tilt";

interface GlassCardProps {
  children: ReactNode;
  className?: string;
  delay?: number;
}

// The one reusable "glass" surface every page composes -- a translucent, blurred panel with a soft
// border, the Hyprland/omarchy-style look the whole frontend is built around. It fades/lifts in on
// mount; the settings can firm it up (reduced blur, fully solid, high contrast: see styles/tokens.css,
// which targets the `glass` class) and, if the person asks for it and motion is allowed, make it lean
// a few degrees toward the pointer. Reduced motion is honoured globally by the stylesheet.
export function GlassCard({ children, className = "", delay = 0 }: GlassCardProps) {
  const onMove = (event: PointerEvent<HTMLDivElement>) => {
    const root = document.documentElement;
    if (root.getAttribute("data-tilt") !== "on") return;
    const rect = event.currentTarget.getBoundingClientRect();
    const { x, y } = tiltFor(event.clientX - rect.left, event.clientY - rect.top, rect.width, rect.height);
    event.currentTarget.style.setProperty("--tilt-x", `${x}deg`);
    event.currentTarget.style.setProperty("--tilt-y", `${y}deg`);
  };
  const onLeave = (event: PointerEvent<HTMLDivElement>) => {
    event.currentTarget.style.setProperty("--tilt-x", "0deg");
    event.currentTarget.style.setProperty("--tilt-y", "0deg");
  };
  return (
    <motion.div
      initial={{ opacity: 0, y: 12 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.35, delay, ease: "easeOut" }}
      onPointerMove={onMove}
      onPointerLeave={onLeave}
      className={`glass relative rounded-2xl border border-white/10 bg-white/5 backdrop-blur-xl shadow-glass before:pointer-events-none before:absolute before:inset-x-0 before:top-0 before:h-px before:rounded-t-2xl before:bg-gradient-to-r before:from-transparent before:via-white/40 before:to-transparent ${className}`}
    >
      <div className="tilt-layer">{children}</div>
    </motion.div>
  );
}
