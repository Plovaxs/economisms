import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { GlassCard } from "../../components/GlassCard";
import { NumberField } from "../../components/NumberField";
import { PageHeader } from "../../components/PageHeader";
import { RunJobPanel } from "../../components/RunJobPanel";
import { StatusBadge } from "../../components/StatusBadge";
import { useJobPolling } from "../../hooks/useJobPolling";

interface SeedOutcome {
  seed: number;
  household_utility: number;
  firm_profit: number;
}

interface MarlPayload {
  single_agent: SeedOutcome[];
  co_learning: SeedOutcome[];
  mean_household_utility_delta: number;
  verdict: "co_learning_better" | "single_agent_better";
}

export function MarlLab() {
  const { state, submit } = useJobPolling("marl");
  const [seed, setSeed] = useState(0);
  const [nEpochs, setNEpochs] = useState(30);

  const payload = state.phase === "done" ? (state.artifact.marl as MarlPayload) : null;
  const bars = payload
    ? payload.single_agent.map((single, i) => ({
        seed: single.seed,
        "single-agent": single.household_utility,
        "co-learning": payload.co_learning[i]?.household_utility ?? 0,
      }))
    : [];

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Multi-agent RL"
        description="A PPO-trained household policy, benchmarked against the same household trained alone against a fixed-rule firm -- single-agent vs. co-learning household utility, across seeds."
      />
      <RunJobPanel
        state={state}
        onRun={() =>
          submit({
            seed,
            n_epochs: nEpochs,
            episodes_per_epoch: 8,
            n_steps: 6,
            firm_opening_capital_minor_units: 100_000,
          })
        }
        configFields={
          <>
            <NumberField label="Seed" value={seed} onChange={setSeed} min={0} />
            <NumberField label="Epochs" value={nEpochs} onChange={setNEpochs} step={5} min={1} />
          </>
        }
      />
      {payload && (
        <>
          <GlassCard className="p-6">
            <p className="mb-4 text-sm font-medium text-slate-300">Household utility: single-agent vs. co-learning</p>
            <ResponsiveContainer width="100%" height={240}>
              <BarChart data={bars}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="seed" stroke="#64748b" fontSize={12} label={{ value: "seed", position: "insideBottom", offset: -5 }} />
                <YAxis stroke="#64748b" fontSize={12} />
                <Tooltip contentStyle={{ background: "#12151c", border: "1px solid rgba(255,255,255,0.1)" }} />
                <Legend />
                <Bar dataKey="single-agent" fill="#64748b" radius={[6, 6, 0, 0]} />
                <Bar dataKey="co-learning" fill="#8b5cf6" radius={[6, 6, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </GlassCard>
          <GlassCard className="p-6">
            <p className="text-sm font-medium text-slate-300">Verdict</p>
            <div className="mt-2">
              <StatusBadge
                label={payload.verdict.replace("_", " ")}
                tone={payload.verdict === "co_learning_better" ? "good" : "neutral"}
              />
            </div>
            <p className="mt-3 text-sm text-slate-400">
              Mean household-utility delta: {payload.mean_household_utility_delta.toFixed(3)}
            </p>
          </GlassCard>
        </>
      )}
    </div>
  );
}
