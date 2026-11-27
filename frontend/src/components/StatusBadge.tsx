interface StatusBadgeProps {
  label: string;
  tone: "neutral" | "good" | "bad" | "pending";
}

const TONE_CLASSES: Record<StatusBadgeProps["tone"], string> = {
  neutral: "bg-white/10 text-slate-200",
  good: "bg-good/15 text-good border-good/30",
  bad: "bg-bad/15 text-bad border-bad/30",
  pending: "bg-warn/15 text-warn border-warn/30",
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
