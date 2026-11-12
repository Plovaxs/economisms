import { DataStateView } from "../components/DataStateView";
import { MetricStat } from "../components/MetricStat";
import { PageHeader } from "../components/PageHeader";
import { StatusBadge } from "../components/StatusBadge";
import { useDashboardData } from "../hooks/useDashboardData";

interface PortfolioRiskPayload {
  alpha: number;
  horizon_label: string;
  var: number;
  es: number;
  drawdown: number;
}

export function PortfolioRisk() {
  const state = useDashboardData<PortfolioRiskPayload>("/portfolio-risk");

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Portfolio risk"
        description="Real historical VaR/ES and max drawdown over a P&L series."
      />
      <div>
        <StatusBadge label="synthetic" tone="neutral" />
      </div>
      <DataStateView state={state}>
        {(data) => (
          <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <MetricStat label={`VaR (${(data.alpha * 100).toFixed(0)}%)`} value={data.var.toFixed(2)} />
            <MetricStat label="Expected shortfall" value={data.es.toFixed(2)} />
            <MetricStat label="Max drawdown" value={data.drawdown.toFixed(2)} />
          </div>
        )}
      </DataStateView>
    </div>
  );
}
