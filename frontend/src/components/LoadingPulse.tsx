import { motion } from "framer-motion";

interface LoadingPulseProps {
  label: string;
}

// A real, animated "an engine is actually training right now" state --
// three staggered pulsing dots on the accent gradient, not a static
// spinner, so the wait itself feels like part of the aesthetic rather
// than a dead moment.
export function LoadingPulse({ label }: LoadingPulseProps) {
  return (
    <div className="flex flex-col items-center gap-4 py-10">
      <div className="flex gap-2">
        {[0, 1, 2].map((index) => (
          <motion.span
            key={index}
            className="h-3 w-3 rounded-full bg-accent-gradient"
            animate={{ opacity: [0.3, 1, 0.3], scale: [0.8, 1.1, 0.8] }}
            transition={{
              duration: 1.1,
              repeat: Infinity,
              delay: index * 0.18,
              ease: "easeInOut",
            }}
          />
        ))}
      </div>
      <p className="text-sm text-slate-400">{label}</p>
    </div>
  );
}
