import { useState } from "react";

import { GlassCard } from "../../components/GlassCard";
import { MetricStat } from "../../components/MetricStat";
import { NumberField } from "../../components/NumberField";
import { PageHeader } from "../../components/PageHeader";
import { RunJobPanel } from "../../components/RunJobPanel";
import { useJobPolling } from "../../hooks/useJobPolling";

interface NeuralSdePayload {
  n_months: number;
  n_train_examples: number;
  n_validation_examples: number;
  n_covid_examples: number;
  selected_epoch: number;
  best_validation_nll: number;
  n_parameters: number;
  benchmark_report: {
    candidate_names: string[];
    log_score: Record<string, number>;
    // One dimension's CRPS per key, plus a `mean_crps` summary --
    // not a flat number per candidate.
    crps: Record<string, { mean_crps: number }>;
  };
}

export function NeuralSdeLab() {
  const { state, submit } = useJobPolling("neural_sde");
  const [seed, setSeed] = useState(0);
  const [maxEpochs, setMaxEpochs] = useState(300);

  const payload = state.phase === "done" ? (state.artifact.neural_sde as NeuralSdePayload) : null;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Neural SDE"
        description="A neural stochastic differential equation trained on real macro data, benchmarked against classical baselines with proper scoring rules, including a genuine out-of-distribution shock window (the 2020 COVID window)."
      />
      <RunJobPanel
        state={state}
        onRun={() => submit({ seed, max_epochs: maxEpochs, patience: 20 })}
        configFields={
          <>
            <NumberField label="Seed" value={seed} onChange={setSeed} min={0} />
            <NumberField label="Max epochs" value={maxEpochs} onChange={setMaxEpochs} step={10} min={1} />
          </>
        }
      />
      {payload && (
        <>
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <MetricStat label="Train examples" value={String(payload.n_train_examples)} />
            <MetricStat label="Validation examples" value={String(payload.n_validation_examples)} />
            <MetricStat label="COVID OOD examples" value={String(payload.n_covid_examples)} />
            <MetricStat label="Selected epoch" value={String(payload.selected_epoch)} />
          </div>
          <GlassCard className="p-6">
            <p className="mb-3 text-sm font-medium text-slate-300">Log-score by candidate (lower is better)</p>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              {Object.entries(payload.benchmark_report.log_score).map(([name, value]) => (
                <MetricStat key={name} label={name} value={value.toFixed(3)} />
              ))}
            </div>
          </GlassCard>
          <GlassCard className="p-6">
            <p className="mb-3 text-sm font-medium text-slate-300">CRPS by candidate (lower is better)</p>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
              {Object.entries(payload.benchmark_report.crps).map(([name, value]) => (
                <MetricStat key={name} label={name} value={value.mean_crps.toFixed(3)} />
              ))}
            </div>
          </GlassCard>
        </>
      )}
    </div>
  );
}
