import { DataStateView } from "../components/DataStateView";
import { GlassCard } from "../components/GlassCard";
import { PageHeader } from "../components/PageHeader";
import { useDashboardData } from "../hooks/useDashboardData";

interface Transition {
  from_state: string | null;
  to_state: string;
  actor: string;
  at: string;
  reason: string;
  approved_by: string | null;
}

export function AuditTrail() {
  const state = useDashboardData<{ model_id: string; history: Transition[] }>("/audit-trail");

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Audit trail"
        description="A model registry's real state-transition history."
      />
      <DataStateView state={state}>
        {(data) => (
          <GlassCard className="overflow-hidden">
            <div className="border-b border-white/10 px-4 py-3 text-sm text-slate-400">
              Model: <span className="text-slate-100">{data.model_id}</span>
            </div>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-xs uppercase tracking-wider text-slate-500">
                  <th className="px-4 py-3">State</th>
                  <th className="px-4 py-3">Actor</th>
                  <th className="px-4 py-3">Date</th>
                  <th className="px-4 py-3">Reason</th>
                </tr>
              </thead>
              <tbody>
                {data.history.map((t, i) => (
                  <tr key={i} className="border-b border-white/5 text-slate-300">
                    <td className="px-4 py-3">{t.to_state}</td>
                    <td className="px-4 py-3">{t.actor}</td>
                    <td className="px-4 py-3">{t.at}</td>
                    <td className="px-4 py-3">{t.reason}</td>
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
