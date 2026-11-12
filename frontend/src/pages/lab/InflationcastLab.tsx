import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { GlassCard } from "../../components/GlassCard";
import { MetricStat } from "../../components/MetricStat";
import { NumberField } from "../../components/NumberField";
import { PageHeader } from "../../components/PageHeader";
import { RunJobPanel } from "../../components/RunJobPanel";
import { StatusBadge } from "../../components/StatusBadge";
import { useJobPolling } from "../../hooks/useJobPolling";

interface CandidateMetrics {
  mae: number;
  rmse: number;
  mase: number;
  n_parameters: number;
  train_seconds: number;
  selected_epoch: number | null;
}

interface InflationcastPayload {
  dataset: { n_train: number; n_validation: number; n_test: number };
  models: Record<string, CandidateMetrics>;
  best_point_challenger: string;
  gru_calibration: {
    n_observations: number;
    nominal_coverage: number;
    observed_coverage: number;
    p_value: number;
  };
  gru_vs_best_classical: {
    point_estimate: number;
    ci_low: number;
    ci_high: number;
    excludes_zero: boolean;
  };
  verdict: "gru_better" | "classical_better" | "inconclusive";
}

export function InflationcastLab() {
  const { state, submit } = useJobPolling("inflationcast");
  const [maxEpochs, setMaxEpochs] = useState(150);
  const [seed, setSeed] = useState(0);

  const payload =
    state.phase === "done" ? (state.artifact.inflationcast as InflationcastPayload) : null;
  const bars = payload
    ? Object.entries(payload.models).map(([name, m]) => ({ name, mae: m.mae }))
    : [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="INFLATIONCAST"
        description="CPI nowcasting: naive persistence vs. linear regression vs. classical MLP vs. hybrid quantum vs. a calibrated GRU, on real BLS CPI-U + Kaggle macro data."
      />
      <RunJobPanel
        state={state}
        onRun={() =>
          submit({
            seed,
            max_epochs: maxEpochs,
            patience: 15,
            window: 6,
            validation_split_date: "2019-01-01",
            test_split_date: "2022-01-01",
            bootstrap_resamples: 300,
            calibration_coverage: 0.9,
          })
        }
        configFields={
          <>
            <NumberField label="Seed" value={seed} onChange={setSeed} min={0} />
            <NumberField label="Max epochs" value={maxEpochs} onChange={setMaxEpochs} step={10} min={1} />
          </>
        }
      />
      {payload && (
        <>
          <GlassCard className="p-6">
            <p className="mb-4 text-sm font-medium text-slate-300">MAE by candidate (lower is better)</p>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={bars} layout="vertical" margin={{ left: 24 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis type="number" stroke="#64748b" fontSize={12} />
                <YAxis dataKey="name" type="category" stroke="#64748b" fontSize={12} width={140} />
                <Tooltip
                  contentStyle={{ background: "#12151c", border: "1px solid rgba(255,255,255,0.1)" }}
                />
                <Bar dataKey="mae" fill="#8b5cf6" radius={[0, 6, 6, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </GlassCard>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <MetricStat label="Best candidate" value={payload.best_point_challenger} />
            <MetricStat
              label="GRU observed coverage"
              value={`${(payload.gru_calibration.observed_coverage * 100).toFixed(1)}%`}
              tone={payload.gru_calibration.observed_coverage < 0.7 ? "bad" : "good"}
            />
            <MetricStat
              label="Nominal coverage"
              value={`${(payload.gru_calibration.nominal_coverage * 100).toFixed(0)}%`}
            />
            <MetricStat label="p-value" value={payload.gru_calibration.p_value.toExponential(2)} />
          </div>
          <GlassCard className="p-6">
            <p className="text-sm font-medium text-slate-300">Verdict</p>
            <div className="mt-2">
              <StatusBadge
                label={payload.verdict.replace("_", " ")}
                tone={payload.verdict === "gru_better" ? "good" : "bad"}
              />
            </div>
            <p className="mt-3 text-sm text-slate-400">
              95% CI for the mean squared-error difference: [{payload.gru_vs_best_classical.ci_low.toFixed(3)},{" "}
              {payload.gru_vs_best_classical.ci_high.toFixed(3)}]
            </p>
          </GlassCard>
        </>
      )}
    </div>
  );
}
