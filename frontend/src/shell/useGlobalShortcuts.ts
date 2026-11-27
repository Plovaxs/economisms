import { useEffect } from "react";

import { THEMES } from "../settings/themes";
import { WORKSPACES } from "./nav";
import type { Settings } from "../settings/settings";

interface Handlers {
  openPalette: () => void;
  openShortcuts: () => void;
  navigate: (to: string) => void;
  settings: Settings;
  update: (patch: Partial<Settings>) => void;
}

function typingTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  return target.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(target.tagName);
}

/** The next theme id after the current one (a "system" setting counts as the first theme). */
export function nextTheme(current: string): string {
  const ids = THEMES.map((t) => t.id);
  const index = ids.indexOf(current);
  return ids[(index + 1) % ids.length];
}

export function useGlobalShortcuts({ openPalette, openShortcuts, navigate, settings, update }: Handlers) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        openPalette();
        return;
      }
      if (e.altKey && !e.ctrlKey && !e.metaKey) {
        const workspace = WORKSPACES.find((w) => w.key === e.key);
        if (workspace) {
          e.preventDefault();
          navigate(workspace.home);
          return;
        }
        const k = e.key.toLowerCase();
        if (k === "t") {
          e.preventDefault();
          update({ theme: nextTheme(settings.theme) });
        } else if (k === "m") {
          e.preventDefault();
          update({ motion: settings.motion === "reduced" ? "full" : "reduced" });
        } else if (k === "b") {
          e.preventDefault();
          update({ sidebar: settings.sidebar === "hidden" ? "left" : "hidden" });
        }
        return;
      }
      if (typingTarget(e.target) || e.ctrlKey || e.metaKey || e.altKey) return;
      if (e.key === "/") {
        e.preventDefault();
        openPalette();
      } else if (e.key === "?") {
        e.preventDefault();
        openShortcuts();
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [openPalette, openShortcuts, navigate, settings, update]);
}
