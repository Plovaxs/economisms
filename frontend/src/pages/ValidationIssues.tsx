import { DataStateView } from "../components/DataStateView";
import { GlassCard } from "../components/GlassCard";
import { PageHeader } from "../components/PageHeader";
import { useDashboardData } from "../hooks/useDashboardData";

interface Finding {
  finding_id: string;
  component_id: string;
  severity: string;
  owner: string;
  expiry_date: string;
  disposition: string;
}

export function ValidationIssues() {
  const state = useDashboardData<{ findings: Finding[] }>("/validation-issues");

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Validation issues" description="The real tracked findings log." />
      <DataStateView state={state}>
        {(data) => (
          <GlassCard className="overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-xs uppercase tracking-wider text-slate-500">
                  <th className="px-4 py-3">ID</th>
                  <th className="px-4 py-3">Component</th>
                  <th className="px-4 py-3">Severity</th>
                  <th className="px-4 py-3">Owner</th>
                  <th className="px-4 py-3">Disposition</th>
                </tr>
              </thead>
              <tbody>
                {data.findings.map((f) => (
                  <tr key={f.finding_id} className="border-b border-white/5 text-slate-300">
                    <td className="px-4 py-3">{f.finding_id}</td>
                    <td className="px-4 py-3">{f.component_id}</td>
                    <td className="px-4 py-3">{f.severity}</td>
                    <td className="px-4 py-3">{f.owner}</td>
                    <td className="px-4 py-3">{f.disposition}</td>
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
