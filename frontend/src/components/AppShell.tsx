import type { ReactNode } from "react";
import { NavLink } from "react-router-dom";

interface AppShellProps {
  children: ReactNode;
}

const DASHBOARD_LINKS = [
  { to: "/", label: "Overview" },
  { to: "/economy", label: "Economy explorer" },
  { to: "/balance-sheets", label: "Balance sheets" },
  { to: "/market-paths", label: "Market paths" },
  { to: "/pricing", label: "Pricing diagnostics" },
  { to: "/hedge-actions", label: "Hedge actions" },
  { to: "/portfolio-risk", label: "Portfolio risk" },
  { to: "/experiments", label: "Experiments" },
  { to: "/audit-trail", label: "Audit trail" },
  { to: "/validation-issues", label: "Validation issues" },
  { to: "/model-usage", label: "Model usage" },
];

const LAB_LINKS = [
  { to: "/lab/qmacro", label: "Q-MACRO" },
  { to: "/lab/recessionnet", label: "RECESSIONNET" },
  { to: "/lab/inflationcast", label: "INFLATIONCAST" },
  { to: "/lab/neural-sde", label: "Neural SDE" },
  { to: "/lab/pde-solver", label: "PDE solver" },
  { to: "/lab/marl", label: "Multi-agent RL" },
  { to: "/lab/rl-hedge", label: "RL hedging" },
];

function NavSection({
  title,
  links,
}: {
  title: string;
  links: { to: string; label: string }[];
}) {
  return (
    <div>
      <p className="px-3 text-xs font-semibold uppercase tracking-wider text-slate-500">
        {title}
      </p>
      <nav className="mt-2 flex flex-col gap-0.5">
        {links.map((link) => (
          <NavLink
            key={link.to}
            to={link.to}
            end={link.to === "/"}
            className={({ isActive }) =>
              `relative rounded-lg px-3 py-2 text-sm transition-colors duration-200 ${
                isActive
                  ? "bg-white/10 text-slate-50 shadow-glow before:absolute before:inset-y-1 before:left-0 before:w-0.5 before:rounded-full before:bg-accent-gradient"
                  : "text-slate-400 hover:bg-white/5 hover:text-slate-200"
              }`
            }
          >
            {link.label}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export function AppShell({ children }: AppShellProps) {
  return (
    <div className="flex min-h-screen">
      <aside className="w-64 shrink-0 border-r border-white/10 bg-white/[0.02] px-3 py-6 backdrop-blur-xl">
        <div className="px-3 pb-6">
          <span className="bg-accent-gradient bg-clip-text text-lg font-semibold tracking-tight text-transparent">
            ECONOSIM
          </span>
          <p className="font-mono text-[11px] tracking-widest text-slate-500">
            PROMETHEUS-X
          </p>
        </div>
        <div className="flex flex-col gap-6">
          <NavSection title="Dashboard" links={DASHBOARD_LINKS} />
          <NavSection title="Deep Learning Lab" links={LAB_LINKS} />
        </div>
      </aside>
      <main className="flex-1 overflow-y-auto px-8 py-8">
        <div className="mx-auto max-w-5xl">{children}</div>
      </main>
    </div>
  );
}
