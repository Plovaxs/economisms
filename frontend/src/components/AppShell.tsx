import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { NavLink, useLocation, useNavigate } from "react-router-dom";

import { DemoBanner } from "../demo/DemoBanner";
import { useSettings } from "../settings/useSettings";
import { CommandPalette } from "../shell/CommandPalette";
import { ShortcutsDialog } from "../shell/ShortcutsDialog";
import { TopBar } from "../shell/TopBar";
import { buildCommands } from "../shell/commands";
import { NAV_ITEMS, titleOf, workspaceOf } from "../shell/nav";
import { useGlobalShortcuts } from "../shell/useGlobalShortcuts";

interface AppShellProps {
  children: ReactNode;
}

const SECTIONS: { title: string; group: string }[] = [
  { title: "Dashboard", group: "dashboard" },
  { title: "Deep Learning Lab", group: "labs" },
  { title: "Model zoo", group: "zoo" },
  { title: "Preferences", group: "settings" },
];

function NavSection({ title, group }: { title: string; group: string }) {
  const links = NAV_ITEMS.filter((i) => i.group === group);
  return (
    <div>
      <p className="px-3 text-xs font-semibold uppercase tracking-wider text-slate-500">{title}</p>
      <nav aria-label={title} className="mt-2 flex flex-col gap-0.5">
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
            {link.label.replace(/ lab$/, "")}
          </NavLink>
        ))}
      </nav>
    </div>
  );
}

export function AppShell({ children }: AppShellProps) {
  const { settings, update, reset } = useSettings();
  const location = useLocation();
  const navigate = useNavigate();
  const [palette, setPalette] = useState(false);
  const [shortcuts, setShortcuts] = useState(false);
  const main = useRef<HTMLElement>(null);
  const first = useRef(true);
  const title = titleOf(location.pathname);

  const openPalette = useCallback(() => setPalette(true), []);
  const openShortcuts = useCallback(() => setShortcuts(true), []);
  const closePalette = useCallback(() => setPalette(false), []);
  const closeShortcuts = useCallback(() => setShortcuts(false), []);
  const go = useCallback((to: string) => navigate(to), [navigate]);

  useGlobalShortcuts({ openPalette, openShortcuts, navigate: go, settings, update });

  const commands = useMemo(
    () => buildCommands({ navigate: go, settings, update, reset, openShortcuts }),
    [go, settings, update, reset, openShortcuts],
  );

  // After a navigation, name the new page for the screen reader and the tab, and move focus to it.
  useEffect(() => {
    document.title = `${title} · ECONOSIM`;
    if (first.current) {
      first.current = false;
      return;
    }
    main.current?.focus({ preventScroll: true });
  }, [location.pathname, title]);

  const sidebar = settings.sidebar;
  const aside = sidebar !== "hidden" && (
    <aside
      aria-label="Sections"
      className="shell-panel w-60 shrink-0 overflow-y-auto rounded-2xl border border-white/10 bg-white/[0.03] px-3 py-5 backdrop-blur-xl"
    >
      <div className="px-3 pb-5">
        <span className="bg-accent-gradient bg-clip-text text-lg font-semibold tracking-tight text-transparent">
          ECONOSIM
        </span>
        <p className="font-mono text-[11px] tracking-widest text-slate-500">PROMETHEUS-X</p>
      </div>
      <div className="flex flex-col gap-6">
        {SECTIONS.map((s) => (
          <NavSection key={s.group} title={s.title} group={s.group} />
        ))}
      </div>
    </aside>
  );

  return (
    <div className="flex h-screen flex-col">
      <a href="#main" className="skip-link">
        Skip to the content
      </a>
      {settings.topBar && <TopBar workspace={workspaceOf(location.pathname)} title={title} onPalette={openPalette} />}
      <div className={`flex min-h-0 flex-1 gap-3 p-3 ${sidebar === "right" ? "flex-row-reverse" : ""}`}>
        {aside}
        <main
          id="main"
          ref={main}
          tabIndex={-1}
          aria-label={title}
          className="shell-panel min-w-0 flex-1 overflow-y-auto rounded-2xl border border-accent-a/30 bg-white/[0.02] px-8 py-8 shadow-glow focus:outline-none"
        >
          <div className="mx-auto max-w-5xl">
            <DemoBanner />
            {children}
          </div>
        </main>
      </div>
      <div role="status" aria-live="polite" className="sr-only-live">
        {title}
      </div>
      <CommandPalette open={palette} onClose={closePalette} commands={commands} />
      <ShortcutsDialog open={shortcuts} onClose={closeShortcuts} />
    </div>
  );
}
