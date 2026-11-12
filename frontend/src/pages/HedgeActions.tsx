import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { DataStateView } from "../components/DataStateView";
import { GlassCard } from "../components/GlassCard";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { useDashboardData } from "../hooks/useDashboardData";

interface HedgeActionsPayload {
  ratios_path_0: number[];
}

export function HedgeActions() {
  const state = useDashboardData<HedgeActionsPayload>("/hedge-actions");

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Hedge actions"
        description="Delta-hedge ratio by step for a single simulated path, computed from information available at that step only."
      />
      <div>
        <StatusBadge label="synthetic" tone="neutral" />
      </div>
      <DataStateView state={state}>
        {(data) => (
          <GlassCard className="p-6">
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={data.ratios_path_0.map((ratio, step) => ({ step, ratio }))}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="step" stroke="#64748b" fontSize={12} />
                <YAxis stroke="#64748b" fontSize={12} />
                <Tooltip contentStyle={{ background: "#12151c", border: "1px solid rgba(255,255,255,0.1)" }} />
                <Line type="stepAfter" dataKey="ratio" stroke="#22d3ee" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </GlassCard>
        )}
      </DataStateView>
    </div>
  );
}
