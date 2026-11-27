// The routes of the app and how they group into "workspaces" (Hyprland-style: Alt+1 to Alt+5).

export interface NavItem {
  to: string;
  label: string;
  group: WorkspaceId;
  keywords?: string;
}

export type WorkspaceId = "overview" | "dashboard" | "labs" | "zoo" | "settings";

export interface Workspace {
  id: WorkspaceId;
  label: string;
  key: string;
  home: string;
}

export const WORKSPACES: readonly Workspace[] = [
  { id: "overview", label: "Overview", key: "1", home: "/" },
  { id: "dashboard", label: "Dashboard", key: "2", home: "/economy" },
  { id: "labs", label: "Labs", key: "3", home: "/lab/qmacro" },
  { id: "zoo", label: "Model zoo", key: "4", home: "/atlas" },
  { id: "settings", label: "Settings", key: "5", home: "/settings" },
];

export const NAV_ITEMS: readonly NavItem[] = [
  { to: "/", label: "Overview", group: "overview", keywords: "home start" },
  { to: "/economy", label: "Economy explorer", group: "dashboard", keywords: "ledger macro shocks" },
  { to: "/balance-sheets", label: "Balance sheets", group: "dashboard", keywords: "assets liabilities equity" },
  { to: "/market-paths", label: "Market paths", group: "dashboard", keywords: "gbm percentile simulation" },
  { to: "/pricing", label: "Pricing diagnostics", group: "dashboard", keywords: "black scholes greeks option" },
  { to: "/hedge-actions", label: "Hedge actions", group: "dashboard", keywords: "delta hedge ratio" },
  { to: "/portfolio-risk", label: "Portfolio risk", group: "dashboard", keywords: "var expected shortfall drawdown" },
  { to: "/experiments", label: "Experiments", group: "dashboard", keywords: "comparison verdict null negative" },
  { to: "/audit-trail", label: "Audit trail", group: "dashboard", keywords: "model registry" },
  { to: "/validation-issues", label: "Validation issues", group: "dashboard", keywords: "findings log" },
  { to: "/model-usage", label: "Model usage", group: "dashboard", keywords: "authorised application" },
  { to: "/lab/qmacro", label: "Q-MACRO lab", group: "labs", keywords: "factor forecast quantum" },
  { to: "/lab/recessionnet", label: "RECESSIONNET lab", group: "labs", keywords: "recession classification" },
  { to: "/lab/inflationcast", label: "INFLATIONCAST lab", group: "labs", keywords: "cpi nowcast" },
  { to: "/lab/neural-sde", label: "Neural SDE lab", group: "labs", keywords: "stochastic differential equation" },
  { to: "/lab/pde-solver", label: "PDE solver lab", group: "labs", keywords: "pinn bsde grid" },
  { to: "/lab/marl", label: "Multi-agent RL lab", group: "labs", keywords: "ppo household" },
  { to: "/lab/rl-hedge", label: "RL hedging lab", group: "labs", keywords: "reinforce cvar" },
  { to: "/atlas", label: "Atlas: the model zoo", group: "zoo", keywords: "graph web 3d models registry" },
  { to: "/settings", label: "Settings", group: "settings", keywords: "theme accessibility font contrast motion" },
];

export function workspaceOf(pathname: string): WorkspaceId {
  const hit = NAV_ITEMS.find((i) => i.to === pathname);
  if (hit) return hit.group;
  if (pathname.startsWith("/lab/")) return "labs";
  return "overview";
}

export function titleOf(pathname: string): string {
  return NAV_ITEMS.find((i) => i.to === pathname)?.label ?? "Overview";
}
