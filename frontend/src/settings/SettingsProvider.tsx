import { useCallback, useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";

import { SettingsContext } from "./useSettings";
import type { SettingsApi } from "./useSettings";
import {
  DEFAULT_SETTINGS,
  ENVIRONMENT_QUERIES,
  applyToElement,
  loadSettings,
  readEnvironment,
  resolve,
  saveSettings,
} from "./settings";
import type { Environment, Settings } from "./settings";

// Owns the settings: loads them, applies them to <html> (attributes and CSS variables), saves every
// change, and re-resolves "system" the moment the operating system's preference changes.

interface Props {
  children: ReactNode;
  /** tests inject these; the app uses the real storage and window */
  initial?: Settings;
  environment?: Environment;
}

export function SettingsProvider({ children, initial, environment }: Props) {
  const [settings, setSettings] = useState<Settings>(() => initial ?? loadSettings());
  const [env, setEnv] = useState<Environment>(() => environment ?? readEnvironment());
  const [persisted, setPersisted] = useState(false);
  const resolved = useMemo(() => resolve(settings, env), [settings, env]);

  useEffect(() => {
    applyToElement(document.documentElement, resolved);
  }, [resolved]);

  useEffect(() => {
    if (initial) return; // injected settings are not written back
    setPersisted(saveSettings(settings));
  }, [settings, initial]);

  useEffect(() => {
    if (environment || typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const lists = ENVIRONMENT_QUERIES.map((q) => window.matchMedia(q));
    const onChange = () => setEnv(readEnvironment());
    lists.forEach((l) => l.addEventListener?.("change", onChange));
    return () => lists.forEach((l) => l.removeEventListener?.("change", onChange));
  }, [environment]);

  const update = useCallback((patch: Partial<Settings>) => setSettings((s) => ({ ...s, ...patch })), []);
  const replace = useCallback((next: Settings) => setSettings(next), []);
  const reset = useCallback(() => setSettings({ ...DEFAULT_SETTINGS }), []);

  const api = useMemo<SettingsApi>(
    () => ({ settings, resolved, environment: env, persisted, update, replace, reset }),
    [settings, resolved, env, persisted, update, replace, reset],
  );
  return <SettingsContext.Provider value={api}>{children}</SettingsContext.Provider>;
}
