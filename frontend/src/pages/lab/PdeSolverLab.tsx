import { useState } from "react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";

import { GlassCard } from "../../components/GlassCard";
import { NumberField } from "../../components/NumberField";
import { PageHeader } from "../../components/PageHeader";
import { RunJobPanel } from "../../components/RunJobPanel";
import { useJobPolling } from "../../hooks/useJobPolling";

interface ComputeCostRow {
  method: string;
  n_dimensions: number;
  wall_seconds: number;
  grid_nodes: number | null;
  price: number;
}

interface PdeSolverPayload {
  rows: ComputeCostRow[];
}

export function PdeSolverLab() {
  const { state, submit } = useJobPolling("pde_solver");
  const [strike, setStrike] = useState(100);
  const [volatility, setVolatility] = useState(0.2);

  const payload = state.phase === "done" ? (state.artifact.pde_solver as PdeSolverPayload) : null;

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="PDE solvers"
        description="A classical finite-difference grid, a physics-informed neural network (PINN), and a deep-BSDE solver, all priced against the same Black-Scholes option -- compute-cost and accuracy compared directly."
      />
      <RunJobPanel
        state={state}
        onRun={() =>
          submit({
            seed: 0,
            risk_free_rate: 0.05,
            volatility,
            maturity: 1.0,
            strike,
            n_space_grid_1d: 400,
            pinn_epochs: 100,
            bsde_epochs: 20,
          })
        }
        configFields={
          <>
            <NumberField label="Strike" value={strike} onChange={setStrike} min={1} />
            <NumberField label="Volatility" value={volatility} onChange={setVolatility} step={0.01} min={0.01} />
          </>
        }
      />
      {payload && (
        <>
          <GlassCard className="p-6">
            <p className="mb-4 text-sm font-medium text-slate-300">Wall-clock cost by method</p>
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={payload.rows}>
                <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="method" stroke="#64748b" fontSize={12} />
                <YAxis stroke="#64748b" fontSize={12} />
                <Tooltip contentStyle={{ background: "#12151c", border: "1px solid rgba(255,255,255,0.1)" }} />
                <Bar dataKey="wall_seconds" fill="#8b5cf6" radius={[6, 6, 0, 0]} name="wall seconds" />
              </BarChart>
            </ResponsiveContainer>
          </GlassCard>
          <GlassCard className="overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-white/10 text-left text-xs uppercase tracking-wider text-slate-500">
                  <th className="px-4 py-3">Method</th>
                  <th className="px-4 py-3">Price</th>
                  <th className="px-4 py-3">Wall seconds</th>
                  <th className="px-4 py-3">Grid nodes</th>
                </tr>
              </thead>
              <tbody>
                {payload.rows.map((row) => (
                  <tr key={row.method} className="border-b border-white/5 text-slate-300">
                    <td className="px-4 py-3">{row.method}</td>
                    <td className="px-4 py-3">{row.price.toFixed(4)}</td>
                    <td className="px-4 py-3">{row.wall_seconds.toFixed(3)}</td>
                    <td className="px-4 py-3">{row.grid_nodes ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </GlassCard>
        </>
      )}
    </div>
  );
}
