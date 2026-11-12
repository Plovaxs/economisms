interface StatusBadgeProps {
  label: string;
  tone: "neutral" | "good" | "bad" | "pending";
}

const TONE_CLASSES: Record<StatusBadgeProps["tone"], string> = {
  neutral: "bg-white/10 text-slate-200",
  good: "bg-emerald-500/15 text-emerald-300 border-emerald-400/30",
  bad: "bg-rose-500/15 text-rose-300 border-rose-400/30",
  pending: "bg-amber-500/15 text-amber-300 border-amber-400/30",
};

export function StatusBadge({ label, tone }: StatusBadgeProps) {
  return (
    <span
      className={`inline-flex items-center gap-1.5 rounded-full border border-white/10 px-3 py-1 text-xs font-medium ${TONE_CLASSES[tone]}`}
    >
      <span className="h-1.5 w-1.5 rounded-full bg-current" />
      {label}
    </span>
  );
}
