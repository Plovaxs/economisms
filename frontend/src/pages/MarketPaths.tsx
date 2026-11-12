import { useState } from "react";

import { DataStateView } from "../components/DataStateView";
import { GlassCard } from "../components/GlassCard";
import { MetricStat } from "../components/MetricStat";
import { NumberField } from "../components/NumberField";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { useDashboardData } from "../hooks/useDashboardData";

interface MarketPathsPayload {
  p5: number;
  p50: number;
  p95: number;
  n_paths: number;
}

export function MarketPaths() {
  const [sigma, setSigma] = useState(0.2);
  const [nPaths, setNPaths] = useState(2000);
  const state = useDashboardData<MarketPathsPayload>(
    `/market-paths?sigma=${sigma}&n_paths=${nPaths}`,
    [sigma, nPaths],
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Market paths"
        description="Simulated GBM paths and the terminal-value distribution's real 5th/50th/95th percentiles."
      />
      <GlassCard className="p-6">
        <div className="mb-2">
          <StatusBadge label="synthetic" tone="neutral" />
        </div>
        <div className="flex gap-4">
          <NumberField label="Volatility" value={sigma} onChange={setSigma} step={0.01} min={0.01} />
          <NumberField label="Paths" value={nPaths} onChange={setNPaths} step={500} min={100} />
        </div>
      </GlassCard>
      <DataStateView state={state}>
        {(data) => (
          <div className="grid grid-cols-3 gap-4">
            <MetricStat label="5th percentile" value={data.p5.toFixed(2)} />
            <MetricStat label="Median" value={data.p50.toFixed(2)} />
            <MetricStat label="95th percentile" value={data.p95.toFixed(2)} />
          </div>
        )}
      </DataStateView>
    </div>
  );
}
