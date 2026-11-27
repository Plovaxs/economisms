import React from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { SettingsProvider } from "./settings/SettingsProvider";
import { applyToElement, loadSettings, readEnvironment, resolve } from "./settings/settings";
// Self-hosted (bundled by Vite into /assets), not loaded from Google Fonts:
// the gateway's Content-Security-Policy allows no third-party origin, and a
// UI that phones a font CDN on every load also breaks air-gapped use and
// tells that CDN who opened it. Latin subset only, at the weights the UI uses.
import "@fontsource/inter/latin-400.css";
import "@fontsource/inter/latin-500.css";
import "@fontsource/inter/latin-600.css";
import "@fontsource/inter/latin-700.css";
import "@fontsource/jetbrains-mono/latin-400.css";
import "@fontsource/jetbrains-mono/latin-500.css";
import "@fontsource/jetbrains-mono/latin-600.css";
import "./styles/tokens.css";

// Apply the saved theme before React renders, so a non-default theme does not flash the default one.
applyToElement(document.documentElement, resolve(loadSettings(), readEnvironment()));

const rootElement = document.getElementById("root");
if (!rootElement) {
  throw new Error("root element not found");
}

ReactDOM.createRoot(rootElement).render(
  <React.StrictMode>
    <SettingsProvider>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </SettingsProvider>
  </React.StrictMode>,
);
