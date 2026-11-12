import { useState } from "react";

import { GlassCard } from "../../components/GlassCard";
import { MetricStat } from "../../components/MetricStat";
import { NumberField } from "../../components/NumberField";
import { PageHeader } from "../../components/PageHeader";
import { RunJobPanel } from "../../components/RunJobPanel";
import { StatusBadge } from "../../components/StatusBadge";
import { useJobPolling } from "../../hooks/useJobPolling";

interface RlHedgePayload {
  static_baseline_cvar: number;
  trained_final_cvar: number;
  verdict: "rl_better" | "static_better" | "inconclusive";
  n_parameters: number;
}

export function RlHedgeLab() {
  const { state, submit } = useJobPolling("rl_hedge");
  const [nEpochs, setNEpochs] = useState(40);
  const [seed, setSeed] = useState(0);

  const payload = state.phase === "done" ? (state.artifact.rl_hedge as RlHedgePayload) : null;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="RL hedging"
        description="A REINFORCE-trained hedging policy, risk-bounded against a static delta-hedge-with-no-trade-band baseline's own CVaR, computed on the same simulated GBM paths."
      />
      <RunJobPanel
        state={state}
        onRun={() => submit({ seed, n_epochs: nEpochs, s0: 100.0, mu: 0.05, sigma: 0.2, maturity: 1.0, n_steps: 20, n_paths: 2000, strike: 100.0, option_type: "call", risk_free_rate: 0.03, cost_rate: 0.001, initial_premium: 5.0, cvar_alpha: 0.95, learning_rate: 0.01, band_width: 0.05 })}
        configFields={
          <>
            <NumberField label="Seed" value={seed} onChange={setSeed} min={0} />
            <NumberField label="Epochs" value={nEpochs} onChange={setNEpochs} step={5} min={1} />
          </>
        }
      />
      {payload && (
        <>
          <div className="grid grid-cols-2 gap-4">
            <MetricStat label="Static baseline CVaR" value={payload.static_baseline_cvar.toFixed(3)} />
            <MetricStat
              label="RL policy CVaR"
              value={payload.trained_final_cvar.toFixed(3)}
              tone={payload.trained_final_cvar < payload.static_baseline_cvar ? "good" : "bad"}
            />
          </div>
          <GlassCard className="p-6">
            <p className="text-sm font-medium text-slate-300">Verdict</p>
            <div className="mt-2">
              <StatusBadge
                label={payload.verdict.replace("_", " ")}
                tone={payload.verdict === "rl_better" ? "good" : payload.verdict === "static_better" ? "bad" : "neutral"}
              />
            </div>
            <p className="mt-3 text-sm text-slate-400">Lower CVaR (tail loss) is better.</p>
          </GlassCard>
        </>
      )}
    </div>
  );
}
