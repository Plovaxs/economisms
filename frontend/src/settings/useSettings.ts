import { createContext, useContext } from "react";

import { DEFAULT_ENVIRONMENT, DEFAULT_SETTINGS, resolve } from "./settings";
import type { Environment, Resolved, Settings } from "./settings";

export interface SettingsApi {
  settings: Settings;
  resolved: Resolved;
  environment: Environment;
  /** false when the browser would not let the settings be saved (they still apply for this visit) */
  persisted: boolean;
  update: (patch: Partial<Settings>) => void;
  replace: (next: Settings) => void;
  reset: () => void;
}

const FALLBACK: SettingsApi = {
  settings: DEFAULT_SETTINGS,
  resolved: resolve(DEFAULT_SETTINGS, DEFAULT_ENVIRONMENT),
  environment: DEFAULT_ENVIRONMENT,
  persisted: false,
  update: () => {},
  replace: () => {},
  reset: () => {},
};

/** Components render without a provider (in tests, say) with the default settings. */
export const SettingsContext = createContext<SettingsApi>(FALLBACK);

export function useSettings(): SettingsApi {
  return useContext(SettingsContext);
}

export function useChartTheme() {
  return useSettings().resolved.chart;
}
