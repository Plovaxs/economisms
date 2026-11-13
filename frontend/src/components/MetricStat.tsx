interface MetricStatProps {
  label: string;
  value: string;
  tone?: "default" | "good" | "bad";
}

const TONE_CLASSES: Record<NonNullable<MetricStatProps["tone"]>, string> = {
  default: "text-slate-100",
  good: "text-emerald-300",
  bad: "text-rose-300",
};

export function MetricStat({ label, value, tone = "default" }: MetricStatProps) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/5 px-4 py-3 transition-colors duration-200 hover:border-white/20 hover:bg-white/[0.07]">
      <p className="text-xs uppercase tracking-wider text-slate-500">{label}</p>
      <p className={`mt-1 font-mono text-xl font-semibold ${TONE_CLASSES[tone]}`}>{value}</p>
    </div>
  );
}
