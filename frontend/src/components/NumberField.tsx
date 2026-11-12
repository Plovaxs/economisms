interface NumberFieldProps {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: number;
  min?: number;
}

export function NumberField({ label, value, onChange, step = 1, min }: NumberFieldProps) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-slate-400">{label}</span>
      <input
        type="number"
        value={value}
        step={step}
        min={min}
        onChange={(event) => onChange(Number(event.target.value))}
        className="rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-slate-100 focus:border-accent-violet focus:outline-none"
      />
    </label>
  );
}
