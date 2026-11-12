import { useState } from "react";

import { DataStateView } from "../components/DataStateView";
import { GlassCard } from "../components/GlassCard";
import { MetricStat } from "../components/MetricStat";
import { NumberField } from "../components/NumberField";
import { PageHeader } from "../components/PageHeader";
import { useDashboardData } from "../hooks/useDashboardData";

interface PricingPayload {
  price: number;
  delta: number;
  gamma: number;
  vega: number;
  theta: number;
  rho: number;
  pricing_method: string;
  as_of: string;
}

export function PricingDiagnostics() {
  const [strike, setStrike] = useState(100);
  const [volatility, setVolatility] = useState(0.2);
  const state = useDashboardData<PricingPayload>(
    `/pricing?strike=${strike}&volatility=${volatility}`,
    [strike, volatility],
  );

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Pricing diagnostics"
        description="A real closed-form Black-Scholes price and Greeks."
      />
      <GlassCard className="p-6">
        <div className="flex gap-4">
          <NumberField label="Strike" value={strike} onChange={setStrike} min={1} />
          <NumberField label="Volatility" value={volatility} onChange={setVolatility} step={0.01} min={0.01} />
        </div>
      </GlassCard>
      <DataStateView state={state}>
        {(data) => (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <MetricStat label="Price" value={data.price.toFixed(4)} />
            <MetricStat label="Delta" value={data.delta.toFixed(4)} />
            <MetricStat label="Gamma" value={data.gamma.toFixed(4)} />
            <MetricStat label="Vega" value={data.vega.toFixed(4)} />
            <MetricStat label="Theta" value={data.theta.toFixed(4)} />
            <MetricStat label="Rho" value={data.rho.toFixed(4)} />
          </div>
        )}
      </DataStateView>
    </div>
  );
}
