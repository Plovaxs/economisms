import { useState } from "react";
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { DataStateView } from "../components/DataStateView";
import { GlassCard } from "../components/GlassCard";
import { NumberField } from "../components/NumberField";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { useDashboardData } from "../hooks/useDashboardData";

interface EconomyStepRow {
  step: number;
  ledger_total_usd: number;
  n_shocks: number;
}

interface EconomyExplorerPayload {
  steps: EconomyStepRow[];
  shocks: { shock_id: string; step: number; kind: string; magnitude: number }[];
}

export function EconomyExplorer() {
  const [nSteps, setNSteps] = useState(6);
  const [seed, setSeed] = useState(0);
  const state = useDashboardData<EconomyExplorerPayload>(
    `/economy?n_steps=${nSteps}&seed=${seed}`,
    [nSteps, seed],
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Economy explorer"
        description="A real household+firm economy, stepped forward with real posted ledger transactions and real drawn macro shocks."
      />
      <GlassCard className="p-6">
        <div className="mb-2">
          <StatusBadge label="synthetic" tone="neutral" />
        </div>
        <div className="flex gap-4">
          <NumberField label="Steps" value={nSteps} onChange={setNSteps} min={1} />
          <NumberField label="Seed" value={seed} onChange={setSeed} min={0} />
        </div>
      </GlassCard>
      <DataStateView state={state}>
        {(data) => (
          <GlassCard className="p-6">
            <p className="mb-4 text-sm font-medium text-slate-300">Aggregate ledger balance by step</p>
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={data.steps}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="step" stroke="#64748b" fontSize={12} />
                <YAxis stroke="#64748b" fontSize={12} />
                <Tooltip contentStyle={{ background: "#12151c", border: "1px solid rgba(255,255,255,0.1)" }} />
                <Line type="monotone" dataKey="ledger_total_usd" stroke="#8b5cf6" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </GlassCard>
        )}
      </DataStateView>
    </div>
  );
}
