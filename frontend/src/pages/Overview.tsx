import { GlassCard } from "../components/GlassCard";

const DASHBOARD_COUNT = 11;
const LAB_COUNT = 7;

export function Overview() {
  return (
    <div className="flex flex-col gap-6">
      <GlassCard className="p-8">
        <h1 className="bg-accent-gradient bg-clip-text text-3xl font-semibold text-transparent">
          ECONOSIM / PROMETHEUS-X
        </h1>
        <p className="mt-3 max-w-2xl text-sm leading-relaxed text-slate-400">
          Deep Learning for Quantitative Economics and Neural Finance:
          classical econometrics, deep learning, and hybrid quantum
          models benchmarked side by side on real computed output. Every
          number on every page below comes from a live run of the actual
          Python backend -- nothing here is a placeholder or a canned
          screenshot.
        </p>
      </GlassCard>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <GlassCard className="p-6" delay={0.05}>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Dashboard
          </p>
          <p className="mt-2 text-2xl font-semibold text-slate-100">{DASHBOARD_COUNT} views</p>
          <p className="mt-1 text-sm text-slate-400">
            Economy, pricing, hedging, risk, audit and governance views over
            this project&apos;s simulation and evidence subsystems.
          </p>
        </GlassCard>
        <GlassCard className="p-6" delay={0.1}>
          <p className="text-xs font-semibold uppercase tracking-wider text-slate-500">
            Deep Learning Lab
          </p>
          <p className="mt-2 text-2xl font-semibold text-slate-100">{LAB_COUNT} engines</p>
          <p className="mt-1 text-sm text-slate-400">
            Submit a real training/benchmark job for Q-MACRO, RECESSIONNET,
            INFLATIONCAST, the neural SDE, the PDE solvers, multi-agent RL,
            or the REINFORCE hedging agent, and watch it resolve to a real
            result.
          </p>
        </GlassCard>
      </div>
    </div>
  );
}
