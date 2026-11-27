import { useId, useRef } from "react";
import type { KeyboardEvent, ReactNode } from "react";

// The few form controls the settings use, built to the WAI-ARIA patterns they are named after:
// a radio group (one tab stop, arrows move and select) and a switch.

interface SegmentedProps<T extends string | number> {
  label: string;
  value: T;
  options: readonly { value: T; label: string; hint?: string }[];
  onChange: (value: T) => void;
}

export function Segmented<T extends string | number>({ label, value, options, onChange }: SegmentedProps<T>) {
  const id = useId();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const move = (from: number, step: number) => {
    const next = (from + step + options.length) % options.length;
    onChange(options[next].value);
    refs.current[next]?.focus();
  };
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key === "ArrowRight" || event.key === "ArrowDown") {
      event.preventDefault();
      move(index, 1);
    } else if (event.key === "ArrowLeft" || event.key === "ArrowUp") {
      event.preventDefault();
      move(index, -1);
    } else if (event.key === "Home") {
      event.preventDefault();
      move(0, 0);
    } else if (event.key === "End") {
      event.preventDefault();
      move(options.length - 1, 0);
    }
  };
  return (
    <div role="radiogroup" aria-labelledby={id} className="flex flex-col gap-2">
      <span id={id} className="text-sm font-medium text-slate-200">
        {label}
      </span>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o, index) => {
          const on = o.value === value;
          return (
            <button
              key={String(o.value)}
              ref={(el) => {
                refs.current[index] = el;
              }}
              type="button"
              role="radio"
              aria-checked={on}
              tabIndex={on ? 0 : -1}
              title={o.hint}
              onClick={() => onChange(o.value)}
              onKeyDown={(e) => onKeyDown(e, index)}
              className={`rounded-lg border px-3 py-1.5 text-sm transition-colors ${
                on
                  ? "border-accent-a bg-accent-a/20 text-slate-50"
                  : "border-white/10 bg-white/5 text-slate-300 hover:bg-white/10"
              }`}
            >
              {o.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

interface SwitchProps {
  label: string;
  description?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}

export function Switch({ label, description, checked, onChange }: SwitchProps) {
  const id = useId();
  return (
    <div className="flex items-start justify-between gap-4">
      <div>
        <span id={id} className="text-sm font-medium text-slate-200">
          {label}
        </span>
        {description && <p className="text-xs text-slate-400">{description}</p>}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-labelledby={id}
        onClick={() => onChange(!checked)}
        className={`relative mt-0.5 h-6 w-11 shrink-0 rounded-full border transition-colors ${
          checked ? "border-accent-a bg-accent-a/60" : "border-white/20 bg-white/10"
        }`}
      >
        <span
          aria-hidden="true"
          className={`absolute top-0.5 h-4 w-4 rounded-full bg-slate-50 transition-all ${
            checked ? "left-6" : "left-1"
          }`}
        />
        <span className="sr-only">{checked ? "on" : "off"}</span>
      </button>
    </div>
  );
}

export function Field({ children }: { children: ReactNode }) {
  return <div className="flex flex-col gap-4">{children}</div>;
}
