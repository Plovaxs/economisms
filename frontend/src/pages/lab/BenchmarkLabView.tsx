import type { ReactNode } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { GlassCard } from "../../components/GlassCard";
import { MetricStat } from "../../components/MetricStat";
import { RunJobPanel } from "../../components/RunJobPanel";
import { StatusBadge } from "../../components/StatusBadge";
import type { LabState } from "../../hooks/useJobPolling";
import { useChartTheme } from "../../settings/useSettings";

// Shared envelope across qmacro_run.py::_summary_payload and
// recessionnet_run.py::summary_payload: both already produce
// best_classical_challenger/quantum_vs_best_classical/verdict, but
// their per-model metric fields differ (Q-MACRO is a regression task:
// mae/rmse/mase; RECESSIONNET is classification: brier_score/roc_auc/
// calibration_slope/calibration_intercept) -- so this view stays
// generic over `metricField` rather than assuming one shape for both.
export interface BenchmarkPayload {
  dataset: Record<string, unknown>;
  models: Record<string, Record<string, number | null>>;
  best_classical_challenger: string;
  quantum_vs_best_classical: {
    point_estimate: number;
    ci_low: number;
    ci_high: number;
    excludes_zero: boolean;
  };
  verdict: "quantum_better" | "classical_better" | "inconclusive";
}

interface BenchmarkLabViewProps {
  state: LabState;
  onRun: () => void;
  configFields: ReactNode;
  payloadKey: string;
  metricField: string;
  metricLabel: string;
}

export function BenchmarkLabView({
  state,
  onRun,
  configFields,
  payloadKey,
  metricField,
  metricLabel,
}: BenchmarkLabViewProps) {
  const chart = useChartTheme();
  const payload =
    state.phase === "done" ? (state.artifact[payloadKey] as BenchmarkPayload | undefined) : undefined;
  const bars = payload
    ? Object.entries(payload.models).map(([name, m]) => ({ name, value: m[metricField] ?? 0 }))
    : [];

  return (
    <div className="flex flex-col gap-6">
      <RunJobPanel state={state} onRun={onRun} configFields={configFields} />
      {payload && (
        <>
          <GlassCard className="p-6">
            <p className="mb-4 text-sm font-medium text-slate-300">
              {metricLabel} by candidate (lower is better)
            </p>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={bars} layout="vertical" margin={{ left: 24 }}>
                <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
                <XAxis type="number" stroke={chart.axis} fontSize={12} />
                <YAxis dataKey="name" type="category" stroke={chart.axis} fontSize={12} width={160} />
                <Tooltip contentStyle={{ background: chart.tooltipBackground, border: `1px solid ${chart.tooltipBorder}`, color: chart.ink }} />
                <Bar dataKey="value" fill={chart.series[1]} radius={[0, 6, 6, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </GlassCard>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <MetricStat label="Best classical challenger" value={payload.best_classical_challenger} />
            <MetricStat
              label="Quantum CI"
              value={`[${payload.quantum_vs_best_classical.ci_low.toFixed(3)}, ${payload.quantum_vs_best_classical.ci_high.toFixed(3)}]`}
            />
            <MetricStat
              label="CI excludes zero"
              value={payload.quantum_vs_best_classical.excludes_zero ? "yes" : "no"}
              tone={payload.quantum_vs_best_classical.excludes_zero ? "good" : "default"}
            />
          </div>
          <GlassCard className="p-6">
            <p className="text-sm font-medium text-slate-300">Verdict</p>
            <div className="mt-2">
              <StatusBadge
                label={payload.verdict.replace("_", " ")}
                tone={
                  payload.verdict === "quantum_better"
                    ? "good"
                    : payload.verdict === "classical_better"
                      ? "bad"
                      : "neutral"
                }
              />
            </div>
          </GlassCard>
        </>
      )}
    </div>
  );
}
