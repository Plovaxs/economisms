import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { DataStateView } from "../components/DataStateView";
import { GlassCard } from "../components/GlassCard";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { useDashboardData } from "../hooks/useDashboardData";
import { useChartTheme } from "../settings/useSettings";

interface HedgeActionsPayload {
  ratios_path_0: number[];
}

export function HedgeActions() {
  const chart = useChartTheme();
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
                <CartesianGrid strokeDasharray="3 3" stroke={chart.grid} />
                <XAxis dataKey="step" stroke={chart.axis} fontSize={12} />
                <YAxis stroke={chart.axis} fontSize={12} />
                <Tooltip contentStyle={{ background: chart.tooltipBackground, border: `1px solid ${chart.tooltipBorder}`, color: chart.ink }} />
                <Line type="stepAfter" dataKey="ratio" stroke={chart.series[1]} strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </GlassCard>
        )}
      </DataStateView>
    </div>
  );
}
