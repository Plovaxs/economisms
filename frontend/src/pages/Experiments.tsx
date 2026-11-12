import { DataStateView } from "../components/DataStateView";
import { GlassCard } from "../components/GlassCard";
import { PageHeader } from "../components/PageHeader";
import { useDashboardData } from "../hooks/useDashboardData";

interface ExperimentRow {
  experiment: string;
  metric_name: string;
  champion_value: string;
  challenger_value: string;
  verdict: string;
  source_pr: string;
}

export function Experiments() {
  const state = useDashboardData<{ rows: ExperimentRow[] }>("/experiments");

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Experiment comparison"
        description="Every real comparison this project has run, including every null/negative result."
      />
      <DataStateView state={state}>
        {(data) => (
          <GlassCard className="overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-xs uppercase tracking-wider text-slate-500">
                  <th className="px-4 py-3">Experiment</th>
                  <th className="px-4 py-3">Metric</th>
                  <th className="px-4 py-3">Champion</th>
                  <th className="px-4 py-3">Challenger</th>
                  <th className="px-4 py-3">Verdict</th>
                </tr>
              </thead>
              <tbody>
                {data.rows.map((row) => (
                  <tr key={row.experiment} className="border-b border-white/5 text-slate-300">
                    <td className="px-4 py-3">{row.experiment}</td>
                    <td className="px-4 py-3">{row.metric_name}</td>
                    <td className="px-4 py-3">{row.champion_value}</td>
                    <td className="px-4 py-3">{row.challenger_value}</td>
                    <td className="px-4 py-3">{row.verdict}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </GlassCard>
        )}
      </DataStateView>
    </div>
  );
}
