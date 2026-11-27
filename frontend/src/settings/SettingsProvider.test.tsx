import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { DEFAULT_ENVIRONMENT, DEFAULT_SETTINGS, STORAGE_KEY } from "./settings";
import { SettingsProvider } from "./SettingsProvider";
import { useSettings } from "./useSettings";

function Probe() {
  const { settings, resolved, update, reset, persisted } = useSettings();
  return (
    <div>
      <output data-testid="theme">{resolved.theme.id}</output>
      <output data-testid="persisted">{String(persisted)}</output>
      <output data-testid="scale">{settings.fontScale}</output>
      <button onClick={() => update({ theme: "nord", fontScale: 1.3 })}>nord</button>
      <button onClick={() => update({ theme: "system" })}>system</button>
      <button onClick={reset}>reset</button>
    </div>
  );
}

beforeEach(() => {
  window.localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("SettingsProvider", () => {
  it("applies the settings to the document element, saves them, and can reset", () => {
    render(
      <SettingsProvider>
        <Probe />
      </SettingsProvider>,
    );
    expect(document.documentElement.getAttribute("data-theme")).toBe("aurora");
    fireEvent.click(screen.getByText("nord"));
    expect(screen.getByTestId("theme")).toHaveTextContent("nord");
    expect(document.documentElement.getAttribute("data-theme")).toBe("nord");
    expect(document.documentElement.getAttribute("data-font-scale")).toBe("1.3");
    expect(document.documentElement.style.getPropertyValue("--accent-a")).toBe("136 192 208");
    expect(JSON.parse(window.localStorage.getItem(STORAGE_KEY) ?? "{}").theme).toBe("nord");
    expect(screen.getByTestId("persisted")).toHaveTextContent("true");
    fireEvent.click(screen.getByText("reset"));
    expect(document.documentElement.getAttribute("data-theme")).toBe(DEFAULT_SETTINGS.theme);
  });

  it("loads what was saved on the previous visit", () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ theme: "gruvbox", fontScale: 1.15 }));
    render(
      <SettingsProvider>
        <Probe />
      </SettingsProvider>,
    );
    expect(screen.getByTestId("theme")).toHaveTextContent("gruvbox");
    expect(screen.getByTestId("scale")).toHaveTextContent("1.15");
  });

  it("follows the system for 'system' and does not write injected settings back", () => {
    render(
      <SettingsProvider environment={{ ...DEFAULT_ENVIRONMENT, prefersDark: false }}>
        <Probe />
      </SettingsProvider>,
    );
    fireEvent.click(screen.getByText("system"));
    expect(screen.getByTestId("theme")).toHaveTextContent("catppuccin-latte");
    act(() => {});
    render(
      <SettingsProvider initial={{ ...DEFAULT_SETTINGS, theme: "kanagawa" }}>
        <Probe />
      </SettingsProvider>,
    );
    expect(screen.getAllByTestId("theme").some((n) => n.textContent === "kanagawa")).toBe(true);
  });

  it("survives a store that refuses writes", () => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = () => {
      throw new Error("quota");
    };
    try {
      render(
        <SettingsProvider>
          <Probe />
        </SettingsProvider>,
      );
      fireEvent.click(screen.getByText("nord"));
      expect(screen.getByTestId("theme")).toHaveTextContent("nord");
      expect(screen.getByTestId("persisted")).toHaveTextContent("false");
    } finally {
      Storage.prototype.setItem = original;
    }
  });
});
