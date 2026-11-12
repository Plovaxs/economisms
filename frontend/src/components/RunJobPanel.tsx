import type { ReactNode } from "react";

import type { LabState } from "../hooks/useJobPolling";
import { GlassCard } from "./GlassCard";
import { LoadingPulse } from "./LoadingPulse";
import { StatusBadge } from "./StatusBadge";

interface RunJobPanelProps {
  state: LabState;
  onRun: () => void;
  configFields?: ReactNode;
  runLabel?: string;
}

export function RunJobPanel({ state, onRun, configFields, runLabel = "Run" }: RunJobPanelProps) {
  const busy = state.phase === "submitting" || state.phase === "polling";
  return (
    <GlassCard className="p-6">
      <div className="flex items-center justify-between">
        <div className="flex flex-wrap items-end gap-4">{configFields}</div>
        <button
          onClick={onRun}
          disabled={busy}
          className="shrink-0 rounded-xl bg-accent-gradient px-5 py-2.5 text-sm font-medium text-slate-950 transition-opacity hover:opacity-90 disabled:opacity-40"
        >
          {busy ? "Running..." : runLabel}
        </button>
      </div>
      {state.phase === "polling" && (
        <div className="mt-4 flex items-center gap-3">
          <StatusBadge label={state.job.status} tone="pending" />
          <span className="text-xs text-slate-500">job {state.job.job_id.slice(0, 8)}</span>
        </div>
      )}
      {busy && <LoadingPulse label="Training a real model on real data..." />}
      {state.phase === "error" && (
        <p className="mt-4 rounded-xl border border-rose-400/30 bg-rose-500/10 px-4 py-3 text-sm text-rose-300">
          {state.message}
        </p>
      )}
    </GlassCard>
  );
}
