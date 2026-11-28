import { useEffect, useState } from "react";
import { NavLink } from "react-router-dom";

import { DEMO } from "../demo/demo";
import { useSettings } from "../settings/useSettings";
import { nextTheme } from "./useGlobalShortcuts";
import { WORKSPACES, type WorkspaceId } from "./nav";

interface Props {
  workspace: WorkspaceId;
  title: string;
  onPalette: () => void;
}

function useClock(enabled: boolean): string {
  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    if (!enabled) return;
    const id = window.setInterval(() => setNow(new Date()), 30_000);
    return () => window.clearInterval(id);
  }, [enabled]);
  return now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

// A status bar in the spirit of waybar: workspaces on the left, the page in the middle, the things a
// person reaches for (gate state, theme, palette, settings, clock) on the right.
export function TopBar({ workspace, title, onPalette }: Props) {
  const { settings, resolved, update } = useSettings();
  const clock = useClock(settings.clock);
  return (
    <header
      role="banner"
      className="shell-panel mx-3 mt-3 flex flex-wrap items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-3 py-2 backdrop-blur-xl"
    >
      <nav aria-label="Workspaces" className="flex items-center gap-1">
        {WORKSPACES.map((w) => (
          <NavLink
            key={w.id}
            to={w.home}
            aria-label={`${w.label} (Alt ${w.key})`}
            aria-current={workspace === w.id ? "page" : undefined}
            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1 text-sm transition-colors ${
              workspace === w.id
                ? "bg-accent-gradient font-medium text-on-accent"
                : "text-slate-300 hover:bg-white/10 hover:text-slate-50"
            }`}
          >
            <span className="font-mono text-xs">{w.key}</span>
            <span className="hidden sm:inline">{w.label}</span>
          </NavLink>
        ))}
      </nav>
      <div className="min-w-0 flex-1 truncate text-center text-sm text-slate-300">{title}</div>
      <div className="flex items-center gap-2 text-sm">
        <span
          title="This project's own gate decision: research and simulation only, never live trading."
          className="rounded-full border border-bad/40 bg-bad/10 px-2.5 py-0.5 text-xs font-medium text-bad"
        >
          research only · NO-GO
        </span>
        {DEMO && (
          <span className="rounded-full border border-warn/40 bg-warn/10 px-2.5 py-0.5 text-xs font-medium text-warn">
            demo
          </span>
        )}
        <button
          type="button"
          onClick={() => update({ theme: nextTheme(resolved.theme.id) })}
          title="Next theme (Alt T)"
          className="rounded-lg border border-white/10 px-2.5 py-1 text-slate-200 hover:bg-white/10"
        >
          <span aria-hidden="true" className="mr-1.5 inline-block h-2.5 w-2.5 rounded-full bg-accent-gradient" />
          {resolved.theme.name}
        </button>
        <button
          type="button"
          onClick={onPalette}
          title="Command palette (Ctrl K)"
          aria-label="Open the command palette"
          className="rounded-lg border border-white/10 px-2.5 py-1 text-slate-200 hover:bg-white/10"
        >
          <kbd className="font-mono text-xs">Ctrl K</kbd>
        </button>
        {settings.clock && (
          <time className="font-mono text-xs text-slate-400" aria-label="Local time">
            {clock}
          </time>
        )}
      </div>
    </header>
  );
}
