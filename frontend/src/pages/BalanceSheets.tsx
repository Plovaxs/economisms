import { useState } from "react";

import { DataStateView } from "../components/DataStateView";
import { GlassCard } from "../components/GlassCard";
import { MetricStat } from "../components/MetricStat";
import { PageHeader } from "../components/PageHeader";
import { useDashboardData } from "../hooks/useDashboardData";

interface Money {
  minor_units: number;
  currency: string;
}

interface BalanceSheetEntry {
  account_id: string;
  account_type: string;
  balance_minor_units: number;
  currency: string;
}

interface BalanceSheetPayload {
  sector: string;
  assets: Money;
  liabilities: Money;
  equity: Money;
  residual: Money;
  reconciled: boolean;
  entries: BalanceSheetEntry[];
}

function formatMoney(money: Money): string {
  return `${(money.minor_units / 100).toFixed(2)} ${money.currency}`;
}

export function BalanceSheets() {
  const [owner, setOwner] = useState("alice");
  const state = useDashboardData<BalanceSheetPayload>(`/portfolio/${owner}`, [owner]);

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Balance sheets"
        description="A real, owner-scoped portfolio -- only reachable with a token authorized for this owner."
      />
      <GlassCard className="p-6">
        <label className="flex flex-col gap-1 text-sm">
          <span className="text-slate-400">Owner</span>
          <input
            value={owner}
            onChange={(e) => setOwner(e.target.value)}
            className="w-48 rounded-lg border border-white/10 bg-white/5 px-3 py-1.5 text-slate-100 focus:border-accent-violet focus:outline-none"
          />
        </label>
      </GlassCard>
      <DataStateView state={state}>
        {(data) => (
          <>
            <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
              <MetricStat label="Assets" value={formatMoney(data.assets)} />
              <MetricStat label="Liabilities" value={formatMoney(data.liabilities)} />
              <MetricStat label="Equity" value={formatMoney(data.equity)} />
              <MetricStat
                label="Reconciled"
                value={data.reconciled ? "yes" : "no"}
                tone={data.reconciled ? "good" : "bad"}
              />
            </div>
            <GlassCard className="overflow-hidden">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-white/10 text-left text-xs uppercase tracking-wider text-slate-500">
                    <th className="px-4 py-3">Account</th>
                    <th className="px-4 py-3">Type</th>
                    <th className="px-4 py-3">Balance</th>
                  </tr>
                </thead>
                <tbody>
                  {data.entries.map((entry) => (
                    <tr key={entry.account_id} className="border-b border-white/5 text-slate-300">
                      <td className="px-4 py-3">{entry.account_id}</td>
                      <td className="px-4 py-3">{entry.account_type}</td>
                      <td className="px-4 py-3">
                        {(entry.balance_minor_units / 100).toFixed(2)} {entry.currency}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </GlassCard>
          </>
        )}
      </DataStateView>
    </div>
  );
}
